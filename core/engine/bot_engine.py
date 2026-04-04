"""Bot引擎 — 主控编排层

三层架构：
  [1] 窗口控制层: window_manager + screen_capture
  [2] 图像识别层: cv_detector
  [3] 操作执行层: action_executor + nklite ops

优先级：
  P-1 异常处理: popup     — 关闭弹窗/商店/返回主界面
  P0  收益:     harvest   — 一键收获 + 自动出售
  P1  维护:     maintain  — 一键除草/除虫/浇水
  P2  生产:     plant     — 播种 + 购买种子 + 施肥
  P3  资源:     expand    — 扩建土地
  P3.2 出售:    sell      — 仓库批量出售
  P3.5 任务:    task      — 领取任务奖励
  P4  社交:     friend    — 好友巡查/帮忙/偷菜/同意好友
"""

import threading
import time
from datetime import datetime, timedelta

import cv2
import numpy as np
from loguru import logger
from PIL import Image as PILImage
from PyQt6.QtCore import QObject, pyqtSignal

from core.platform.action_executor import ActionExecutor
from core.vision.cv_detector import CVDetector, DetectResult
from core.platform.device import NKLiteDevice
from core.ops import ExpandOps, FriendOps, PlantOps, PopupOps, TaskOps
from core.tasks.task_farm_reward import TaskFarmReward
from core.tasks.task_farm_main import TaskFarmMain
from core.ui.page import (
    GOTO_MAIN,
    page_main,
)
from core.ui.ui import UI as NKLiteUI
from core.platform.screen_capture import ScreenCapture
from core.engine.task_executor import TaskExecutor
from core.engine.task_registry import (
    TaskContext,
    TaskItem,
    TaskResult,
    TaskSnapshot,
    build_default_tasks,
)
from core.engine.task_scheduler import TaskScheduler
from core.platform.window_manager import WindowManager
from models.config import AppConfig, PlantMode, TaskTriggerType
from models.farm_state import Action, ActionType
from models.game_data import get_best_crop_for_level


