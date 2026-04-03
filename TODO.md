# TODO - 任务执行器与页面状态机改造

## 改造目标
- [ ] 将当前“全量扫描 + 大循环串行策略”改为“任务执行器 + 页面状态机 + 导航器”
- [ ] 降低误跳转与无效匹配开销
- [ ] 提升停止响应速度与任务可观测性

## 当前现状（简版）
- 调度：`core/task_scheduler.py` 用 `QTimer` 触发 farm/friend
- 执行：`BotWorker -> check_farm()`，`check_farm()` 内最多 50 轮循环
- 决策：每轮全量模板匹配 + 场景判定 + 优先级策略串行
- 校验：`_expect_runtime_states()` / `_verify_expected_runtime()`
- 问题：调度与业务耦合、长循环难中断、任务优先级与延迟机制弱、队列不可观测

## 参考基线（NIKKE）
- [ ] 任务调度循环：`main.py` 的 `loop() + get_next_task()`
- [ ] 队列模型：`pending_task / waiting_task + task_delay() / task_call()`
- [ ] 页面导航：`ui_ensure() / ui_goto()` 的页面感知跳转

## P0：页面与导航基础层

### P0-1 页面图（Page Graph）
- [ ] 新建 `core/page_graph.py`
- [ ] 定义页面：`MAIN / POPUP / SHOP / BUY_CONFIRM / PLOT_MENU / SEED_SELECT / FRIEND / UNKNOWN`
- [ ] 定义跳转边：打开商店、关闭弹窗、确认购买、回家等
- [ ] 提供最短下一跳接口：`next_action(current, target)`

### P0-2 页面识别器
- [ ] 在 `core/scene_detector.py` 增加 `resolve_page(...) -> PageId`
- [ ] 保留严格/回退两阶段识别
- [ ] 保留连续帧确认
- [ ] 增加识别超时与 `UNKNOWN` 回退

### P0-3 导航器
- [ ] 新建 `core/navigator.py`
- [ ] 实现 `get_current_page() / goto(target) / ensure(target)`
- [ ] 每次点击后加入确认等待（confirm wait）
- [ ] 超时重试与失败返回

### P0-4 全局 UI Guard
- [ ] 新建 `core/ui_guard.py`
- [ ] 统一处理关闭类弹窗、未知可恢复页面
- [ ] 主循环先执行 `handle_global_popups()` 再进入业务

## P0：任务执行器改造

### P0-5 任务模型与注册表
- [ ] 新建 `core/task_registry.py`
- [ ] 定义 `TaskItem`：`name/enabled/priority/next_run/max_failures`
- [ ] 定义 `TaskResult`：`success/actions/next_run_seconds/need_recover`
- [ ] 支持 `pending_tasks / waiting_tasks` 计算与输出

### P0-6 统一执行器
- [ ] 新建 `core/task_executor.py`
- [ ] 执行循环：`select_next_task -> run_task_once -> schedule_next`
- [ ] 支持 `task_delay(task, seconds|target)` 与 `task_call(task)`
- [ ] 停止语义统一为单一 `stop_event`，等待/截图/点击均可中断

### P0-7 与现有 BotEngine 并行接入
- [ ] 保留现有 `BotWorker` 路径，先做可切换运行（灰度）
- [ ] 先接 `farm_main`、`friend` 两个任务
- [ ] 保持 UI 线程安全：执行器发信号，UI 只做展示和控制

## P1：业务层迁移

### P1-1 策略契约化
- [ ] 策略声明 `requires_page`
- [ ] 策略声明 `expected_page_after`
- [ ] 执行标准化：`ensure -> action -> post-check`

### P1-2 拆分 `check_farm()`
- [ ] 拆为 `farm_main / maintenance / plant / expand / sell / task / friend_help`
- [ ] 移除 `check_farm()` 内调度职责，仅保留页面内动作
- [ ] 页面处理器最小化：`MAIN / SHOP / BUY_CONFIRM / POPUP / FRIEND`

### P1-3 执行流改为状态分发
- [ ] 新流程：`tick -> ui_guard -> resolve_page -> dispatch(page_handler)`
- [ ] 删除“最多 50 轮扫描”硬循环

## P2：稳定性与性能
- [ ] 动作冷却：`ActionCooldown`
- [ ] 高噪声模板降权：`TemplateNoiseGuard`
- [ ] 页面跳转预算：`PageTransitionBudget`
- [ ] 任务失败计数与熔断（连续失败保护）
- [ ] 任务级耗时统计（识别/动作/总耗时）
- [ ] UI 增加任务队列面板（运行中/待执行/等待中）

## 实施顺序（建议）
1. 页面图 + 页面识别 + 导航器最小闭环
2. UI Guard 接管全局弹窗
3. 任务模型与执行器落地（仅接 `farm_main/friend`）
4. `check_farm()` 拆分与任务化迁移
5. 节流、熔断、观测与 UI 面板完善

## 验收指标
- [ ] 误跳转次数明显下降（日志可量化）
- [ ] 单轮平均耗时下降
- [ ] 停止后残留动作显著减少
- [ ] 买种/出售/任务往返主页稳定
- [ ] 日志可看到 `running + pending + waiting` 任务摘要

## 下一个可执行动作
- [ ] 建立 `TaskItem/TaskResult` 与 `task_registry`（不改现有策略）
- [ ] 建 `task_executor` 骨架并接入 `farm_main/friend`
