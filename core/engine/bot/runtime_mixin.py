"""Bot 生命周期与运行态控制逻辑。"""

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


class BotRuntimeMixin:
    """Bot 生命周期与运行态控制逻辑。"""

    def _switch_session(self, cancelled: bool) -> int:
        """切换到新会话，旧会话结果自动作废。"""
        self._session_id += 1
        self._cancel_event = threading.Event()
        if cancelled:
            self._cancel_event.set()
        return self._session_id

    def _is_cancel_requested(self, session_id: int | None = None) -> bool:
        """判断是否满足 `cancel_requested` 条件。"""
        if session_id is not None and session_id != self._session_id:
            return True
        if self._task_executor and self._task_executor.is_stop_requested():
            return True
        return self._cancel_event.is_set()

    def is_session_cancelled(self, session_id: int) -> bool:
        """对外暴露：判断指定会话是否已取消。"""
        return self._is_cancel_requested(session_id)

    def _sleep_interruptible(self, seconds: float, session_id: int | None = None, interval: float = 0.02) -> bool:
        """可中断睡眠：检测到取消请求时提前返回 False。"""
        if seconds <= 0:
            return not self._is_cancel_requested(session_id)
        end_at = time.perf_counter() + seconds
        while True:
            if self._is_cancel_requested(session_id):
                return False
            remain = end_at - time.perf_counter()
            if remain <= 0:
                return True
            time.sleep(min(interval, remain))

    def update_config(self, config: AppConfig):
        """更新配置并将变更同步到执行器。"""
        self.config = config
        platform = getattr(config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        Button.set_template_platform(normalize_template_platform(platform_value))
        self._sync_executor_tasks_from_config()

    def _resolve_crop_name_quiet(self) -> str:
        """根据策略决定种植作物（静默版本，不打印日志）。"""
        planting = self.config.planting
        if planting.strategy == PlantMode.BEST_EXP_RATE:
            best = get_best_crop_for_level(planting.player_level)
            if best:
                return best[0]
        return planting.preferred_crop

    def _resolve_crop_name(self) -> str:
        """根据策略决定种植作物"""
        crop_name = self._resolve_crop_name_quiet()
        if self.config.planting.strategy == PlantMode.BEST_EXP_RATE:
            best = get_best_crop_for_level(self.config.planting.player_level)
            if best:
                logger.info(f'策略选择: {best[0]} (经验效率 {best[4] / best[3]:.4f}/秒)')
        return crop_name

    def _clear_screen(self, rect: tuple, session_id: int | None = None):
        """通过 GOTO_MAIN 连续点击 2 次，尽量回到稳定主界面。"""
        if not self.action_executor:
            return

        goto_x, goto_y = GOTO_MAIN.location
        for _ in range(2):
            if self._is_cancel_requested(session_id):
                break
            self._nklite_click(goto_x, goto_y, 'goto_main')
            if self._is_cancel_requested(session_id):
                break
            if not self._sleep_interruptible(0.3, session_id):
                break

    def resolve_capture_point(
        self,
        base_x: int,
        base_y: int,
        rect: tuple[int, int, int, int] | None = None,
    ) -> tuple[int, int]:
        """将目标客户区坐标映射为当前截图坐标（含非客户区偏移）。"""
        use_rect = rect
        if not use_rect or len(use_rect) != 4:
            use_rect = self.window_manager.get_capture_rect()
        if not use_rect or len(use_rect) != 4:
            return int(base_x), int(base_y)

        cap_w = int(use_rect[2])
        cap_h = int(use_rect[3])
        if cap_w <= 0 or cap_h <= 0:
            return int(base_x), int(base_y)

        platform = getattr(self.config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        x1, y1, _crop_w, _crop_h = self.window_manager.get_preview_crop_box(cap_w, cap_h, platform_value)

        x = int(base_x + x1)
        y = int(base_y + y1)
        x = max(0, min(x, cap_w - 1))
        y = max(0, min(y, cap_h - 1))
        return x, y

    def resolve_live_click_point(self, x: int, y: int) -> tuple[int, int]:
        """将逻辑点击坐标映射到当前截图坐标系。"""
        rect = None
        if self.nk_device is not None:
            rect = getattr(self.nk_device, 'rect', None)
        return self.resolve_capture_point(int(x), int(y), rect=rect)

    def _resolve_goto_main_point(self, rect: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
        """计算“回主按钮”在当前截图中的点击坐标。"""
        return self.resolve_capture_point(*GOTO_MAIN.location, rect=rect)

    def start(self) -> bool:
        """启动当前模块的主流程。"""
        if self._executor_running():
            self.log_message.emit('上一轮任务仍在停止中，请稍候再启动')
            return False
        # [启动阶段] 重置运行会话与计数器。
        self._switch_session(cancelled=False)
        self._runtime_failure_count = 0
        current_platform = getattr(self.config.planting, 'window_platform', 'qq')
        current_platform_value = current_platform.value if hasattr(current_platform, 'value') else str(current_platform)
        Button.set_template_platform(normalize_template_platform(current_platform_value))
        asset_count = len(ASSET_NAME_TO_CONST)
        if asset_count == 0:
            self.log_message.emit('未找到 assets 按钮模板，请先运行 button_extract 工具')
            return False

        window = self.window_manager.find_window(self.config.window_title_keyword)
        if not window:
            self.log_message.emit('未找到QQ农场窗口，请先打开微信小程序中的QQ农场')
            return False

        # [窗口阶段] 调整窗口尺寸与位置，确保截图区域稳定。
        pos = getattr(self.config.planting, 'window_position', 'left_center')
        pos_value = pos.value if hasattr(pos, 'value') else str(pos)
        platform = getattr(self.config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        self.window_manager.resize_window(pos_value, platform_value)
        self._sleep_interruptible(0.5)
        window = self.window_manager.refresh_window_info(self.config.window_title_keyword)
        self.log_message.emit(
            f'窗口已调整（整窗外框目标：540x960 + 非客户区增量）-> 实际外框 {window.width}x{window.height}'
        )

        rect = self.window_manager.get_capture_rect()
        if not rect:
            rect = (window.left, window.top, window.width, window.height)
        self.action_executor = ActionExecutor(
            window_rect=rect,
            delay_min=self.config.safety.random_delay_min,
            delay_max=self.config.safety.random_delay_max,
            click_offset=self.config.safety.click_offset_range,
        )
        # [适配层阶段] 构建 nklite 设备/UI/任务对象，供执行器回调使用。
        self.action_executor.set_cancel_checker(self._is_cancel_requested)
        self.nk_device = NKLiteDevice(
            screenshot_fn=self._nklite_screenshot,
            click_fn=self._nklite_click,
            sleep_fn=self._nklite_sleep,
            cancel_checker=self._is_cancel_requested,
        )
        self.nk_device.set_rect(rect)
        self.nk_ui = NKLiteUI(
            config=self.config,
            detector=self.cv_detector,
            device=self.nk_device,
            crop_name_resolver=self._resolve_crop_name_quiet,
            cancel_checker=self._is_cancel_requested,
        )
        self.nk_task_farm_main = TaskFarmMain(engine=self, ui=self.nk_ui)

        self.scheduler.stop()
        self.scheduler.force_state('running')
        self.scheduler.update_runtime_metrics(
            current_task='--',
            current_page='unknown',
            failure_count=self._runtime_failure_count,
            running_tasks=0,
            pending_tasks=0,
            waiting_tasks=0,
            last_result='--',
            last_tick_ms='--',
        )
        self._init_executor()

        self.log_message.emit(f'Bot已启动(executor) - 窗口: {window.title} | assets: {asset_count}个')
        return True

    def stop(self):
        """停止当前模块并释放运行状态。"""
        self._switch_session(cancelled=True)
        self._stop_executor()
        self.nk_task_farm_main = None
        self.nk_ui = None
        self.nk_device = None
        self.scheduler.force_state('idle')

        self.scheduler.update_runtime_metrics(
            current_task='--',
            current_page='--',
            failure_count=self._runtime_failure_count,
            running_tasks=0,
            pending_tasks=0,
            waiting_tasks=0,
            last_result='--',
            last_tick_ms='--',
        )
        self.scheduler.set_next_checks(farm_ts=0.0, friend_ts=0.0)
        # 兜底刷新：确保UI在点击停止后立即看到最新状态。
        self.state_changed.emit('idle')
        self.stats_updated.emit(self.scheduler.get_stats())
        self.log_message.emit('Bot已停止')

    def pause(self):
        """暂停当前模块执行。"""
        if self._task_executor:
            self._task_executor.pause()
        self.scheduler.force_state('paused')
        self.state_changed.emit('paused')
        self.stats_updated.emit(self.scheduler.get_stats())

    def resume(self):
        """恢复当前模块执行。"""
        if self._task_executor:
            self._task_executor.resume()
        self.scheduler.force_state('running')
        self.state_changed.emit('running')
        self.stats_updated.emit(self.scheduler.get_stats())

    def run_once(self):
        """立即触发一次 `farm_main` 任务执行。"""
        if not self._task_executor or not self._task_executor.is_running():
            self.log_message.emit('执行器未运行，无法立即执行')
            return
        self._task_executor.task_call('farm_main')
        self._task_executor.resume()