class BotEngine(QObject):
    log_message = pyqtSignal(str)
    screenshot_updated = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    detection_result = pyqtSignal(object)

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self._session_id = 0
        self._cancel_event = threading.Event()
        self._runtime_failure_count = 0

        # [1] 窗口控制层
        self.window_manager = WindowManager()
        self.screen_capture = ScreenCapture()

        # [2] 图像识别层
        self.cv_detector = CVDetector(templates_dir='templates')

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

    def _executor_running(self) -> bool:
        return bool(self._task_executor and self._task_executor.is_running())

    @staticmethod
    def _seconds_to_next_daily(daily_time: str, now: datetime | None = None) -> int:
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
        if not item or not item.enabled:
            return 0.0
        return item.next_run.timestamp()

    def _task_seconds_by_trigger(self, task_name: str, now: datetime | None = None) -> int:
        current = now or datetime.now()
        tasks_cfg = self.config.tasks
        cfg = getattr(tasks_cfg, task_name, None)
        if cfg is None:
            return int(self.config.executor.default_success_interval)
        if cfg.trigger == TaskTriggerType.DAILY:
            return self._seconds_to_next_daily(cfg.daily_time, current)
        return max(1, int(cfg.interval_seconds))

    def get_task_features(self, task_name: str) -> dict[str, bool]:
        cfg = getattr(self.config.tasks, task_name, None)
        if cfg is None:
            return {}
        raw = getattr(cfg, 'features', {}) or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): bool(v) for k, v in raw.items()}

    def _sync_executor_tasks_from_config(self):
        if not self._executor_tasks:
            return
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
        self._accept_executor_events = False
        executor = self._task_executor
        self._task_executor = None
        if executor:
            executor.stop(wait_timeout=1.5)
        self._executor_tasks = {}

    def _run_task_farm_main(self, _ctx: TaskContext) -> TaskResult:
        return self.check_farm(self._session_id)

    def _run_task_friend(self, _ctx: TaskContext) -> TaskResult:
        return self.check_friends(self._session_id)

    def _run_task_share(self, _ctx: TaskContext) -> TaskResult:
        return self.check_share(self._session_id)

    def _on_executor_snapshot(self, snapshot: TaskSnapshot):
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

    def _switch_session(self, cancelled: bool) -> int:
        """切换到新会话，旧会话结果自动作废。"""
        self._session_id += 1
        self._cancel_event = threading.Event()
        if cancelled:
            self._cancel_event.set()
        return self._session_id

    def _is_cancel_requested(self, session_id: int | None = None) -> bool:
        if session_id is not None and session_id != self._session_id:
            return True
        if self._task_executor and self._task_executor.is_stop_requested():
            return True
        return self._cancel_event.is_set()

    def is_session_cancelled(self, session_id: int) -> bool:
        return self._is_cancel_requested(session_id)

    def _sleep_interruptible(self, seconds: float, session_id: int | None = None, interval: float = 0.02) -> bool:
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
        self.config = config
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
        rect = None
        if self.nk_device is not None:
            rect = getattr(self.nk_device, 'rect', None)
        return self.resolve_capture_point(int(x), int(y), rect=rect)

    def _resolve_goto_main_point(self, rect: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
        return self.resolve_capture_point(*GOTO_MAIN.location, rect=rect)

    def start(self) -> bool:
        if self._executor_running():
            self.log_message.emit('上一轮任务仍在停止中，请稍候再启动')
            return False
        self._switch_session(cancelled=False)
        self._runtime_failure_count = 0
        self.cv_detector.load_templates()
        tpl_count = sum(len(v) for v in self.cv_detector._templates.values())
        if tpl_count == 0:
            self.log_message.emit('未找到模板图片，请先运行模板采集工具')
            return False

        window = self.window_manager.find_window(self.config.window_title_keyword)
        if not window:
            self.log_message.emit('未找到QQ农场窗口，请先打开微信小程序中的QQ农场')
            return False

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

        self.log_message.emit(f'Bot已启动(executor) - 窗口: {window.title} | 模板: {tpl_count}个')
        return True

    def stop(self):
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
        if self._task_executor:
            self._task_executor.pause()
        self.scheduler.force_state('paused')
        self.state_changed.emit('paused')
        self.stats_updated.emit(self.scheduler.get_stats())

    def resume(self):
        if self._task_executor:
            self._task_executor.resume()
        self.scheduler.force_state('running')
        self.state_changed.emit('running')
        self.stats_updated.emit(self.scheduler.get_stats())

    def run_once(self):
        if not self._task_executor or not self._task_executor.is_running():
            self.log_message.emit('执行器未运行，无法立即执行')
            return
        self._task_executor.task_call('farm_main')
        self._task_executor.resume()

    # ============================================================
    # 截屏 + 检测
    # ============================================================

    def _prepare_window(self) -> tuple | None:
        window = self.window_manager.refresh_window_info(self.config.window_title_keyword)
        if not window:
            return None
        self.window_manager.activate_window()
        if not self._sleep_interruptible(0.3):
            return None
        rect = self.window_manager.get_capture_rect()
        if not rect:
            rect = (window.left, window.top, window.width, window.height)
        if self.action_executor:
            self.action_executor.update_window_rect(rect)
        if self.nk_device:
            self.nk_device.set_rect(rect)
        return rect

    def _crop_preview_image(self, image: PILImage.Image | None) -> PILImage.Image | None:
        """仅用于左侧预览显示：按 nonclient 配置裁掉窗口边框/标题栏。"""
        if image is None:
            return None
        platform = getattr(self.config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        return self.window_manager.crop_window_image_for_preview(image, platform_value)

    def _capture_frame(
        self,
        rect: tuple,
        prefix: str = 'farm',
        save: bool = True,
    ) -> tuple[np.ndarray | None, PILImage.Image | None]:
        if save:
            image, _ = self.screen_capture.capture_and_save(rect, prefix)
        else:
            image = self.screen_capture.capture_region(rect)
        if image is None:
            return None, None
        preview_image = self._crop_preview_image(image)
        if preview_image is None:
            return None, None
        self.screenshot_updated.emit(preview_image)
        cv_image = self.cv_detector.pil_to_cv2(preview_image)
        return cv_image, preview_image

    def _capture_and_detect(
        self,
        rect: tuple,
        prefix: str = 'farm',
        categories: list[str] | None = None,
        template_names: list[str] | None = None,
        template_thresholds: dict[str, float] | None = None,
        template_rois: dict[str, tuple[int, int, int, int]] | None = None,
        save: bool = True,
    ) -> tuple[np.ndarray | None, list[DetectResult], PILImage.Image | None]:
        cv_image, image = self._capture_frame(rect, prefix=prefix, save=save)
        if cv_image is None or image is None:
            return None, [], None

        if template_names is not None:
            detections = self.cv_detector.detect_templates(
                cv_image,
                template_names=template_names,
                default_threshold=0.8,
                thresholds=template_thresholds,
                roi_map=template_rois,
            )
        elif categories is not None:
            detections = []
            for cat in categories:
                detections += self.cv_detector.detect_category(cv_image, cat, threshold=0.8)
            detections = self.cv_detector._nms(detections, iou_threshold=0.5)
        else:
            detections = []

        return cv_image, detections, image

    def _nklite_screenshot(self, rect: tuple[int, int, int, int]) -> np.ndarray | None:
        cv_image, _ = self._capture_frame(rect, save=False)
        return cv_image

    def _nklite_click(self, x: int, y: int, desc: str) -> bool:
        if not self.action_executor:
            return False
        rel_x, rel_y = self.resolve_live_click_point(int(x), int(y))
        action = Action(
            type=ActionType.NAVIGATE,
            click_position={'x': int(rel_x), 'y': int(rel_y)},
            priority=0,
            description=str(desc or 'nklite_click'),
        )
        result = self.action_executor.execute_action(action)
        return bool(result.success)

    def _nklite_sleep(self, seconds: float) -> bool:
        return self._sleep_interruptible(seconds)

    def _emit_annotated(self, cv_image: np.ndarray, detections: list[DetectResult]):
        if detections:
            annotated = self.cv_detector.draw_results(cv_image, detections)
            annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            annotated_pil = PILImage.fromarray(annotated_rgb)
            self.detection_result.emit(annotated_pil)

    def _record_stat(self, action_type: str):
        type_map = {
            ActionType.HARVEST: 'harvest',
            ActionType.PLANT: 'plant',
            ActionType.WATER: 'water',
            ActionType.WEED: 'weed',
            ActionType.BUG: 'bug',
            ActionType.STEAL: 'steal',
            ActionType.SELL: 'sell',
        }
        stat_key = type_map.get(action_type)
        if stat_key:
            self.scheduler.record_action(stat_key)

    def _augment_detections(
        self,
        cv_image: np.ndarray,
        detections: list[DetectResult],
        template_names: list[str],
        thresholds: dict[str, float] | None = None,
        default_threshold: float = 0.8,
    ) -> list[DetectResult]:
        """仅补齐缺失模板，避免每轮重复跑大集合识别。"""
        base = list(detections or [])
        wanted = [str(name).strip() for name in template_names if str(name).strip()]
        if not wanted:
            return base

        existing = {d.name for d in base}
        missing = [name for name in wanted if name not in existing]
        if not missing:
            return base

        extra = self.cv_detector.detect_templates(
            cv_image,
            template_names=missing,
            default_threshold=default_threshold,
            thresholds=thresholds,
        )
        if not extra:
            return base

        merged = base + extra
        return self.cv_detector._nms(merged, iou_threshold=0.5)

    def _handle_seed_select_scene(self, detections: list[DetectResult]) -> str | None:
        crop_name = self._resolve_crop_name()
        seed = self.popup.find_by_name(detections, f'seed_{crop_name}')
        if not seed:
            return None
        self.popup.click(seed.x, seed.y, f'播种{crop_name}', ActionType.PLANT)
        self._record_stat(ActionType.PLANT)
        return f'播种{crop_name}'

    # ============================================================
    # 主循环
    # ============================================================

    def check_farm(self, session_id: int | None = None) -> TaskResult:
        if self.nk_task_farm_main is not None:
            return self.nk_task_farm_main.run(session_id=session_id)
        return TaskResult(success=False, actions=[], next_run_seconds=5, error='nklite 农场任务未初始化')

    def check_share(self, session_id: int | None = None) -> TaskResult:
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
        friend_interval = max(1, int(self.config.tasks.friend.interval_seconds))
        if self._is_cancel_requested(session_id):
            return TaskResult(success=False, actions=[], next_run_seconds=friend_interval, error='停止中')
        logger.info('好友巡查功能开发中...')
        return TaskResult(success=True, actions=[], next_run_seconds=friend_interval, error='')




