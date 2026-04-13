# AGENTS

本文件定义本仓库内自动化/编码代理的工作约定。以当前代码实现为准。
- 每次修改完后，使用项目 `.venv` 下的 `ruff format` 进行代码格式化。
: 仅格式化 Python 文件，跳过 `json/md` 等非 Python 文件（避免改坏 JSON 语法与文档排版）。
: 推荐命令：`.\.venv\Scripts\python.exe -m ruff format core gui models tasks utils main.py private\main_window_core.py`

- `private/main_window_core.py` 与 `gui/main_window_core.pyd` 的关系与更新方式：
: `private/main_window_core.py` 是 GUI 源码；`gui/main_window_core.pyd` 是实际发布/默认运行加载的二进制产物。
: GUI 更新流程（必须遵守）：先改 `private/main_window_core.py`，验证通过后执行 `.\private\build_main_window_core_pyd.ps1` 重新编译并覆盖 `gui/main_window_core.pyd`。
: 首次编译先执行：`.\private\build_main_window_core_pyd.ps1 -InstallDeps`。


## 0. 当前状态

- 项目名：`QQ Farm Copilot`
- UI 结构：左侧截图预览 + 中间实例运行面板 + 最右侧竖向实例栏
- 实例纳管操作：`新增 / 删除 / 切换 / 克隆 / 重命名`
- 调度模式：`TaskExecutor` 单线程串行执行
- 任务配置：`%APPDATA%/QQFarmCopilot/instances/<instance_id>/configs/config.json -> tasks`（动态字典，包含持久化 `next_run`）
- 好友黑名单配置：`config.tasks.friend.features.blacklist`（`list[str]`，在任务设置详情弹窗维护）
- 高级配置：`config.safety.debug_log_enabled` 控制 Debug 日志输出
- 播种选种：`config.planting.warehouse_first` 默认开启；开启时优先按 `number_box_detector` 选择最左种子
- 等级同步：播种前执行等级 OCR；由 `config.planting.level_ocr_enabled` 控制，识别后回写 `config.planting.player_level`；QQ/微信 ROI 使用 `tasks/main.py` 内常量
- 窗口选择：`config.window_select_rule` 仅保存匹配顺序（`auto` / `index:N`），不保存 `hwnd`
- 视觉按钮来源：`core/ui/assets.py`（由 `tools/button_extract.py` 生成）

## 1. 核心架构与职责

- `core/engine/bot/engine.py`
: `BotEngine` 入口，组合 `bootstrap/executor/runtime/vision`。

- `core/instance/manager.py`
: 实例会话管理（实例增删改查、当前实例切换、元数据保存）。

- `core/engine/bot/runtime.py`
: 生命周期与会话控制（start/stop/pause/resume/run_once）、配置更新、可中断睡眠、坐标映射。

- `core/engine/bot/executor.py`
: 任务注册与调度桥接（自动发现 `_run_task_*`）。

- `core/engine/task/executor.py`
: 通用任务执行器（pending/waiting 队列、优先级排序、结果回写 next_run）。

- `core/tasks/*.py`
: 业务任务实现（`main/friend/share/reward` 及子任务）。

- `core/ui/ui.py` + `core/base/module_base.py`
: 页面识别、导航、弹窗清理、`appear/appear_then_click` 等模板点击能力。

## 2. 调度语义（必须遵守）

### 2.1 任务来源

- 执行器自动发现 `BotExecutorMixin` 中所有 `_run_task_<name>`。
- 任务启停与参数从 `config.tasks[<name>]` 读取。

### 2.2 排序规则

- 仅执行 `enabled=true` 且 `next_run <= now` 的任务。
- `pending` 队列按 `priority` 升序排序（值越小优先级越高）。
- 同一时刻到期任务按 `priority` 串行执行，不并发。

### 2.3 触发类型

- `trigger=interval`：按 `interval_seconds`。
- `trigger=daily`：按 `daily_time` 计算距离下一次秒数。
- `trigger=interval` 额外受 `enabled_time_range`（`HH:MM:SS-HH:MM:SS`）限制；不在时间段则跳过本轮并延迟到下个时间段起点。
- `interval_seconds` / `failure_interval_seconds` 生效下限为 `executor.min_task_interval_seconds`（默认 `5` 秒）。
- `TaskResult.next_run_seconds` 若设置，会覆盖本次默认成功/失败间隔。
- 执行器每次计算后的 `next_run` 会回写 `config.tasks.<name>.next_run`。

