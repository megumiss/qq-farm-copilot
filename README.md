# QQ Farm Copilot

> ⚠️ 重构中：当前版本部分功能暂不可用

基于 OpenCV + PyQt6 的 QQ 农场自动化工具，支持PC端QQ（后台）和微信平台。

## 使用提示

- 本软件完全免费，若付费购买请立即退款。
- 请认准项目主页获取版本与说明，谨防二次售卖、捆绑分发与虚假收费。
- 项目地址：`https://github.com/megumiss/qq-farm-copilot`

## 当前实现概览

- 架构：`BotEngine` + `TaskExecutor` + UI 页面识别（`core/ui`）
- 调度：统一任务执行器，支持 `INTERVAL` / `DAILY`
- 实例配置：`%APPDATA%\QQFarmCopilot\instances\<instance_id>\configs\config.json` 中 `tasks` 为**动态字典**
- 任务优先级：`tasks.<task>.priority`（数字越小越先执行）
- UI：左侧实时截图、中间实例运行面板、最右侧竖向实例栏（新增/删除/切换/克隆/重命名）

当前内置任务（通过 `_run_task_*` 自动发现）：

- `main`：农场主流程（收获维护、播种、扩建、出售、任务奖励、好友求助入口）
- `friend`：独立好友任务
- `share`：独立分享/任务奖励任务（通常配合每日触发）

## 已实现功能

- [x] 一键收获 / 除草 / 除虫 / 浇水
- [ ] 自动购买种子
- [ ] 自动播种
- [ ] 自动扩建 / 升级土地
- [x] 仓库批量出售
- [ ] 任务奖励领取
- [ ] 分享奖励领取
- [ ] 商城免费礼包购买
- [ ] QQSvip礼包领取
- [x] 好友农场偷菜
- [x] 好友农场帮忙
- [x] 任务调度时间自定义
- [x] QQ平台后台运行

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

可选（国内源）：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 首次运行建议检查

1. `window_title_keyword` 与实际窗口标题一致（默认 `QQ经典农场`）。
2. `planting.window_platform` 与当前平台一致（QQ / 微信）。
3. 游戏窗口已打开且未最小化。

热键：

- `F9`：暂停 / 恢复
- `F10`：停止

## 配置说明

实例主配置文件（按实例隔离）：

- `%APPDATA%\QQFarmCopilot\instances\<instance_id>\configs\config.json`

核心字段：

- `window_title_keyword`：窗口标题关键词（默认 `QQ经典农场`）
- `safety`：运行方式、随机延迟、点击抖动、单轮点击上限、`debug_log_enabled`
- `planting`：种植策略、等级、平台、窗口位置
- `executor`：空队列策略、默认间隔、最大失败次数
- `tasks`：动态任务字典

`tasks` 示例：

```json
{
  "main": {
    "enabled": true,
    "priority": 10,
    "trigger": "interval",
    "interval_seconds": 60,
    "daily_time": "04:00",
    "failure_interval_seconds": 30,
    "features": {
      "auto_harvest": true,
      "auto_plant": false,
      "auto_upgrade": false,
      "auto_fertilize": false
    }
  },
  "share": {
    "enabled": true,
    "priority": 30,
    "trigger": "daily",
    "daily_time": "04:00",
    "interval_seconds": 86400,
    "failure_interval_seconds": 300,
    "features": {
      "auto_task": false
    }
  }
}
```

固定禁用项（运行时强制关闭）：

- `main.auto_plant`
- `main.auto_upgrade`
- `main.auto_fertilize`
- `share.auto_task`

调度规则：

- 到期任务按 `priority` 从小到大执行
- 任务执行后按成功/失败间隔或 `TaskResult.next_run_seconds` 计算下一次执行
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
2. 在 `configs/config.json` 的 `tasks` 增加 `<name>` 配置
3. （可选）在 `configs/ui_labels.json` 增加任务与功能文案

执行器会自动发现 `_run_task_*` 并参与调度。

## 目录结构（当前）

```text
core/
  engine/
    bot/        # Bot 入口、运行态、执行器桥接、视觉桥接
    task/       # 通用任务执行器、任务模型、统计调度器
  tasks/        # 业务任务实现
  platform/     # 窗口/截图/点击执行适配
  ui/           # 页面图、assets 按钮、UI 导航
  vision/       # CV 检测器
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
