# QQ Farm Copilot 单窗口多实例方案（不兼容旧版）

## 1. 范围与原则

1. 只打开一次 `QQFarmCopilot.exe`，在同一个主窗口内管理多个实例。
2. 启动、暂停、停止、立即执行逻辑保持现状，不做全局实例级启停改造。
3. 外层实例纳管只包含五个操作：新增、删除、切换、克隆、重命名。
4. 左侧截图预览只显示当前选中实例。
5. 每个实例配置与数据完全隔离。

## 2. 界面布局（按你的最新要求）

1. 主窗口采用三栏布局：
   1. 左栏：截图预览（保持现有）。
   2. 中栏：当前实例的原有信息窗口（状态、日志、任务调度、任务设置、设置，保持现有结构）。
   3. 右栏：实例栏（竖向，固定在最右侧）。
2. 右侧实例栏结构：
   1. 上部：实例列表（竖向 Tab/List，单击切换实例）。
   2. 下部：操作按钮（新增、删除、克隆、重命名）。
3. 右侧实例栏建议固定宽度 `220-260px`，列表超出时滚动。
4. 中栏原有“开始/暂停/停止/立即执行”按钮原位保留，不移动到实例栏。

## 3. 实例模型

1. `InstanceSession`（内存对象）：
   1. `instance_id`
   2. `name`
   3. `config_path`
   4. `engine`（独立 `BotEngine`）
   5. `panels`（独立右侧面板控件集合）
   6. `last_preview`（最后一帧截图缓存）
2. `InstanceManager`（主进程单例）：
   1. 实例增删改查
   2. 当前实例切换
   3. 元数据保存到 `profiles.json`
   4. UI 与运行态对象映射管理

## 4. 配置与目录（全新结构）

1. 全局元数据：
   1. `%APPDATA%/QQFarmCopilot/profiles.json`
   2. 保存实例列表、顺序、当前激活实例、显示名
2. 实例隔离目录：
   1. `%APPDATA%/QQFarmCopilot/instances/<instance_id>/configs/config.json`
   2. `%APPDATA%/QQFarmCopilot/instances/<instance_id>/logs/`
   3. `%APPDATA%/QQFarmCopilot/instances/<instance_id>/screenshots/`
   4. `%APPDATA%/QQFarmCopilot/instances/<instance_id>/logs/error/`
3. 禁止共享写目录，所有写路径都必须通过实例上下文解析。

## 5. 进程与运行架构

1. 主程序进程只有一个（单窗口）。
2. 每个实例使用一套独立运行链路：
   1. `BotEngine`
   2. 对应 worker 子进程
3. 多实例可并行运行，彼此调度与状态不共享。
4. 可选增加“应用单实例锁”（全局 mutex），防止用户再开第二个主窗口。

## 6. 五个实例操作定义

1. 新增：
   1. 创建实例目录与默认 `config.json`
   2. 注册到 `profiles.json`
   3. 在右侧列表新增条目并切换到该实例
2. 删除：
   1. 仅允许删除未运行实例
   2. 删除实例目录与元数据
3. 切换：
   1. 切换中栏到目标实例的面板
   2. 左侧预览切换到目标实例图像流
4. 克隆：
   1. 复制源实例配置到新实例
   2. 不复制运行态（不自动启动）
5. 重命名：
   1. 仅允许未运行实例
   2. 更新显示名与目录名（或仅目录映射名）
   3. 同步更新 `profiles.json`

## 7. 左侧预览与中栏配置联动

1. 左侧预览始终绑定当前实例。
2. 切换实例时先显示该实例 `last_preview`，再接管实时帧。
3. 中栏展示与编辑的配置始终是当前实例配置。
4. 当前实例配置变更只写回当前实例 `config.json`。

## 8. 启停逻辑保持不变（关键约束）

1. 不新增实例级总控启停。
2. 每个实例仍通过中栏原有按钮执行开始、暂停、停止、立即执行。
3. 切换实例不触发自动启动或自动停止。
4. 删除、重命名运行中实例直接拒绝并提示用户先停止该实例。

## 9. 逐文件改造清单（含完成标记）

状态说明：`[ ]` 未完成，`[x]` 已完成。