### 2.4 失败语义

- `TaskResult.success=false` 时计入失败并使用 `failure_interval_seconds`（除非 next_run_seconds 覆盖）。
- 不要新增会影响调度推进的“业务阻断标记”。

### 2.5 多实例边界（必须遵守）

- 启动/暂停/停止/立即执行逻辑保持在中间实例面板，禁止新增“全局实例总控启停”。
- 实例纳管仅包含：`新增 / 删除 / 切换 / 克隆 / 重命名`。
- 删除、重命名运行中实例必须拒绝并提示先停止该实例。

## 3. 常用方法速查

## 3.1 Runtime/Bot 常用

- `_is_cancel_requested(session_id=None) -> bool`
: 判断当前会话或执行器是否停止。

- `_sleep_interruptible(seconds, session_id=None) -> bool`
: 可中断睡眠，返回 `False` 表示被取消。

- `_prepare_window() -> rect | None`（vision）
: 刷新窗口、激活、更新 `action_executor/device` 窗口矩形。

- `_clear_screen(rect, session_id=None)`
: 连续点击 `GOTO_MAIN` 兜底回主。

- `resolve_live_click_point(x, y) -> (x, y)`
: 逻辑坐标映射到当前截图坐标系（考虑 nonclient 裁剪偏移）。

- `device.click_minitouch(x, y, desc=...) -> bool`
: 统一通过 `ActionExecutor` 执行点击动作。

- `_capture_frame(rect, save=False) -> (cv_img, pil_img)`
: 截图并推送 GUI 预览。

- `_capture_and_detect(...)`
: 当前只负责截图返回，模板检测由业务侧按需调用 detector。

## 3.2 UI/模板点击常用

- `ui.ui_get_current_page(...)`
: 页面识别（未知页会尝试回主+清弹窗）。

- `ui.ui_goto(page)` / `ui.ui_ensure(page)`
: 页面导航与确保到达。

- `ui.ui_additional()`
: 统一弹窗处理入口（等级、奖励、公告等）。

- `appear(button, offset=(30,30), threshold=0.8, static=False)`
: 仅判断出现。

- `appear_then_click(..., interval=1, ...)`
: 出现后点击；**interval 最低保持 1**。

- `appear_then_click_any([...], interval=1, ...)`
: 依次尝试多个按钮。

- UI 页面跳转开发注意
: 在跳转链路里，点击只代表“发起动作”，不代表“页面已切换”；点击后应继续循环并复检页面状态，确认到达目标页后再结束当前分支。

## 3.3 TaskExecutor 常用

- `task_call(task_name, force_call=True)`
: 立即将任务置为可执行。

- `task_delay(task_name, seconds=..., target_time=...)`
: 推迟任务下一次执行。

- `update_task(name, **kwargs)`
: 热更新任务参数（enabled/priority/interval 等）。

## 4. 业务任务逻辑（当前实现）

- `main`
: 主流程任务，内部先巡查维护，再按页面分发子任务。

- `main` 在自动播种前会先尝试等级 OCR（可由 `config.planting.level_ocr_enabled` 关闭）。

- `main` 在主页面的子任务顺序（命中即短路）：
1. `plant`
2. `upgrade(expand)`
3. `sell`
4. `reward`
5. `friend`

- `harvest` 内部顺序（命中即返回）：
1. 收获
2. 除草
3. 除虫
4. 浇水

- `friend`
: 独立好友任务，复用 `TaskFriend`；支持 `features.blacklist: list[str]` 配置。

- `share`
: 独立分享任务，仅执行分享领奖流程（仅支持微信平台；无 `features` 分项开关）。

- `reward`
: 独立任务奖励领取任务，支持分项开关：`features.claim_growth_task`（默认 false）、`features.claim_daily_task`（默认 true）。

- `gift`
: 物品领取任务，支持分项开关：`features.auto_svip_gift`（默认 true）、`features.auto_mall_gift`（默认 true）、`features.auto_mail`（默认 true，依赖 `menu_goto_mail` 模板，缺失时自动跳过）。

## 5. 新增任务标准流程

1. 在 `core/engine/bot/executor.py` 增加 `_run_task_<name>(ctx)`。
2. 在 `configs/config.template.json` 与用户配置中增加 `tasks.<name>`。
3. 任务业务代码放入 `core/tasks/<name>.py`（或复用已有子任务）。
4. 在任务中通过 `engine.get_task_features('<name>')` 读取开关。
5. 必要时补充 `configs/ui_labels.json` 文案映射。

