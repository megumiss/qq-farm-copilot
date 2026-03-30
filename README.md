# QQ Farm Vision Bot

基于 OpenCV 视觉识别的 QQ 经典农场（微信小程序）自动化工具。纯本地运行，不依赖游戏接口，零封号风险。

## 工作原理

```
截屏(mss) → OpenCV多尺度模板匹配 → 场景识别 → 策略决策 → pyautogui模拟点击 → 循环
```

通过截取游戏窗口画面，用 OpenCV 模板匹配识别按钮、图标、作物状态，再按优先级自动执行操作。不读取内存、不修改数据包、不调用游戏API。

## 功能进度

### 已完成

- [x] 自动收获（一键收获）
- [x] 自动播种（拖拽播种所有空地）
- [x] 智能种植策略（自动选当前等级经验效率最高的作物）
- [x] 种子用完自动去商店购买（shop_ 模板匹配）
- [x] 自动除草 / 除虫 / 浇水（一键维护）
- [x] 自动扩建土地
- [x] 自动领取任务奖励（分享领双倍）
- [x] 自动出售仓库果实（批量出售 / 选择性出售）
- [x] 好友求助 / 帮浇水 / 除草 / 除虫
- [x] 自动关闭弹窗（任务奖励、确认框等）
- [x] 升级弹窗自动检测，等级自动 +1
- [x] 场景识别状态机（农场主页 / 商店 / 好友家 / 弹窗 / 升级等）
- [x] 播种后智能调度（按设置间隔定期检查维护）
- [x] 设置实时生效（无需手动保存）
- [x] 现代浅色 GUI（左侧截图预览 + 右侧 Tab 状态/设置/出售 + 日志）
- [x] 全局热键（F9 暂停/恢复，F10 停止）
- [x] 模板采集工具
- [x] 种子图片批量导入工具

### 待完成

- [ ] 自动偷菜（进入好友农场检测成熟作物）
- [ ] 好友农场批量巡查
- [ ] 自动同意好友申请

## 环境要求

- Windows 10/11
- Python 3.10+
- PC端微信，打开 QQ 经典农场小程序

## 安装

```bash
git clone https://github.com/Z7ANN/qq-farm-vision-bot.git
cd qq-farm-vision-bot
pip install -r requirements.txt
```

## 快速开始

### 1. 采集模板（首次使用必须）

打开微信小程序中的 QQ 经典农场，然后运行：

```bash
python tools/template_collector.py
```

操作方式：鼠标左键拖拽框选 → 按 `S` 保存 → 按 `R` 重新截屏 → 按 `Q` 退出

需要采集的模板：

| 文件名 | 说明 | 来源页面 |
|--------|------|---------|
| `land_empty.png` | 空地 | 农场主页 |
| `btn_harvest.png` | 一键收获按钮 | 农场主页 |
| `btn_weed.png` | 一键除草按钮 | 农场主页 |
| `btn_bug.png` | 一键除虫按钮 | 农场主页 |
| `btn_water.png` | 一键浇水按钮 | 农场主页 |
| `btn_close.png` | 关闭按钮(X) | 各种弹窗 |
| `btn_claim.png` | "直接领取"按钮 | 任务奖励弹窗 |
| `btn_share.png` | "分享"按钮 | 任务奖励弹窗 |
| `btn_task.png` | 左下角任务提示条 | 农场主页 |
| `btn_shop.png` | 底部"商店"按钮 | 农场主页 |
| `btn_shop_close.png` | 商店关闭按钮(X) | 商店页面 |
| `btn_buy_max.png` | 购买数量加号按钮 | 商店购买弹窗 |
| `btn_buy_confirm.png` | 购买"确定"按钮 | 商店购买弹窗 |
| `btn_batch_sell.png` | "批量出售"按钮 | 仓库页面 |
| `btn_home.png` | 回家按钮 | 好友家园 |
| `btn_friend_help.png` | 好友求助按钮 | 农场主页 |
| `btn_expand.png` | 扩建按钮 | 农场主页 |
| `btn_expand_confirm.png` | 扩建确认按钮 | 扩建弹窗 |
| `icon_levelup.png` | 升级弹窗特征图标 | 升级弹窗 |
| `shop_小麦.png` | 商店种子卡片 | 商店页面（每种作物单独采集） |

种子模板可通过导入工具批量生成：

```bash
python tools/import_seeds.py
```

### 2. 启动

```bash
python main.py
```

### 3. 配置

GUI 右侧三个标签页：

- 状态：运行状态、操作统计、下次检查时间
- 设置：玩家等级、种植策略（自动最优/手动指定）、功能开关、检查间隔
- 出售：出售模式（批量全部/选择性），选择性模式可勾选要出售的作物

所有设置修改后实时生效，无需手动保存。

### 4. 运行

点击「开始」按钮，程序会：

1. 自动找到 QQ 经典农场窗口并调整大小（预留任务栏）
2. 清屏：点击天空区域关闭残留弹窗
3. 循环执行：截屏 → 场景识别 → 按优先级执行操作
4. 播种后按设置间隔定期检查维护（除虫/除草/浇水/任务等）
5. 检测到升级弹窗自动更新等级，重新计算最优作物

热键：
- `F9` — 暂停 / 恢复
- `F10` — 强制停止

