"""Bot 任务入口封装。"""

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


class BotTaskEntryMixin:
    """Bot 任务入口封装。"""

    def check_farm(self, session_id: int | None = None) -> TaskResult:
        """农场任务入口：转发到 `TaskFarmMain`。"""
        if self.nk_task_farm_main is not None:
            return self.nk_task_farm_main.run(session_id=session_id)
        return TaskResult(success=False, actions=[], next_run_seconds=5, error='nklite 农场任务未初始化')

    def check_share(self, session_id: int | None = None) -> TaskResult:
        """分享任务入口：执行奖励领取并返回下一次调度时间。"""
        share_cfg = self.config.tasks.share
        next_seconds = max(1, int(share_cfg.interval_seconds))
        if share_cfg.trigger == TaskTriggerType.DAILY:
            next_seconds = self._seconds_to_next_daily(share_cfg.daily_time)

        if self._is_cancel_requested(session_id):
            return TaskResult(success=False, actions=[], next_run_seconds=next_seconds, error='停止中')
        if not self.nk_ui:
            return TaskResult(success=False, actions=[], next_run_seconds=next_seconds, error='UI未初始化')

        rect = self._prepare_window()
        if not rect:
            return TaskResult(success=False, actions=[], next_run_seconds=next_seconds, error='窗口未找到')
        if self.nk_device:
            self.nk_device.set_rect(rect)

        self._clear_screen(rect, session_id)
        self.nk_ui.ui_ensure(page_main, confirm_wait=0.5)

        reward = TaskFarmReward(engine=self, ui=self.nk_ui)
        out = reward.run(rect=rect, features=self.get_task_features('share'))
        return TaskResult(success=True, actions=list(out.actions), next_run_seconds=next_seconds, error='')

    def check_friends(self, session_id: int | None = None) -> TaskResult:
        """好友任务入口（当前仍为占位实现）。"""
        friend_interval = max(1, int(self.config.tasks.friend.interval_seconds))
        if self._is_cancel_requested(session_id):
            return TaskResult(success=False, actions=[], next_run_seconds=friend_interval, error='停止中')
        logger.info('好友巡查功能开发中...')
        return TaskResult(success=True, actions=[], next_run_seconds=friend_interval, error='')
