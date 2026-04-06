"""Bot 初始化装配逻辑。"""

from __future__ import annotations

from core.base.button import Button
from core.engine.task.executor import TaskExecutor
from core.engine.task.registry import (
    TaskItem,
)
from core.engine.task.scheduler import TaskScheduler
from core.platform.action_executor import ActionExecutor
from core.platform.device import Device
from core.platform.screen_capture import ScreenCapture
from core.platform.window_manager import WindowManager
from core.ui.ui import UI
from core.vision.cv_detector import CVDetector
from models.config import AppConfig, resolve_effective_run_mode
from utils.template_paths import DEFAULT_TEMPLATE_PLATFORM, normalize_template_platform


class BotInitMixin:
    """Bot 初始化装配逻辑。"""

    def __init__(self, config: AppConfig):
        """初始化对象并准备运行所需状态。"""
        super().__init__()
        self.config = config
        self._runtime_failure_count = 0

        # [1] 窗口控制层
        self.window_manager = WindowManager()
        effective_mode = resolve_effective_run_mode(config.safety.run_mode, config.planting.window_platform)
        self.screen_capture = ScreenCapture(run_mode=effective_mode)

        # [2] 图像识别层
        # 非 seed 模板识别改走 assets，detector 仅保留 seed 识别并固定默认平台。
        self.cv_detector = CVDetector(templates_dir='templates', template_platform=DEFAULT_TEMPLATE_PLATFORM)
        platform = getattr(config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        Button.set_template_platform(normalize_template_platform(platform_value))

        # [3] 操作执行层
        self.action_executor: ActionExecutor | None = None
        self.device: Device | None = None
        self.ui: UI | None = None

        # 调度
        self.scheduler = TaskScheduler()
        self._task_executor: TaskExecutor | None = None
        self._executor_tasks: dict[str, TaskItem] = {}
        self._accept_executor_events = False
        self._fatal_error_stop_requested = False
        self._task_error_delay_overrides: dict[str, int] = {}
        self._task_error_type_names: dict[str, str] = {}

        self.scheduler.state_changed.connect(self.state_changed.emit)
        self.scheduler.stats_updated.connect(self.stats_updated.emit)
