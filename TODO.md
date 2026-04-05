# TODO - 复刻精简版 NIKKE 脚本架构（页面跳转 / UI导航 / 场景处理 / Button逻辑）

> 目标：停止“混合风格”迭代，按 `NIKKE/` 代码范式重建本项目运行时。  
> 范围：本文件只管运行时与页面体系；任务执行器继续按 `TODO_task_executor.md`。  
> 原则：接口命名、调用顺序、兜底处理尽量与 NIKKE 保持同构，只做“农场业务最小集”裁剪。

---

## 0. 强制约束（本次改造必须满足）

- [x] 统一页面真相源：页面判断以 `UI.ui_get_current_page()` 为准，不再由 `scene_detector + 策略` 双轨并行决定。
- [x] 统一跳转入口：所有“去某页面”必须走 `UI.ui_ensure()/ui_goto()`，禁止策略里直接拼跳转流程。
- [x] 统一按钮语义：按钮检测/点击全部走 `ModuleBase.appear()/appear_then_click()`，保留 interval 限速与模板 offset 机制。
- [x] 统一兜底弹窗：未知弹窗与通用确认仅在 `InfoHandler.ui_additional()` 处理，任务分支不再重复关闭同类弹窗。
- [ ] 保留日志：不关模板日志；改造后日志应体现“按页面/按步骤的最小集合检测”，而不是每 tick 扫一大组无关模板。
- [x] `seed` 模板识别方式保持不变：继续使用当前 `cv_detector.detect_seed_template(...)` 流程与参数策略（含现有 ROI、尺度回退、阈值语义），本轮架构改造不改 seed 识别算法。

---

## 1. NIKKE 参考基线（必须对齐）

### 1.1 页面与导航
- 参考文件：`NIKKE/module/ui/page.py`
  - `Page` 对象、`check_button`、`links`、`link(button, destination)`
  - 页面图反向建父链（destination 反推可达页）
- 参考文件：`NIKKE/module/ui/ui.py`
  - `ui_page_appear()`
  - `ui_get_current_page()`
  - `ui_goto()`
  - `ui_ensure()`
  - `ui_additional()`

### 1.2 按钮与识别点击
- 参考文件：`NIKKE/module/base/button.py`
  - `Button(area,color,button,file,name)`
  - `match()/appear_on()/match_with_scale()`
  - `_button_offset` 动态偏移
- 参考文件：`NIKKE/module/base/base.py`
  - `appear()`
  - `appear_then_click()`
  - interval timer 限速
  - `appear_any()/appear_then_click_any()`

### 1.3 场景异常与弹窗兜底
- 参考文件：`NIKKE/module/handler/info_handle.py`
  - `handle_level_up()/handle_reward()/handle_announcement()...`
  - `ui_additional()` 中统一串联处理顺序

---

## 2. 当前项目到目标架构映射（按文件落地）

### 2.1 目标目录（新建）
- [x] 新建 `core/base/`
- [x] 新建 `core/ui/`
- [x] 新建 `core/handler/`
- [x] 新建 `core/tasks/`

### 2.2 映射关系
- [x] `NIKKE/module/base/button.py` -> `core/base/button.py`
- [x] `NIKKE/module/base/timer.py` -> `core/base/timer.py`（可复用现有 timer 实现但接口保持一致）
- [x] `NIKKE/module/base/base.py` -> `core/base/module_base.py`
- [x] `NIKKE/module/ui/page.py` -> `core/ui/page.py`
- [x] `NIKKE/module/ui/ui.py` -> `core/ui/ui.py`
- [x] `NIKKE/module/handler/info_handle.py` -> `core/handler/info_handler.py`

### 2.4 强制命名清单（类名 + 方法名）
- [x] `core/base/button.py`
  - 类名：`Button`
  - 方法名：`ensure_template`、`match`、`match_with_scale`、`appear_on`、`match_several`
- [x] `core/base/module_base.py`
  - 类名：`ModuleBase`
  - 方法名：`appear`、`appear_any`、`appear_then_click`、`appear_then_click_any`、`interval_reset`
- [x] `core/ui/page.py`
  - 类名：`Page`
  - 方法名：`link`
- [x] `core/ui/ui.py`
  - 类名：`UI`
  - 方法名：`ui_page_appear`、`ui_get_current_page`、`ui_goto`、`ui_ensure`、`ui_additional`、`ui_goto_main`、`ui_wait_loading`