## 项目结构

```
qq-farm-vision-bot/
├── main.py                     # 程序入口
├── config.json                 # 运行时配置（自动生成）
├── templates/                  # 模板图片（用户采集 + 种子导入）
│
├── core/                       # 核心引擎
│   ├── bot_engine.py           # 主控编排（BotEngine + BotWorker）
│   ├── window_manager.py       # 窗口定位与管理（预留任务栏）
│   ├── screen_capture.py       # 屏幕截图（mss）
│   ├── cv_detector.py          # OpenCV 模板匹配引擎
│   ├── scene_detector.py       # 场景识别（枚举状态机）
│   ├── action_executor.py      # 鼠标操作执行器（pyautogui）
│   ├── task_scheduler.py       # 定时调度器（QTimer）
│   └── strategies/             # 策略模块（按优先级）
│       ├── base.py             # 策略基类
│       ├── popup.py            # P-1  弹窗处理 + 任务奖励分享
│       ├── harvest.py          # P0   一键收获
│       ├── maintain.py         # P1   除草/除虫/浇水
│       ├── plant.py            # P2   播种 + 购买种子
│       ├── expand.py           # P3   扩建土地
│       ├── task.py             # P3.5 任务领取 + 出售果实
│       └── friend.py           # P4   好友帮忙
│
├── gui/                        # PyQt6 界面
│   ├── main_window.py          # 主窗口（现代浅色主题）
│   ├── icons/                  # SVG 图标
│   └── widgets/
│       ├── log_panel.py        # 日志面板
│       ├── status_panel.py     # 状态统计面板
│       ├── settings_panel.py   # 设置面板
│       └── sell_panel.py       # 出售设置面板
│
├── models/                     # 数据模型
│   ├── config.py               # 配置模型（Pydantic + Enum）
│   ├── farm_state.py           # 操作类型枚举 + Action 模型
│   └── game_data.py            # 作物静态数据表（33种）
│
├── utils/                      # 工具
│   ├── logger.py               # 日志系统（loguru → 文件 + GUI）
│   └── image_utils.py          # 图像处理工具
│
└── tools/                      # 辅助工具
    ├── template_collector.py   # 交互式模板采集
    └── import_seeds.py         # 种子图片批量导入
```

## 架构设计

四层架构，职责分离：

```
┌─────────────────────────────────────────────┐
│  GUI 层 (PyQt6)                              │
│  主窗口 / 状态 / 设置 / 出售 / 日志             │
├─────────────────────────────────────────────┤
│  行为决策层 (strategies/)                      │
│  popup → harvest → maintain → plant →        │
│  expand → task → friend                      │
├─────────────────────────────────────────────┤
│  图像识别层                                    │
│  cv_detector (模板匹配) + scene_detector (场景) │
├─────────────────────────────────────────────┤
│  窗口控制层                                    │
│  window_manager + screen_capture              │
├─────────────────────────────────────────────┤
│  操作执行层                                    │
│  action_executor (pyautogui 模拟点击)          │
└─────────────────────────────────────────────┘
```

策略模块按优先级执行：

| 优先级 | 策略 | 职责 |
|--------|------|------|
| P-1 | PopupStrategy | 关闭弹窗 + 升级检测 + 任务奖励分享 |
| P0 | HarvestStrategy | 一键收获 |
| P1 | MaintainStrategy | 除草 / 除虫 / 浇水 |
| P2 | PlantStrategy | 播种 + 自动购买种子 |
| P3 | ExpandStrategy | 扩建土地 |
| P3.5 | TaskStrategy | 任务领取 + 出售果实 |
| P4 | FriendStrategy | 好友帮忙 |

## 模板命名规范

| 前缀 | 类别 | 示例 |
|------|------|------|
| `btn_` | 按钮 | `btn_harvest.png` |
| `icon_` | 状态图标 | `icon_mature.png`, `icon_levelup.png` |
| `crop_` | 作物状态 | `crop_dead.png` |
| `land_` | 土地状态 | `land_empty.png` |
| `seed_` | 种子图标（播种列表） | `seed_小麦.png` |
| `shop_` | 商店种子卡片 | `shop_小麦.png` |

## 常见问题

**Q: 找不到游戏窗口？**
确保 PC 端微信已打开 QQ 经典农场小程序，窗口标题包含"QQ经典农场"。可在设置中修改窗口关键词。

**Q: 模板匹配不准确？**
模板需要在你自己的设备上采集。不同分辨率、DPI 缩放会导致模板不匹配。程序内置了多尺度匹配（0.8x~1.2x），但差异过大时仍需重新采集。

**Q: 播种时找不到种子？**
确认 `templates/` 目录下有对应的 `seed_作物名.png` 文件，且名称与设置中选择的作物一致。

**Q: 商店购买了错误的种子？**
商店使用独立的 `shop_` 模板（阈值 0.9），需要在商店页面单独采集每种作物的卡片模板。

**Q: 如何添加新功能？**
在 `core/strategies/` 下新建策略模块，继承 `BaseStrategy`，在 `bot_engine.py` 中注册并按优先级编排。

## License

MIT

## 免责声明

本项目仅供学习研究 OpenCV 视觉识别技术使用。自动化操作可能违反游戏服务条款，由此产生的一切后果由使用者自行承担。
