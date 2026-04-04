"""Bot 执行器与调度相关逻辑。"""

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


class BotExecutorMixin:
    """Bot 执行器与调度相关逻辑。"""

    def _executor_running(self) -> bool:
        """判断执行器线程是否仍在运行。"""
        return bool(self._task_executor and self._task_executor.is_running())

    @staticmethod
    def _seconds_to_next_daily(daily_time: str, now: datetime | None = None) -> int:
        """计算距离下一次每日触发时间的秒数。"""
        current = now or datetime.now()
        text = str(daily_time or '04:00')
        try:
            hour = int(text[:2])
            minute = int(text[3:5])
        except Exception:
            hour, minute = 4, 0
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= current:
            target = target + timedelta(days=1)
        return max(1, int((target - current).total_seconds()))

    @staticmethod
    def _task_next_ts(item: TaskItem | None) -> float:
        """读取任务的下一次执行时间戳（禁用任务返回 0）。"""
        if not item or not item.enabled:
            return 0.0
        return item.next_run.timestamp()

    def _task_seconds_by_trigger(self, task_name: str, now: datetime | None = None) -> int:
        """按任务触发类型返回下次调度间隔秒数。"""
        current = now or datetime.now()
        tasks_cfg = self.config.tasks
        cfg = getattr(tasks_cfg, task_name, None)
        if cfg is None:
            return int(self.config.executor.default_success_interval)
        if cfg.trigger == TaskTriggerType.DAILY:
            return self._seconds_to_next_daily(cfg.daily_time, current)
        return max(1, int(cfg.interval_seconds))

    def get_task_features(self, task_name: str) -> dict[str, bool]:
        """获取 `task_features` 信息。"""
        cfg = getattr(self.config.tasks, task_name, None)
        if cfg is None:
            return {}
        raw = getattr(cfg, 'features', {}) or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): bool(v) for k, v in raw.items()}

    def _sync_executor_tasks_from_config(self):
        """将当前配置同步到执行器任务项（启停、间隔、失败参数）。"""
        if not self._executor_tasks:
            return
        # 统一按当前配置计算每个任务的启停状态与执行间隔。
        default_success = max(1, int(self.config.executor.default_success_interval))
        default_failure = max(1, int(self.config.executor.default_failure_interval))
        max_failures = max(1, int(self.config.executor.max_failures))
        now = datetime.now()

        farm_cfg = self.config.tasks.farm_main
        friend_cfg = self.config.tasks.friend
        share_cfg = self.config.tasks.share

        farm_enabled = bool(farm_cfg.enabled)
        friend_enabled = bool(friend_cfg.enabled)
        share_enabled = bool(share_cfg.enabled)

        farm_success = max(default_success, self._task_seconds_by_trigger('farm_main', now))
        friend_success = max(default_success, self._task_seconds_by_trigger('friend', now))
        share_success = max(default_success, self._task_seconds_by_trigger('share', now))
        farm_failure = max(default_failure, int(farm_cfg.failure_interval_seconds))
        friend_failure = max(default_failure, int(friend_cfg.failure_interval_seconds))
        share_failure = max(default_failure, int(share_cfg.failure_interval_seconds))

        share_next_run = (
            now + timedelta(seconds=self._task_seconds_by_trigger('share', now))
            if share_cfg.trigger == TaskTriggerType.DAILY
            else now
        )

        if self._task_executor:
            # 执行器已启动：直接热更新运行中的任务参数。
            self._task_executor.set_empty_queue_policy(self.config.executor.empty_queue_policy)
            self._task_executor.update_task(
                'farm_main',
                enabled=farm_enabled,
                success_interval=farm_success,
                failure_interval=farm_failure,
                max_failures=max_failures,
            )
            self._task_executor.update_task(
                'friend',
                enabled=friend_enabled,
                success_interval=friend_success,
                failure_interval=friend_failure,
                max_failures=max_failures,
            )
            self._task_executor.update_task(
                'share',
                enabled=share_enabled,
                success_interval=share_success,
                failure_interval=share_failure,
                max_failures=max_failures,
                next_run=share_next_run,
            )
            if friend_enabled:
                self._task_executor.task_call('friend', force_call=False)
            if share_enabled and share_cfg.trigger == TaskTriggerType.INTERVAL:
                self._task_executor.task_call('share', force_call=False)
            return

        # 执行器未启动：仅更新本地任务快照，等待 _init_executor 使用。
        farm_item = self._executor_tasks.get('farm_main')
        if farm_item:
            farm_item.enabled = farm_enabled
            farm_item.success_interval = farm_success
            farm_item.failure_interval = farm_failure
            farm_item.max_failures = max_failures

        friend_item = self._executor_tasks.get('friend')
        if friend_item:
            friend_item.enabled = friend_enabled
            friend_item.success_interval = friend_success
            friend_item.failure_interval = friend_failure
            friend_item.max_failures = max_failures
            if friend_enabled and friend_item.next_run < now:
                friend_item.next_run = now

        share_item = self._executor_tasks.get('share')
        if share_item:
            share_item.enabled = share_enabled
            share_item.success_interval = share_success
            share_item.failure_interval = share_failure
            share_item.max_failures = max_failures
            if share_cfg.trigger == TaskTriggerType.DAILY:
                share_item.next_run = share_next_run
            elif share_item.next_run < now:
                share_item.next_run = now

    def _init_executor(self):
        """创建并启动统一任务执行器。"""
        self._executor_tasks = build_default_tasks(self.config)
        self._sync_executor_tasks_from_config()
        self._accept_executor_events = True
        self._task_executor = TaskExecutor(
            tasks=self._executor_tasks,
            runners={
                'farm_main': self._run_task_farm_main,
                'friend': self._run_task_friend,
                'share': self._run_task_share,
            },
            empty_queue_policy=self.config.executor.empty_queue_policy,
            on_snapshot=self._on_executor_snapshot,
            on_task_done=self._on_executor_task_done,
            on_idle=self._on_executor_idle,
        )
        self._task_executor.start()

    def _stop_executor(self):
        """停止执行器并清空执行器持有的任务快照。"""
        self._accept_executor_events = False
        executor = self._task_executor
        self._task_executor = None
        if executor:
            executor.stop(wait_timeout=1.5)
        self._executor_tasks = {}

    def _run_task_farm_main(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_farm_main` 子流程。"""
        return self.check_farm(self._session_id)

    def _run_task_friend(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_friend` 子流程。"""
        return self.check_friends(self._session_id)

    def _run_task_share(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_share` 子流程。"""
        return self.check_share(self._session_id)

    def _on_executor_snapshot(self, snapshot: TaskSnapshot):
        """接收执行器快照并更新 GUI 统计面板。"""
        if not self._accept_executor_events:
            return
        self.scheduler.update_runtime_metrics(
            current_task=snapshot.running_task or '--',
            failure_count=self._runtime_failure_count,
            running_tasks=1 if snapshot.running_task else 0,
            pending_tasks=len(snapshot.pending_tasks),
            waiting_tasks=len(snapshot.waiting_tasks),
        )
        self.scheduler.set_next_checks(
            farm_ts=self._task_next_ts(self._executor_tasks.get('farm_main')),
            friend_ts=self._task_next_ts(self._executor_tasks.get('friend')),
        )

    def _on_executor_task_done(self, task_name: str, result: TaskResult):
        """处理任务完成事件并更新运行统计。"""
        if not self._accept_executor_events:
            return
        if result.actions:
            self.log_message.emit(f'[{task_name}] 本轮完成: {", ".join(result.actions)}')
        if result.success:
            self._runtime_failure_count = 0
        else:
            self._runtime_failure_count += 1
            if result.error:
                self.log_message.emit(f'[{task_name}] 操作异常: {result.error}')

        last_result = result.actions[-1] if result.actions else ('ok' if result.success else 'failed')
        self.scheduler.update_runtime_metrics(
            failure_count=self._runtime_failure_count,
            last_result=last_result,
        )

    def _on_executor_idle(self):
        """执行器空闲时触发：按策略尝试回主界面。"""
        if not self._accept_executor_events:
            return
        if self._is_cancel_requested():
            return
        if not self.nk_ui:
            return
        rect = self.window_manager.get_capture_rect()
        if rect and self.nk_device:
            self.nk_device.set_rect(rect)
        try:
            self.nk_ui.ui_goto_main()
        except Exception as exc:
            logger.debug(f'idle ensure main failed: {exc}')