## 6. 配置字段约定（tasks）

每个任务项建议包含：

- `enabled: bool`
- `priority: int`（>=1）
- `trigger: "interval" | "daily"`
- `interval_seconds: int`（>=1，实际生效下限见 `executor.min_task_interval_seconds`）
- `enabled_time_range: "HH:MM:SS-HH:MM:SS"`（默认 `00:00:00-23:59:59`，仅 `trigger=interval` 生效）
- `daily_time: "HH:MM"`
- `next_run: "YYYY-MM-DD HH:MM[:SS]"`（默认 `2026-01-01 00:00`）
- `failure_interval_seconds: int`（>=1，实际生效下限见 `executor.min_task_interval_seconds`）
- `features: {str: bool | list[str]}`

## 7. 修改边界与禁令

- 不要恢复旧 `core/ops` 业务层。
- 不要新增重复包装（例如多余 click/appear 兼容层）。
- 不要把任务列表改回 `models/config.py` 固定字段模型。
- 不要将 `appear_then_click` 的最小 `interval` 改成小于 `1`。
- 不要用会中断调度链路的业务状态去“跳过下次执行时间计算”。

## 8. 提交前检查（最低）

```bash
python -m compileall -q core gui models main.py
rg -n "from core\.ops|core\.ops|model_fields\.keys\(\)" core gui models
```

## 9. 常见问题排查

- 启动提示 assets 为 0
: 先运行 `python tools/button_extract.py`。

- 页面识别卡 unknown
: 检查 `window_title_keyword`、`window_select_rule`、窗口平台（QQ/微信）、模板是否与平台匹配。

- 任务未执行
: 检查 `tasks.<name>.enabled`、`trigger/daily_time/interval_seconds/enabled_time_range`、`priority`。

- 修改文案后界面未更新
: UI 文案读取 `configs/ui_labels.json`（内置配置）；修改后需重启程序，运行中不会热重建已创建面板。

- 点击偏移明显
: 检查 `resolve_live_click_point` 是否被绕过；优先走 `device.click_minitouch` / `ActionExecutor`。


## 10. 文档同步要求

- 若改动调度规则、任务入口、配置结构，必须同步更新：
1. `README.md`
2. 本文件 `AGENTS.md`

## 11. NIKKE 任务执行范式（参考实现）

以下模式来自 `NIKKE/main.py`、`NIKKE/module/ui/ui.py`、`NIKKE/module/base/base.py` 及典型任务（如 `daily/champion_arena`），新任务优先按此风格实现。

### 11.1 任务入口骨架

- 任务入口先 `ui_ensure(page_xxx)`，不要假设当前页面正确。
- 任务主体拆为若干小步骤函数（如 `receive()/ensure_back()/cheer()`），`run()` 只负责编排。
- 任务内允许捕获“可恢复业务异常”（例如资源不足）并执行收尾，再正常结束本轮。
- 本项目中“下一次执行时间”由执行器统一控制；不要在任务子步骤里频繁写 `next_run_seconds`。

### 11.2 while 循环常见写法

- 统一循环骨架：`while 1` + 主动截图 + 分支判断 + `continue/break`。
- 分支顺序通常是：
1. 高优先级弹窗/确认
2. 主动作点击
3. 收敛判定（是否到达目标页/目标状态）
4. 兜底处理（返回上级页面或清弹窗）
- 分支命中后立即 `continue`，避免同一帧执行多次动作。

### 11.3 点击节流

- `appear_then_click(..., interval=1)` 优先。

### 11.4 页面跳转与结束判定注意点

- 点击不是状态完成，点击后必须复检页面/状态再决定 `break/return`。
- 跳转类流程要以“页面已到达”作为结束条件，不要以“按钮点到了”作为结束条件。
- 未识别页面先走统一 `ui_additional()` 清弹窗，再尝试 `goto_main` 兜底。
- 循环必须有明确退出条件（稳定到达、超时、状态不可达），避免死循环。

### 11.5 日志与可观测性

- 关键阶段打印阶段日志（开始、步骤切换、结束）。
- 点击日志必须包含按钮名与坐标；任务完成日志必须包含任务名、状态、动作摘要。
- 异常日志要带上下文（当前任务/页面/按钮），便于复现与回放。

