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
from utils.ocr_provider import get_ocr_tool
from utils.ocr_utils import OCRTool
from utils.template_paths import normalize_template_platform


class BotInitMixin:
    """Bot 初始化装配逻辑。"""

    config: AppConfig

    def __init__(
        self,
        config: AppConfig,
        *,
        runtime_paths: dict[str, str] | None = None,
        instance_id: str = 'default',
    ):
        """初始化对象并准备运行所需状态。"""
        super().__init__()
        self.config = config
        self._instance_id = str(instance_id or 'default')
        self._runtime_paths = dict(runtime_paths or {})
        self._error_dir = str(self._runtime_paths.get('error_dir') or 'logs/error')
        self._ocr_tool: OCRTool | None = None

        # [1] 窗口控制层
        self.window_manager = WindowManager()
        effective_mode = resolve_effective_run_mode(config.safety.run_mode, config.planting.window_platform)
        self.screen_capture = ScreenCapture(
            save_dir=str(self._runtime_paths.get('screenshots_dir') or 'screenshots'),
            run_mode=effective_mode,
        )

        # [2] 图像识别层
        # 非 seed 模板识别改走 assets，detector 主要保留 seed 识别能力。
        platform_value = config.planting.window_platform.value
        normalized_platform = normalize_template_platform(platform_value)
        self.cv_detector = CVDetector(templates_dir='templates', template_platform=normalized_platform)
        Button.set_template_platform(normalized_platform)

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
        self._task_exception_retry_counts: dict[str, int] = {}
        self._restart_task_payload: dict[str, str | int] | None = None
        self._recovery_total_count: int = 0
        self._recovery_last_error: str = '--'
        self._recovery_last_action: str = '--'
        self._recovery_last_outcome: str = '--'
        self._recovery_last_task: str = '--'

        self.scheduler.state_changed.connect(self.state_changed.emit)
        self.scheduler.stats_updated.connect(self.stats_updated.emit)

    def _get_ocr_tool(self) -> OCRTool:
        """懒加载 OCRTool，避免在引擎启动阶段触发模型下载。"""
        if self._ocr_tool is None:
            self._ocr_tool = get_ocr_tool(scope='engine', key=self._instance_id)
        return self._ocr_tool