- [x] `core/handler/info_handler.py`
  - 类名：`InfoHandler`
  - 方法名：`handle_level_up`、`handle_reward`、`handle_announcement`、`handle_login_reward`、`handle_system_error`
- [x] `core/tasks/*.py`
  - 类名命名：`Task*`（示例：`TaskFarmMain`）
  - 方法名：`run`（统一任务入口）

### 2.3 现有文件处置
- [x] `core/page_checker.py` 降级为兼容层或移除（页面判断迁移至 `nklite.ui`）
- [x] `core/navigator.py` 降级为兼容层或移除（导航统一迁移至 `nklite.ui`）
- [x] `core/scene_detector.py` 已删除，全局页面真相统一由 `nklite.ui` 负责
- [x] `core/ui_guard.py` 功能并入 `nklite.handler.info_handler`，避免重复职责
- [x] `core/bot_engine.py` 改为薄编排：只负责任务调度与 `nklite` 调用

---

## 3. Button 逻辑复刻（核心）

### 3.1 Button 模型
- [x] `Button` 字段对齐：`raw_area/raw_color/raw_button/raw_file/raw_name`
- [x] 支持 `name/file/area/color/button/location` 属性语义
- [x] 支持 `_button_offset` 动态偏移，点击坐标取偏移后的 button 区域中心

### 3.2 检测行为
- [x] `match(image, offset, threshold, static)` 行为对齐 NIKKE
- [x] `appear_on(image, threshold)` 颜色判断对齐
- [x] `match_with_scale(...)` 保留多尺度入口（精简版可以先用于少数按钮）
- [x] 统一 debug 日志：每次按钮判定输出 name/similarity/threshold/hit

### 3.3 ModuleBase 入口
- [x] `appear()`：保留 interval timer 限速逻辑
- [x] `appear_then_click()`：检测成功后通过 device 点击按钮
- [x] `appear_any()/appear_then_click_any()`：用于弹窗并列按钮处理
- [x] interval reset 能力：与 NIKKE 同语义

---

## 4. 页面图与 UI 导航复刻

### 4.1 页面定义（精简农场版）
- [x] 在 `core/ui/page.py` 定义 `Page` 类（与 NIKKE 同结构）
- [ ] 页面最小集：
  - `page_unknown`
  - `page_main`
  - `page_plot_menu`
  - `page_seed_select`
  - `page_shop`
  - `page_buy_confirm`
  - `page_popup`
  - `page_friend`
- [x] 每个页面定义 `check_button`
- [x] 使用 `link(button, destination)` 显式建图，不再隐式推断跳转动作

### 4.2 UI 服务
- [x] `ui_page_appear(page)`：页面检查按钮识别
- [x] `ui_get_current_page()`：
  - 轮询截图 -> 遍历 `ui_pages`
  - 未识别页面时先 `ui_additional()` 再做返回主界面尝试
  - 超时后抛出 unknown page 异常（或返回 `page_unknown` + error）
- [x] `ui_goto(destination)`：
  - 使用 NIKKE 同款“从 destination 反推 parent 链”策略
  - 每步点击后等待确认
- [x] `ui_ensure(destination)`：
  - 先识别当前页，若不是目标页则 `ui_goto`

---

## 5. 场景处理与全局兜底复刻

### 5.1 InfoHandler 统一入口
- [x] 新建 `core/handler/info_handler.py`
- [x] 迁移并统一：
  - 升级弹窗
  - 领取奖励弹窗
  - 通用确认/关闭按钮
  - 系统错误/异常状态
- [x] 在 `ui_additional()` 固定顺序串行处理，命中即返回 True

### 5.2 业务场景边界
- [x] 全局页面判断只依赖 `ui_get_current_page()`
- [x] `scene_detector` 已下线，不再参与任何页面判断
- [x] 禁止跨层弹窗处理：页面内通用弹窗统一由 `ui_additional()` 收口

---

## 6. 业务任务改造（精简 NIKKE 任务风格）

### 6.1 任务统一模板（每个任务必须遵守）
- [x] `task.run()` 开始先 `ui_ensure(page_main 或任务入口页)`
- [x] 主循环内每轮：
  - `device.screenshot()`
  - `ui_additional()`
  - 任务自身按钮流程
