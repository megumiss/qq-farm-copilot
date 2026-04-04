"""Bot 初始化装配逻辑。"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import cv2
import numpy as np
from loguru import logger
from PIL import Image as PILImage

from core.base.button import Button
from core.engine.task.executor import TaskExecutor
from core.engine.task.registry import (
    TaskContext,
    TaskItem,
    TaskResult,
    TaskSnapshot,
    build_default_tasks,
)
from core.engine.task.scheduler import TaskScheduler
from core.ops import ExpandOps, FriendOps, PlantOps, PopupOps, TaskOps
from core.platform.action_executor import ActionExecutor
from core.platform.device import NKLiteDevice
from core.platform.screen_capture import ScreenCapture
from core.platform.window_manager import WindowManager
from core.tasks.task_farm_main import TaskFarmMain
from core.tasks.task_farm_reward import TaskFarmReward
from core.ui.assets import ASSET_NAME_TO_CONST
from core.ui.page import (
    GOTO_MAIN,
    page_main,
)
from core.ui.ui import UI as NKLiteUI
from core.vision.cv_detector import CVDetector, DetectResult
from models.config import AppConfig, PlantMode, TaskTriggerType
from models.farm_state import Action, ActionType
from models.game_data import get_best_crop_for_level
from utils.template_paths import DEFAULT_TEMPLATE_PLATFORM, normalize_template_platform


class BotInitMixin:
    """Bot 初始化装配逻辑。"""

    def __init__(self, config: AppConfig):
        """初始化对象并准备运行所需状态。"""
        super().__init__()
        self.config = config
        self._session_id = 0
        self._cancel_event = threading.Event()
        self._runtime_failure_count = 0

        # [1] 窗口控制层
        self.window_manager = WindowManager()
        self.screen_capture = ScreenCapture()

        # [2] 图像识别层
        # 非 seed 模板识别改走 assets，detector 仅保留 seed 识别并固定默认平台。
        self.cv_detector = CVDetector(templates_dir='templates', template_platform=DEFAULT_TEMPLATE_PLATFORM)
        platform = getattr(config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        Button.set_template_platform(normalize_template_platform(platform_value))

        # [3] nklite 业务操作（替代 legacy strategies）
        self.popup = PopupOps(self)
        self.plant = PlantOps(self)
        self.expand = ExpandOps(self)
        self.task = TaskOps(self, popup=self.popup)
        self.friend = FriendOps(self)

        # [4] 操作执行层
        self.action_executor: ActionExecutor | None = None
        self.nk_device: NKLiteDevice | None = None
        self.nk_ui: NKLiteUI | None = None
        self.nk_task_farm_main: TaskFarmMain | None = None

        # 调度
        self.scheduler = TaskScheduler()
        self._task_executor: TaskExecutor | None = None
        self._executor_tasks: dict[str, TaskItem] = {}
        self._accept_executor_events = False

        self.scheduler.state_changed.connect(self.state_changed.emit)
        self.scheduler.stats_updated.connect(self.stats_updated.emit)
