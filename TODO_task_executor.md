# TODO - 任务执行器改造（独立）

## 1. 改造目标与边界
- [x] 把“定时器触发 + 大循环扫描”改成“任务队列 + 任务执行器 + 任务级调度”。
- [x] 在不破坏现有策略能力的前提下，实现可灰度切换（保留旧 `BotWorker/check_farm` 入口）。
- [ ] 统一中断语义：点击、等待、截图、页面确认都可被 `stop_event` 及时打断。
- [x] 引入队列可观测性：运行中、待执行、等待中三态可见。

## 2. 当前现状（项目实际代码）
- 调度层：`core/task_scheduler.py`
  - 当前是 `QTimer(farm) + QTimer(friend)` 双定时器触发，只有“到点触发”语义。
  - 动态调度仅体现在 `set_farm_interval(seconds)`，缺少任务级延迟控制。
- 执行层：`core/bot_engine.py`
  - `BotWorker` 只有 `farm/friend` 两类任务，且同一时刻只能运行一个 worker（`_spawn_worker`）。
  - `check_farm()` 是 50 轮硬循环，调度和业务耦合严重。
- 可观测性：`gui/widgets/status_panel.py`
  - 仅展示总状态与动作计数，无 `running/pending/waiting` 队列视图。

## 3. NIKKE 参考基线（根目录 `NIKKE`）
- `NIKKE/module/config/config.py`
  - `pending_task / waiting_task`
  - `get_next_task()`
  - `task_delay(...) / task_call(...)`
- `NIKKE/main.py`
  - `loop() -> get_next_task() -> run(task)` 主循环
  - 失败计数和熔断统一在调度循环处理

## 4. 目标架构与落地点

### 4.1 任务模型（新增 `core/task_registry.py`）
- [x] 定义 `TaskItem`
  - `name`, `enabled`, `priority`, `next_run`
  - `success_interval`, `failure_interval`
  - `max_failures`, `failure_count`
- [x] 定义 `TaskResult`
  - `success`, `actions`, `next_run_seconds`
  - `need_recover`, `error`
- [x] 定义 `TaskSnapshot`
  - `running_task`, `pending_tasks`, `waiting_tasks`

### 4.2 队列选择与调度接口（新增 `core/task_queue.py` 或并入 `task_executor.py`）
- [x] 任务分类：
  - `next_run <= now` -> pending
  - `next_run > now` -> waiting
- [x] 排序规则：
  - pending：priority -> next_run
  - waiting：next_run 升序
- [x] 调度接口：
  - `get_next_task(now)`
  - `snapshot(now)`
  - `task_delay(task, seconds|target_time)`
  - `task_call(task, force=True)`

### 4.3 统一执行循环（新增 `core/task_executor.py`）
- [x] 主循环：`select_next_task -> run_task_once -> apply_delay -> update_failure_record`
- [x] 空队列策略：
  - `stay`
  - `goto_main`
- [x] 失败熔断：
  - 连续失败达到阈值后降级延迟并上报 UI
- [ ] 停止语义统一：
  - 执行器持有单一 `stop_event`
  - `BaseStrategy.sleep`、`ActionExecutor._sleep_interruptible`、执行器 wait 共用 stop 检查

### 4.4 与 `BotEngine` 的集成（修改 `core/bot_engine.py`）
- [x] 新增模式开关：`engine_mode = legacy|executor`（默认 `legacy`）
- [x] `start()` 路由：
  - `legacy`：沿用 `TaskScheduler + BotWorker`
  - `executor`：启动 `TaskExecutor` 线程
- [x] `stop/pause/resume/run_once` 统一语义：
  - `run_once` => `task_call('farm_main')`
  - pause 仅暂停取任务，stop 强中断
- [x] `stats_updated` 增加队列摘要字段

## 5. 任务迁移顺序（执行器专项）
- [x] 第一批任务接入：
  - `farm_main`
  - `friend`
- [ ] 迁移原则：
  - 旧策略逻辑尽量不改行为，仅改调度归属
  - 统一任务签名：`run_once(ctx) -> TaskResult`
  - 禁止任务内部直接改全局调度周期
- [ ] 清理旧耦合：
  - `scheduler.set_farm_interval(...)` -> `task_delay('farm_main', seconds)`
  - `check_farm` 里的“下次检查时间”逻辑迁到任务结果处理层

## 6. 配置与 UI 对齐
- [x] 修改 `models/config.py`：
  - `executor.enabled`
  - `executor.empty_queue_policy`
  - `executor.default_success_interval`
  - `executor.default_failure_interval`
- [x] GUI 增强（`gui/widgets/status_panel.py` + 新增 `task_queue_panel.py`）：
  - 展示 `running / pending / waiting`
  - “立即执行”按钮触发 `task_call('farm_main')`

## 7. 测试与验收（执行器专项）
- [ ] 单元测试：
  - `pending/waiting` 分类
  - `task_delay/task_call` 结果
  - 失败计数与熔断
- [ ] 集成测试：
  - `executor` 模式稳定运行 1 小时+
  - stop 后 500ms 内不再产生新点击（允许当前点击完成）
- [ ] 验收指标：
  - 队列可视化可见运行中任务与 next run
  - 调度行为不再依赖单一 `farm_interval`

## 8. 最近可执行项（仅任务执行器）
- [x] 建 `core/task_registry.py`（`TaskItem/TaskResult/TaskSnapshot`）
- [x] 建 `core/task_executor.py` 最小循环（先接 `farm_main/friend`）
- [x] 在 `BotEngine` 增加 `legacy|executor` 模式切换
- [x] 在状态页加队列简版展示（running/pending/waiting）

## 9. 改造执行步骤（可直接开工）
1. [ ] 冻结现状与基线：记录当前 `legacy` 路径的行为、耗时与停止响应时间。
2. [ ] 建任务模型与注册表：落地 `TaskItem/TaskResult/TaskSnapshot`。
3. [ ] 建任务队列与调度接口：实现 `get_next_task/snapshot/task_delay/task_call`。
4. [ ] 建执行器主循环：支持 stop/pause、空队列策略、失败计数。
5. [ ] 接入 BotEngine 灰度开关：打通 `engine_mode=legacy|executor`。
6. [ ] 首批迁移任务：先迁 `farm_main`、`friend` 为 `run_once(ctx)->TaskResult`。
7. [ ] UI 与配置对齐：补执行器配置项，显示 `running/pending/waiting`。
8. [ ] 回归与切换：单测+集测通过后默认切 `executor`，保留 `legacy` 回滚。