- [ ] 每一步动作使用 `appear_then_click()`，不直接散落模板匹配调用

### 6.2 农场最小任务集
- [x] `task_farm_harvest`：收获与维护
- [x] `task_farm_plant`：播种、买种、确认
- [x] `task_farm_sell`：仓库与批量出售
- [x] `task_farm_friend`：好友求助与回家
- [x] `task_farm_reward`：任务奖励领取

### 6.3 旧策略迁移
- [x] `core/strategies/*.py` 已整体下线，相关能力迁至 `core/ops`
- [x] 页面基础设施职责已由 `nklite.ui + nklite.handler` 统一承担
- [x] 任务已直接调用 `nklite` API（含 `ops`），策略层已移除

---

## 7. 资产与按钮定义复刻

### 7.1 按钮资产定义文件
- [ ] 新建 `core/ui/assets.py`（农场版）
- [ ] 每个按钮包含：`area/color/button/file`
- [ ] 按钮命名风格对齐 NIKKE（`MAIN_CHECK`, `MAIN_GOTO_XXX`, `GOTO_BACK`）

### 7.2 配置与生成
- [ ] `configs/page_rules.json` 已下线（已删除），页面体系改由 `nklite.ui.page/assets_generated` 驱动
- [ ] 明确模板来源：`templates/` 与按钮定义文件一一对应（`tools/button_extract.py` 直接扫描模板并输出 `assets_generated.py`）
- [ ] 不再维护 `button_extract.json/area_by_template`：ROI 由模板图像直接提取（bbox 像素范围）
- [ ] 保留中文页面映射，日志页名与按钮名都输出中文别名
  （7.2 保持进行中，继续留在 TODO 跟踪）

---

## 8. 与执行器集成（保持 executor-only）

- [x] `BotEngine` 中 executor 路径保留，legacy 路径不回滚
- [x] `farm_main` runner 改为调用 `nklite` 任务入口
- [x] 停止/暂停语义保持当前执行器标准
- [x] UI 状态刷新由 executor snapshot + `ui_current_page` 双源驱动

---

## 9. 清理项（防止再次变乱）

- [x] 删除或封禁旧入口：
  - `check_farm()` 内直接拼页面识别 + 业务分发的大循环逻辑
- [ ] 删除重复状态机：
  - `RuntimeState` 与 `PageId/Scene` 的多套并存状态
- [x] 删除重复导航：
  - `navigator + page_checker + scene_detector` 三套并行页面跳转链

---

## 10. 验收标准（必须全部满足）

- [ ] 页面跳转：任意支持页面到 `main` 能在预算内返回，且路径可解释（日志显示 page->page）
- [ ] UI 导航：`ui_ensure(target)` 在弹窗干扰场景仍可稳定到达
- [ ] 场景处理：未知弹窗只在 `ui_additional()` 关闭，不再出现策略层重复关闭
- [ ] Button 逻辑：按钮点击命中率与 NIKKE 风格一致，日志可追溯 `appear -> click`
- [ ] 性能：每 tick 模板识别条目显著减少，日志不再持续出现无关按钮扫描
- [ ] 稳定性：停止后状态与执行动作在一个调度周期内完成刷新

---

## 11. 改造执行步骤（按序提交）

1. [x] 建立 `core/base`：`button.py + timer.py + module_base.py`，并接入现有 device/capture。
2. [x] 建立 `core/ui`：`assets.py + page.py + ui.py`，先完成 `ui_get_current_page/ui_goto/ui_ensure`。
3. [x] 建立 `core/handler/info_handler.py`，把全局弹窗处理统一收口到 `ui_additional()`。
4. [x] 在 `bot_engine` 接入 `nklite.ui`，把“页面识别/导航”入口改为 `ui_ensure`。
5. [x] 迁移农场最小任务集（收获/维护/播种/出售/好友/奖励）为 `nklite.tasks` 风格。
6. [x] 清理旧链路：移除 `page_checker/navigator/ui_guard` 的主路径职责，只留兼容或删除。
7. [ ] 连续回归：页面跳转、停止刷新、任务执行、日志规模四项验收全部通过。

---

## 12. 当前状态

- [ ] 本 TODO 为重置版，默认全部未完成。
- [ ] 后续每完成一项，直接在本文件勾选并附对应提交号（`commit <sha>`）。

