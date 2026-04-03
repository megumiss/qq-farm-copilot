# TODO - 其他改造（页面状态机、导航、策略、稳定性、观测）

> 任务执行器改造已独立到：`TODO_task_executor.md`

## 0. 现状与参考基线（非执行器部分）

### 0.1 当前项目现状
- 场景识别：`core/scene_detector.py`
  - 已有严格/回退两阶段识别，但缺少页面图导航和统一跳转预算。
- 业务流程：`core/bot_engine.py` + `core/strategies/*.py`
  - `check_farm()` 内聚合页面识别、策略优先级、异常恢复。
  - 策略接口不统一（`str | list[str]` 混用），部分策略内部重复处理弹窗/跳转。
- 观测：`gui/widgets/status_panel.py` / `gui/widgets/log_panel.py`
  - 缺少页面级、任务级耗时与跳转链路观测。

### 0.2 NIKKE 参考点
- 页面导航：`NIKKE/module/ui/ui.py` + `NIKKE/module/ui/page.py`
  - `ui_get_current_page() / ui_goto() / ui_ensure()`
  - 页面图 + 显式 links 的跳转模型
- 页面确认等待：`NIKKE/module/base/timer.py`
  - `confirm_wait` + 到达确认计数
- 可视化：`NIKKE/module/webui/app.py`
  - 状态区分和任务概览展示方式可借鉴

---

## 1. 页面图与导航器

### 1.1 页面图定义（新增 `core/page_graph.py`）
- [x] 页面枚举：`MAIN / POPUP / SHOP / BUY_CONFIRM / PLOT_MENU / SEED_SELECT / FRIEND / UNKNOWN`
- [x] 显式跳转边：
  - `MAIN -> SHOP`（`btn_shop`）
  - `SHOP -> MAIN`（`btn_shop_close`）
  - `MAIN -> FRIEND`（`btn_friend_help`）
  - `FRIEND -> MAIN`（`btn_home`）
  - `PLOT_MENU <-> SEED_SELECT`（点空地 / 选种子）
- [x] 提供 `next_action(current, target)`（BFS 最短下一跳）

### 1.2 导航器（新增 `core/navigator.py`）
- [x] `get_current_page()`：复用 `identify_scene` + 连续帧确认
- [x] `goto(target, timeout, retry)`：
  - 每次点击后 `confirm_wait`
  - 超时重试并可失败返回
- [x] `ensure(target)`：当前页不匹配时自动导航

## 2. 页面识别增强
- [x] 在 `core/scene_detector.py` 增加：
  - 识别超时回落 `UNKNOWN`
  - 高频噪声模板降权（`TemplateNoiseGuard`）
  - 稳定帧数参数化（替代硬编码）
- [x] 在 `core/bot_engine.py`：
  - `_expect_runtime_states` 从“动作描述字符串匹配”改为“动作类型 + 目标页映射”
- 当前状态：已完成首版（`scene_detector` 参数化阈值 + 噪声重复降权、`Navigator` 识别超时回落 `UNKNOWN`、`BotEngine` 按 `action_type` 优先映射期望状态）。

## 3. 全局 UI Guard（新增 `core/ui_guard.py`）
- [x] 统一处理可恢复弹窗：升级、任务奖励、商店残留、确认框
- [x] 主流程前置：
  - `ui_guard.handle_global_popups()`
  - `resolve_page()`
  - `dispatch(page_handler)`
- 当前状态：已完成 `ui_guard` 首版接入（POPUP/BUY_CONFIRM/SHOP 页面）。
- [x] 删除策略中重复的弹窗关闭分支，保留业务动作本身

## 4. 策略契约化与业务拆分
- [x] 统一策略契约：
  - `requires_page: set[PageId]`
  - `expected_page_after: set[PageId]`
  - `run_once(ctx) -> StrategyResult`
- 当前状态：`BaseStrategy` 与主要策略均已声明契约字段并提供 `run_once`。
- [x] `check_farm` 拆分为页面处理器：
  - `handle_main_page`
  - `handle_popup_page`
  - `handle_shop_page`
  - `handle_buy_confirm_page`
  - `handle_friend_page`
- 当前状态：已完成 `MAIN/POPUP/SHOP/BUY_CONFIRM/FRIEND/SEED_SELECT` 分发与 handler 化。
- [x] 移除 `for round in range(1, 51)`，改为 tick 分发
- [x] 策略返回值统一为 `StrategyResult`（替代 `str/list[str]`）
- 当前状态：`BotEngine` 分发层统一承接 `StrategyResult`，策略层通过 `run_once` 统一返回类型。

## 5. 稳定性与性能
- [x] `ActionCooldown`：动作防抖
- [x] `PageTransitionBudget`：跳转预算上限
- [x] 检测按页面裁剪类别：
  - `BUY_CONFIRM` 页仅检测 `button`
- [x] 输出关键耗时：
  - 识别耗时
  - 动作耗时
  - 单轮总耗时
- [x] 清理不可中断路径：
  - `core/strategies/plant.py`
  - `core/strategies/popup.py`
  - `core/strategies/task.py`

## 6. 观测与 GUI
- [x] 状态面板增加：
  - 当前页面
  - 当前任务
  - 连续失败计数
  - 队列摘要（running/pending/waiting 数量）
- [x] 新增任务详情面板：
  - 任务 next run
  - 最近一次执行结果和耗时
- [x] 日志结构化字段：
  - `task=... page=... action=... elapsed_ms=...`
- 当前状态：已接入“当前页面/当前任务/失败计数/队列摘要 + 上次结果/耗时”到状态面板。

## 7. 测试与验收
- [x] 导航回归：
  - 从 `UNKNOWN/POPUP/SHOP/FRIEND` 可在预算内回 `MAIN`
- [x] 行为回归：
  - 收获、维护、播种、出售、任务奖励、好友帮忙无行为退化
- [x] 性能验收：
  - 单轮识别耗时下降
  - 无效点击率下降
- 当前状态：离线回归脚本 `tools/todo_regression_check.py` 已通过；实机回归可在联机环境补充。

## 8. 实施顺序（其他改造）
1. [ ] 页面图 + 导航器最小闭环
2. [ ] UI Guard 接管全局弹窗
3. [ ] `check_farm` 按页面拆分，策略契约化
4. [ ] 性能优化（防抖、预算、噪声降权）
5. [ ] GUI 观测与结构化日志补齐

## 9. 改造执行步骤（可直接开工）
1. [ ] 页面图落地：新增 `core/page_graph.py`，补齐页面和跳转边。
2. [ ] 导航器落地：新增 `core/navigator.py`，实现 `get_current_page/goto/ensure`。
3. [ ] 全局 UI Guard：新增 `core/ui_guard.py`，统一弹窗和可恢复页面处理。
4. [ ] 主流程改为状态分发：`tick -> guard -> resolve_page -> dispatch`。
5. [ ] 策略契约统一：统一 `requires_page/expected_page_after/run_once`。
6. [ ] 稳定性与性能增强：接入 `ActionCooldown/TemplateNoiseGuard/PageTransitionBudget`。
7. [ ] 观测与 GUI 增强：补页面/任务/失败计数/耗时指标与结构化日志。
8. [ ] 全链路回归：完成导航、核心功能与性能验收。
