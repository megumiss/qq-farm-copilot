# QQ Farm Copilot

基于 OpenCV + PyQt6 的 QQ 农场自动化工具，支持 PC 端 QQ和微信平台多开和后台运行。

## 预览

<img src="images/preview.png" alt="QQ Farm Copilot 预览" width="600" />

## 使用提示

- 本软件完全免费，若付费购买请立即退款。
- 请认准项目主页获取版本与说明，谨防二次售卖、捆绑分发与虚假收费。
- 项目地址：`https://github.com/megumiss/qq-farm-copilot`
- 本项目基于 [qq-farm-auto](https://github.com/Z7ANN/qq-farm-auto) 重构而来

## 已实现功能

- [x] 一键收获 / 除草 / 除虫 / 浇水
- [x] 自动购买种子
- [x] 自动播种
- [x] 自动扩建土地
- [ ] 自动升级土地
- [x] 仓库批量出售
- [x] 任务奖励领取
- [x] 分享奖励领取
- [x] 商城免费商品领取
- [x] QQSVIP礼包领取
- [x] 邮件领取
- [x] 好友农场偷菜
- [x] 好友农场帮忙
- [x] 自动同步等级
- [x] 地块巡查
- [x] 任务调度时间自定义
- [x] 偷取统计
- [ ] 异常通知
- [x] 支持QQ/微信平台后台运行
- [x] 支持QQ/微信平台多开

## 当前实现概览

- 架构：`BotEngine` + `TaskExecutor` + UI 页面识别（`core/ui`）
- 调度：统一任务执行器，支持 `INTERVAL` / `DAILY`
- 实例配置：`%APPDATA%\QQFarmCopilot\instances\<instance_id>\configs\config.json` 中 `tasks` 为**动态字典**
- 任务优先级：`tasks.<task>.priority`（数字越小越先执行）
- UI：左侧实时截图、中间实例运行面板、最右侧竖向实例栏（新增/删除/切换/克隆/重命名）

当前内置任务（通过 `_run_task_*` 自动发现）：

- `main`：农场主流程（收获维护、播种、扩建、升级）
- `friend`：独立好友任务（支持 `features.blacklist` 列表配置与 `features.steal_stats` 开关；主界面仅显示黑名单条目数，详情弹窗可维护名单）
- `share`：独立分享任务（仅支持微信平台，通常配合每日触发）
- `reward`：独立任务奖励领取（默认每 6 小时执行一次）
- `gift`：物品领取任务（QQSVIP礼包、商城礼包、可选邮件领取；支持分项开关）
- `sell`：独立出售任务（仓库批量出售）
- `land_scan`：地块巡查任务（默认关闭；每 30 分钟；按左右滑动分段点击地块并 OCR 采集）

## 后台/多开说明

1. 启动程序后，右侧竖向实例栏可进行实例管理（新增/删除/切换/克隆/重命名）。
2. 每个实例有独立配置与运行目录：
   - `%APPDATA%\QQFarmCopilot\instances\<instance_id>\configs\config.json`
   - `%APPDATA%\QQFarmCopilot\instances\<instance_id>\logs\`
   - `%APPDATA%\QQFarmCopilot\instances\<instance_id>\screenshots\`
3. 切换实例后，中间面板显示并控制当前实例；开始/暂停/停止/立即执行仅作用于当前实例。
4. 多开场景建议先在每个实例的设置中手动选择窗口。
5. 微信选择后台模式运行时，有可能会把窗口拉到前台，暂不清楚原因

## 环境要求

- Windows 10/11
- PC 端手动打开 QQ 农场

## 下载安装运行

### 方式一：下载 Release（推荐）

下载链接：
- [https://github.com/megumiss/qq-farm-copilot/releases/latest](https://github.com/megumiss/qq-farm-copilot/releases/latest)

1. 打开上方链接，下载最新的：
   - `QQFarmCopilot-<tag>-windows-x64.exe`
2. 将 `exe` 放到任意目录后双击运行。
3. 首次运行会自动在用户目录生成实例元数据与默认实例配置：
   - `%APPDATA%\QQFarmCopilot\profiles.json`
   - `%APPDATA%\QQFarmCopilot\instances\default\configs\config.json`
4. 打开 QQ 农场窗口，点击程序内“开始”。

### 方式二：源码运行

1. 安装 Python（建议 `3.10`）。
2. 在项目根目录执行：

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

说明：`requirements.txt` 已默认配置清华源（`pypi.tuna.tsinghua.edu.cn`）。


### VSCode 调试使用独立实例目录

- 在 VSCode `launch.json` 的 `env` 设置 `QFARM_DEV=true`。
- 开启后实例元数据与实例目录会隔离到项目内：`.dev_appdata/QQFarmCopilot/`。
- 调试与发布版都使用实例配置路径：`<instances>/<instance_id>/configs/config.json`。
- 设置 `QFARM_DEV=false`（或不设置）后，实例目录恢复到 `%APPDATA%\QQFarmCopilot\instances\`。

### 首次运行建议检查

1. `window_title_keyword` 与实际窗口标题一致（默认 `QQ经典农场`）。
2. 多窗口场景可在设置里指定“选择窗口”（保存匹配顺序，不保存句柄）。
3. `planting.window_platform` 与当前平台一致（QQ / 微信）。
4. 游戏窗口已打开且未最小化。

热键：

- `F9`：暂停 / 恢复
- `F10`：停止

## 配置说明

实例主配置文件（按实例隔离）：

- `%APPDATA%\QQFarmCopilot\instances\<instance_id>\configs\config.json`

核心字段：

- `window_title_keyword`：窗口标题关键词（默认 `QQ经典农场`）
- `window_select_rule`：窗口选择规则（`auto` 或 `index:N`，`auto` 会按当前平台优先匹配）
- `safety`：运行方式、随机延迟、点击抖动、单轮点击上限、`debug_log_enabled`
- `screenshot`：截图相关配置；`capture_interval_seconds` 控制最小截图间隔（秒，默认 `0.3`，`0` 表示不限制）
- `planting`：种植策略、等级、平台、窗口位置、`warehouse_first`（仓库优先选种；按固定底色数字块识别最左种子）、`skip_event_crops`（是否额外跳过艾草 `SEED_BTN_MUGWORT`；爱心果 `SEED_BTN_HEART_FRUIT` 固定跳过）、等级 OCR 开关、`planting_stable_seconds`（播种稳定时间）、`planting_stable_timeout_seconds`（背景树锚点稳定等待超时）
- `executor`：空队列策略、默认间隔、最大失败次数、`min_task_interval_seconds`（任务最小执行间隔）
- `land`：农场详情配置；`land.plots` 为 24 格地块状态列表（元素：`{ "plot_id": "1-1", "level": "unbuilt|normal|red|black|gold", "maturity_countdown": "HH:MM:SS" }`）；`land.profile` 为个人信息（`level/gold/coupon/exp`，由等级同步 OCR 回写）
- `tasks`：动态任务字典
- `tasks.<task>.next_run`：任务下次执行时间（持久化到配置，默认 `2026-01-01 00:00`）
- `tasks.<task>.enabled_time_range`：任务启用时间段（`HH:MM:SS-HH:MM:SS`，默认 `00:00:00-23:59:59`，仅 `INTERVAL` 生效）

等级 OCR 相关（`planting`）：

- `level_ocr_enabled`：是否启用播种前等级 OCR（对应设置面板“等级”右侧“自动同步”开关）
- 等级 OCR 识别区域由统一代码常量维护（见 `tasks/main.py`，不区分平台）

`tasks` 示例：

```json
{
  "main": {
    "enabled": true,
    "priority": 10,
    "trigger": "interval",
    "interval_seconds": 60,
    "enabled_time_range": "00:00:00-23:59:59",
    "daily_time": "04:00",
    "next_run": "2026-01-01 00:00",
    "failure_interval_seconds": 30,
    "features": {
      "auto_harvest": true,
      "auto_plant": false,
      "auto_expand": false,
      "auto_upgrade": false,
      "auto_fertilize": false
    }
  },
  "friend": {
    "enabled": true,
    "priority": 20,
    "trigger": "interval",
    "daily_time": "04:00",
    "next_run": "2026-01-01 00:00",
    "interval_seconds": 1800,
    "enabled_time_range": "00:00:00-23:59:59",
    "failure_interval_seconds": 60,
    "features": {
      "auto_steal": false,
      "steal_stats": false,
      "auto_help": true,
      "auto_accept_request": true,
      "blacklist": [
        "测试好友-张三",
        "测试好友-李四"
      ]
    }
  },
  "share": {
    "enabled": true,
    "priority": 30,
    "trigger": "daily",
    "daily_time": "04:00",
    "next_run": "2026-01-01 00:00",
    "interval_seconds": 86400,
    "enabled_time_range": "00:00:00-23:59:59",
    "failure_interval_seconds": 300,
    "features": {}
  },
  "reward": {
    "enabled": true,
    "priority": 32,
    "trigger": "interval",
    "daily_time": "04:00",
    "next_run": "2026-01-01 00:00",
    "interval_seconds": 21600,
    "enabled_time_range": "00:00:00-23:59:59",
    "failure_interval_seconds": 300,
    "features": {
      "claim_growth_task": false,
      "claim_daily_task": true
    }
  },
  "gift": {
    "enabled": true,
    "priority": 35,
    "trigger": "daily",
    "daily_time": "04:00",
    "enabled_time_range": "00:00:00-23:59:59",
    "interval_seconds": 86400,
    "failure_interval_seconds": 300,
    "features": {
      "auto_svip_gift": true,
      "auto_mall_gift": true,
      "auto_mail": true
    }
  },
  "land_scan": {
    "enabled": false,
    "priority": 45,
    "trigger": "interval",
    "daily_time": "04:00",
    "next_run": "2026-01-01 00:00",
    "interval_seconds": 1800,
    "enabled_time_range": "00:00:00-23:59:59",
    "failure_interval_seconds": 300,
    "features": {}
  }
}
```

固定禁用项（运行时强制关闭）：

- `main.auto_fertilize`

`tasks.<task>.features` 字段说明：

- 布尔开关：`{ "feature_x": true }`
- 列表项（例如好友黑名单）：`{ "blacklist": ["好友A", "好友B"] }`

调度规则：

- 到期任务按 `priority` 从小到大执行
- 任务执行后按成功/失败间隔或 `TaskResult.next_run_seconds` 计算下一次执行
- `INTERVAL` 任务仅在 `enabled_time_range` 内执行；不在时间段内会跳过本轮并延迟到下个启用时段起点
- `interval_seconds` / `failure_interval_seconds` 生效下限为 `executor.min_task_interval_seconds`（默认 `5` 秒）
- 每次计算出的下次执行时间会回写到 `tasks.<task>.next_run`
- `DAILY` 与 `INTERVAL` 共用同一套执行器队列

## UI 面板

- 左侧：当前实例截图预览
- 中间：当前实例状态、日志、任务调度、任务设置、设置（保留原逻辑）
- 右侧实例栏（竖向）：新增、删除、切换、克隆、重命名
- 启停控制：仍在中间面板内，按当前实例执行

### UI 文案配置

- 任务/功能/状态面板文案读取 `configs/ui_labels.json`（内置配置）。
- 修改文案后需要重新运行程序，运行中不会热重建已创建面板。

> 说明：`priority` 目前在配置文件中维护，未在面板提供编辑控件。

## 新增任务（当前实现方式）

1. 在 `core/engine/bot/executor.py` 增加 `_run_task_<name>` 方法
2. 在实例配置 `instances/<instance_id>/configs/config.json` 的 `tasks` 增加 `<name>` 配置
3. （可选）在 `configs/ui_labels.json` 增加任务与功能文案

执行器会自动发现 `_run_task_*` 并参与调度。

## 目录结构（当前）

```text
core/
  engine/
    bot/        # Bot 入口、运行态、执行器桥接、视觉桥接
    task/       # 通用任务执行器、任务模型、统计调度器
  platform/     # 窗口/截图/点击执行适配
  ui/           # 页面图、assets 按钮、UI 导航
  vision/       # CV 检测器
tasks/          # 业务任务实现
configs/
  config.template.json
  config.json
tools/
  template_collector.py
  button_extract.py
  import_seeds.py
```

## 免责声明

本项目仅供学习研究 OpenCV 视觉识别技术使用。自动化操作可能违反游戏服务条款，由此产生的一切后果由使用者自行承担。

## 许可证

本项目采用 `GNU General Public License v3.0 (GPLv3)`，详见根目录 [LICENSE](LICENSE)。