- [ ] [main.py](E:/AutoGame/qq-farm-auto/main.py)：改 `main()` 为“加载 `profiles.json` + 初始化 `InstanceManager` + 创建 `MainWindow(instance_manager)`”；保留 `_set_windows_app_id()`、`_resolve_app_icon_path()`。
- [x] [utils/app_paths.py](E:/AutoGame/qq-farm-auto/utils/app_paths.py)：新增实例路径函数 `user_instances_dir()`、`instance_dir()`、`instance_configs_dir()`、`instance_config_file()`、`instance_logs_dir()`、`instance_screenshots_dir()`、`instance_error_dir()`、`profiles_meta_file()`。
- [x] [utils/instance_paths.py](E:/AutoGame/qq-farm-auto/utils/instance_paths.py)（新增）：新增 `InstancePaths`、`load_profiles_meta()`、`save_profiles_meta()`、`ensure_instance_layout()`、`create_instance()`、`clone_instance()`、`rename_instance()`、`delete_instance()`、`list_instances()`、`sanitize_instance_name()`。
- [x] [models/config.py](E:/AutoGame/qq-farm-auto/models/config.py)：改 `AppConfig.load()` 与 `AppConfig.save()` 为实例绝对路径；新增 `_atomic_write_json()` 并使用 `tmp + os.replace`。
- [x] [core/instance/manager.py](E:/AutoGame/qq-farm-auto/core/instance/manager.py)（新增）：新增 `InstanceSession`、`InstanceManager`，实现 `load()`、`save()`、`create_instance()`、`clone_instance()`、`rename_instance()`、`delete_instance()`、`switch_active()`、`get_active()`、`iter_sessions()`。
- [x] [core/engine/bot/engine.py](E:/AutoGame/qq-farm-auto/core/engine/bot/engine.py)：`BotEngine.__init__()` 增加 `runtime_paths`、`instance_id`；`_ensure_worker()` 传递实例上下文；`_handle_event()` 的 `log` 分支增加 `self.log_message.emit(text)`。
- [x] [core/engine/bot/worker.py](E:/AutoGame/qq-farm-auto/core/engine/bot/worker.py)：`bot_worker_main()` 增加 `runtime_paths`、`instance_id` 参数；`_configure_worker_logger()` 增加实例日志 sink；构造引擎改为 `LocalBotEngine(config, runtime_paths=..., instance_id=...)`。
- [x] [core/engine/bot/local_engine.py](E:/AutoGame/qq-farm-auto/core/engine/bot/local_engine.py)：新增 `__init__(self, config, runtime_paths=None, instance_id='')`，并向 mixin 透传。
- [x] [core/engine/bot/bootstrap.py](E:/AutoGame/qq-farm-auto/core/engine/bot/bootstrap.py)：`BotInitMixin.__init__()` 增加实例上下文；`ScreenCapture` 使用实例 `screenshots_dir`；记录 `self._error_dir`。
- [x] [core/engine/bot/executor.py](E:/AutoGame/qq-farm-auto/core/engine/bot/executor.py)：`_on_executor_task_error()` 内 `save_error_screenshots(..., base_dir=self._error_dir)`，移除硬编码 `'logs/error'`。
- [x] [core/platform/screen_capture.py](E:/AutoGame/qq-farm-auto/core/platform/screen_capture.py)：`_make_screenshot_path()` 文件名增加毫秒时间戳与 PID，避免多实例重名覆盖。
- [ ] [gui/widgets/instance_sidebar.py](E:/AutoGame/qq-farm-auto/gui/widgets/instance_sidebar.py)（新增）：新增最右侧竖向实例栏 `InstanceSidebar`，提供 `instance_selected`、`create_requested`、`delete_requested`、`clone_requested`、`rename_requested` 信号。
- [ ] [gui/main_window.py](E:/AutoGame/qq-farm-auto/gui/main_window.py)：改为三栏布局（左预览/中原面板/右实例栏）；新增 `_create_instance_workspace()`、`_switch_instance()`、`_on_instance_create()`、`_on_instance_delete()`、`_on_instance_clone()`、`_on_instance_rename()`、`_get_active_session()`。
- [ ] [gui/main_window.py](E:/AutoGame/qq-farm-auto/gui/main_window.py)：将 `_on_start()`、`_on_pause()`、`_on_stop()`、`_on_run_once()`、`_on_config_changed()` 改为只作用当前实例会话。
- [ ] [gui/main_window.py](E:/AutoGame/qq-farm-auto/gui/main_window.py)：`_update_screenshot()` 改为实例路由；当前实例实时显示，非当前实例只更新 `last_preview` 缓存。
- [ ] [gui/main_window.py](E:/AutoGame/qq-farm-auto/gui/main_window.py)：`_connect_signals()` 改为“每实例绑定”；停用/移除 `get_log_signal().new_log.connect(...)` 的全局日志直连，避免多实例串日志。
- [ ] [gui/widgets/task_panel.py](E:/AutoGame/qq-farm-auto/gui/widgets/task_panel.py)：如采用控件复用，新增 `set_config(config)` 并支持切换时重载；如每实例独立面板可不改。
- [ ] [gui/widgets/feature_panel.py](E:/AutoGame/qq-farm-auto/gui/widgets/feature_panel.py)：如采用控件复用，新增 `set_config(config)` 并支持切换时重载；如每实例独立面板可不改。
- [ ] [gui/widgets/settings_panel.py](E:/AutoGame/qq-farm-auto/gui/widgets/settings_panel.py)：如采用控件复用，新增 `set_config(config)` 并支持切换时重载；如每实例独立面板可不改。
- [ ] [README.md](E:/AutoGame/qq-farm-auto/README.md)：更新单窗口多实例说明、最右侧竖向实例栏、实例目录与配置路径。
- [ ] [AGENTS.md](E:/AutoGame/qq-farm-auto/AGENTS.md)：同步当前架构、实例纳管边界（仅新增/删除/切换/克隆/重命名）与路径规范。
- [ ] [MULTI_INSTANCE_PLAN.md](E:/AutoGame/qq-farm-auto/MULTI_INSTANCE_PLAN.md)：随实现进度维护本清单的完成状态。

## 10. 验收标准

1. 只开一个主窗口即可创建并管理多个实例。
2. 右侧实例栏位于最右侧，竖向展示并可切换实例。
3. 每个实例启动、停止仍通过中栏原按钮，行为与当前版本一致。
4. 切换实例时左侧预览与中栏配置同步切换。
5. 实例配置、日志、截图、错误快照目录完全隔离。
