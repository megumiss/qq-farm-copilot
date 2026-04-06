# QQ Farm Copilot

> ⚠️ 重构中：当前版本部分功能暂不可用

基于 OpenCV + PyQt6 的 QQ 农场自动化工具，支持PC端QQ（后台）和微信平台。

## 当前实现概览

- 架构：`BotEngine` + `TaskExecutor` + UI 页面识别（`core/ui`）
- 调度：统一任务执行器，支持 `INTERVAL` / `DAILY`
- 任务配置：`configs/config.json` 中 `tasks` 为**动态字典**
- 任务优先级：`tasks.<task>.priority`（数字越小越先执行）
- UI：左侧实时截图，右侧状态/任务调度/任务功能/设置

当前内置任务（通过 `_run_task_*` 自动发现）：

- `main`：农场主流程（收获维护、播种、扩建、出售、任务奖励、好友求助入口）
- `friend`：独立好友任务
- `share`：独立分享/任务奖励任务（通常配合每日触发）
- `gift`：免费礼包任务（QQSVIP礼包 + 商城礼包，每日）

## 已实现功能

- [x] 一键收获 / 除草 / 除虫 / 浇水
- [ ] 自动购买种子
- [ ] 自动播种
- [ ] 自动扩建 / 升级土地
- [x] 仓库批量出售
- [ ] 任务奖励领取
- [ ] 分享奖励领取
- [x] 商城免费礼包领取
- [x] QQSVIP礼包领取
- [x] 好友农场偷菜
- [x] 好友农场帮忙
- [x] 任务调度时间自定义
- [x] QQ平台后台运行

## 环境要求

- Windows 10/11
- PC 端手动打开 QQ 农场


## 下载安装运行

### 方式一：下载 Release（推荐）

1. 打开仓库 `Releases` 页面，下载最新的：
   - `QQFarmCopilot-<tag>-windows-x64.exe`
2. 将 `exe` 放到任意目录后双击运行。
3. 首次运行会自动在用户目录生成配置文件：
   - `%APPDATA%\QQFarmCopilot\configs\config.json`
   - `%APPDATA%\QQFarmCopilot\configs\ui_labels.json`
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

主配置文件：`configs/config.json`

核心字段：

- `window_title_keyword`：窗口标题关键词（默认 `QQ经典农场`）
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
      "auto_plant": true
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
      "auto_task": true
    }
  }
}
```

调度规则：

- 到期任务按 `priority` 从小到大执行
- 任务执行后按成功/失败间隔或 `TaskResult.next_run_seconds` 计算下一次执行
- `DAILY` 与 `INTERVAL` 共用同一套执行器队列

## UI 面板

- 状态：运行状态、当前任务、队列数量、统计
- 任务调度：任务开关、间隔/每日时间、执行器策略
- 任务设置：`tasks.<task>.features` 开关
- 设置：窗口关键词、平台、位置、种植策略

> 说明：`priority` 目前在配置文件中维护，未在面板提供编辑控件。

## 新增任务（当前实现方式）

1. 在 `core/engine/bot/executor.py` 增加 `_run_task_<name>` 方法
2. 在 `configs/config.json` 的 `tasks` 增加 `<name>` 配置
3. （可选）在 `gui/configs/ui_labels.json` 增加任务与功能文案

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
  ui_labels.json
tools/
  template_collector.py
  button_extract.py
  import_seeds.py
```

## 免责声明

本项目仅供学习研究 OpenCV 视觉识别技术使用。自动化操作可能违反游戏服务条款，由此产生的一切后果由使用者自行承担。
