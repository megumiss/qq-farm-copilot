"""Bot引擎 — 主控编排层

四层架构：
  [1] 窗口控制层: window_manager + screen_capture
  [2] 图像识别层: cv_detector + scene_detector
  [3] 行为决策层: strategies/ (模块化策略)
  [4] 操作执行层: action_executor

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
import time
import threading
from datetime import datetime
from enum import Enum
import cv2
import numpy as np
from PIL import Image as PILImage
from loguru import logger

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from models.config import AppConfig, PlantMode, EngineMode
from models.farm_state import ActionType
from models.game_data import get_best_crop_for_level, get_crop_by_name, format_grow_time
from core.window_manager import WindowManager
from core.screen_capture import ScreenCapture
from core.cv_detector import CVDetector, DetectResult
from core.action_executor import ActionExecutor
from core.task_scheduler import TaskScheduler
from core.task_executor import TaskExecutor
from core.task_registry import TaskItem, TaskResult, TaskSnapshot, build_default_tasks
from core.scene_detector import Scene, identify_scene, SceneStabilityTracker
from core.page_graph import PageId
from core.navigator import Navigator
from core.ui_guard import UIGuard
from core.strategies import (
    PopupStrategy, HarvestStrategy, MaintainStrategy,
    PlantStrategy, ExpandStrategy, SellStrategy, TaskStrategy, FriendStrategy,
)
from core.strategies.base import StrategyResult


class RuntimeState(str, Enum):
    MAIN = "main"
    POPUP = "popup"
    SHOP = "shop"
    BUY_CONFIRM = "buy_confirm"
    PLOT_MENU = "plot_menu"
    SEED_SELECT = "seed_select"
    FRIEND = "friend"
    UNKNOWN = "unknown"


class BotWorker(QThread):
    finished = pyqtSignal(int, dict)
    error = pyqtSignal(int, str)

    def __init__(self, engine: "BotEngine", session_id: int, task_type: str = "farm"):
        super().__init__()
        self.engine = engine
        self.session_id = session_id
        self.task_type = task_type

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            if self.engine.is_session_cancelled(self.session_id):
                return
            if self.task_type == "farm":
                result = self.engine.check_farm(self.session_id)
            elif self.task_type == "friend":
                result = self.engine.check_friends(self.session_id)
            else:
                result = {"success": False, "message": "未知任务类型"}
            self.finished.emit(self.session_id, result)
        except Exception as e:
            logger.exception(f"任务执行异常: {e}")
            self.error.emit(self.session_id, str(e))


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
        self._runtime_state = RuntimeState.UNKNOWN
        self._runtime_state_since = time.time()
        self._expected_states: set[RuntimeState] | None = None
        self._expected_reason = ""
        self._expected_deadline = 0.0
        self._runtime_failure_count = 0
        self._scene_tracker = SceneStabilityTracker(
            stable_hits=2,
            level_up_hits=1,
            confirm_timeout=1.0,
        )

        # [1] 窗口控制层
        self.window_manager = WindowManager()
        self.screen_capture = ScreenCapture()

        # [2] 图像识别层
        self.cv_detector = CVDetector(templates_dir="templates")

        # [3] 行为决策层（按优先级）
        self.popup = PopupStrategy(self.cv_detector)       # P-1
        self.harvest = HarvestStrategy(self.cv_detector)    # P0
        self.maintain = MaintainStrategy(self.cv_detector)  # P1
        self.plant = PlantStrategy(self.cv_detector)        # P2
        self.expand = ExpandStrategy(self.cv_detector)      # P3
        self.sell = SellStrategy(self.cv_detector)          # P3.2
        self.task = TaskStrategy(self.cv_detector)          # P3.5
        self.friend = FriendStrategy(self.cv_detector)      # P4
        self._strategies = [self.popup, self.harvest, self.maintain,
                            self.plant, self.expand, self.sell, self.task, self.friend]

        # [4] 操作执行层
        self.action_executor: ActionExecutor | None = None
        self.navigator: Navigator | None = None
        self.ui_guard: UIGuard | None = None

        # 调度
        self.scheduler = TaskScheduler()
        self._worker: BotWorker | None = None
        self._engine_mode: EngineMode = self._resolve_engine_mode(config)
        self._task_executor: TaskExecutor | None = None
        self._executor_tasks: dict[str, TaskItem] = {}

        self.scheduler.farm_check_triggered.connect(self._on_farm_check)
        self.scheduler.friend_check_triggered.connect(self._on_friend_check)
        self.scheduler.state_changed.connect(self.state_changed.emit)
        self.scheduler.stats_updated.connect(self.stats_updated.emit)

    def _init_strategies(self):
        """初始化所有策略的依赖"""
        for s in self._strategies:
            s.action_executor = self.action_executor
            s.set_capture_fn(self._capture_and_detect)
            s._stop_requested = False
            s.set_cancel_checker(self._is_cancel_requested)
            s.set_action_hook(self._on_strategy_action)

    def _resolve_engine_mode(self, config: AppConfig) -> EngineMode:
        mode = getattr(config, "engine_mode", EngineMode.LEGACY)
        if isinstance(mode, EngineMode):
            return mode
        text = str(mode or "").strip().lower()
        if text == EngineMode.EXECUTOR.value:
            return EngineMode.EXECUTOR
        if text == EngineMode.LEGACY.value:
            return EngineMode.LEGACY
        if getattr(config, "executor", None) and bool(config.executor.enabled):
            return EngineMode.EXECUTOR
        return EngineMode.LEGACY

    def _using_executor_mode(self) -> bool:
        return self._engine_mode == EngineMode.EXECUTOR

    def _executor_running(self) -> bool:
        return bool(self._task_executor and self._task_executor.is_running())

    @staticmethod
    def _task_next_ts(item: TaskItem | None) -> float:
        if not item or not item.enabled:
            return 0.0
        return item.next_run.timestamp()

    def _sync_executor_tasks_from_config(self):
        if not self._executor_tasks:
            return
        default_success = max(1, int(self.config.executor.default_success_interval))
        default_failure = max(1, int(self.config.executor.default_failure_interval))
        max_failures = max(1, int(self.config.executor.max_failures))
        farm_success = max(default_success, int(self.config.schedule.farm_check_minutes) * 60)
        friend_success = max(default_success, int(self.config.schedule.friend_check_minutes) * 60)
        friend_enabled = bool(self.config.features.auto_help or self.config.features.auto_steal)

        if self._task_executor:
            self._task_executor.set_empty_queue_policy(self.config.executor.empty_queue_policy)
            self._task_executor.update_task(
                "farm_main",
                enabled=True,
                success_interval=farm_success,
                failure_interval=default_failure,
                max_failures=max_failures,
            )
            self._task_executor.update_task(
                "friend",
                enabled=friend_enabled,
                success_interval=friend_success,
                failure_interval=max(default_failure, 60),
                max_failures=max_failures,
            )
            if friend_enabled:
                self._task_executor.task_call("friend", force_call=False)
            return

        farm_item = self._executor_tasks.get("farm_main")
        if farm_item:
            farm_item.enabled = True
            farm_item.success_interval = farm_success
            farm_item.failure_interval = default_failure
            farm_item.max_failures = max_failures

        friend_item = self._executor_tasks.get("friend")
        if friend_item:
            friend_item.enabled = friend_enabled
            friend_item.success_interval = friend_success
            friend_item.failure_interval = max(default_failure, 60)
            friend_item.max_failures = max_failures
            if friend_enabled and friend_item.next_run < datetime.now():
                friend_item.next_run = datetime.now()

    def _init_executor(self):
        self._executor_tasks = build_default_tasks(self.config)
        self._sync_executor_tasks_from_config()
        self._task_executor = TaskExecutor(
            tasks=self._executor_tasks,
            runners={
                "farm_main": self._run_task_farm_main,
                "friend": self._run_task_friend,
            },
            empty_queue_policy=self.config.executor.empty_queue_policy,
            on_snapshot=self._on_executor_snapshot,
            on_task_done=self._on_executor_task_done,
            on_idle=self._on_executor_idle,
        )
        self._task_executor.start()

    def _stop_executor(self):
        executor = self._task_executor
        self._task_executor = None
        if executor:
            executor.stop(wait_timeout=1.5)
        self._executor_tasks = {}

    def _run_task_farm_main(self) -> TaskResult:
        payload = self.check_farm(self._session_id)
        return TaskResult.from_legacy_dict(payload)

    def _run_task_friend(self) -> TaskResult:
        payload = self.check_friends(self._session_id)
        return TaskResult.from_legacy_dict(payload)

    def _on_executor_snapshot(self, snapshot: TaskSnapshot):
        self.scheduler.update_runtime_metrics(
            current_task=snapshot.running_task or "--",
            failure_count=self._runtime_failure_count,
            running_tasks=1 if snapshot.running_task else 0,
            pending_tasks=len(snapshot.pending_tasks),
            waiting_tasks=len(snapshot.waiting_tasks),
        )
        self.scheduler.set_next_checks(
            farm_ts=self._task_next_ts(self._executor_tasks.get("farm_main")),
            friend_ts=self._task_next_ts(self._executor_tasks.get("friend")),
        )

    def _on_executor_task_done(self, task_name: str, result: TaskResult):
        if result.actions:
            self.log_message.emit(f"[{task_name}] 本轮完成: {', '.join(result.actions)}")
        if result.success:
            self._runtime_failure_count = 0
        else:
            self._runtime_failure_count += 1
            if result.error:
                self.log_message.emit(f"[{task_name}] 操作异常: {result.error}")

        last_result = result.actions[-1] if result.actions else ("ok" if result.success else "failed")
        self.scheduler.update_runtime_metrics(
            failure_count=self._runtime_failure_count,
            last_result=last_result,
        )

    def _on_executor_idle(self):
        if self._is_cancel_requested():
            return
        if not self.navigator:
            return
        rect = self.window_manager.get_capture_rect()
        if not rect:
            return
        try:
            self.navigator.ensure(rect, PageId.MAIN, timeout=0.8, confirm_wait=0.12)
        except Exception as exc:
            logger.debug(f"idle ensure main failed: {exc}")

    def _reset_scene_confirm(self):
        self._scene_tracker.reset()

    def _confirm_scene(self, raw_scene: Scene) -> Scene | None:
        return self._scene_tracker.feed(raw_scene)

    @staticmethod
    def _scene_to_runtime_state(scene: Scene) -> RuntimeState:
        if scene == Scene.FARM_OVERVIEW:
            return RuntimeState.MAIN
        if scene == Scene.POPUP or scene == Scene.LEVEL_UP:
            return RuntimeState.POPUP
        if scene == Scene.SHOP_PAGE:
            return RuntimeState.SHOP
        if scene == Scene.BUY_CONFIRM:
            return RuntimeState.BUY_CONFIRM
        if scene == Scene.PLOT_MENU:
            return RuntimeState.PLOT_MENU
        if scene == Scene.SEED_SELECT:
            return RuntimeState.SEED_SELECT
        if scene == Scene.FRIEND_FARM:
            return RuntimeState.FRIEND
        return RuntimeState.UNKNOWN

    def _set_runtime_state(self, state: RuntimeState, source: str = ""):
        if state == self._runtime_state:
            return
        old = self._runtime_state
        self._runtime_state = state
        self._runtime_state_since = time.time()
        if source:
            logger.debug(f"运行状态切换: {old.value} -> {state.value} ({source})")
        else:
            logger.debug(f"运行状态切换: {old.value} -> {state.value}")

    def _expect_runtime_states(self, states: set[RuntimeState], timeout: float, reason: str):
        self._expected_states = set(states)
        self._expected_reason = str(reason)
        self._expected_deadline = time.time() + max(0.1, float(timeout))
        expect = ",".join(sorted(s.value for s in self._expected_states))
        logger.debug(f"设置期望跳转: reason={reason}, states={expect}, timeout={timeout:.1f}s")

    def _clear_expected_states(self):
        self._expected_states = None
        self._expected_reason = ""
        self._expected_deadline = 0.0

    def _verify_expected_runtime(self) -> bool:
        if not self._expected_states:
            return True
        if self._runtime_state in self._expected_states:
            logger.debug(
                f"期望跳转满足: reason={self._expected_reason}, state={self._runtime_state.value}"
            )
            self._clear_expected_states()
            return True
        if time.time() < self._expected_deadline:
            return True
        expect = ",".join(sorted(s.value for s in self._expected_states))
        logger.warning(
            f"期望跳转超时: reason={self._expected_reason}, "
            f"expected={expect}, actual={self._runtime_state.value}"
        )
        self._clear_expected_states()
        return False

    def _on_strategy_action(self, desc: str, action_type: str):
        text = (desc or "").strip()
        if not text:
            return

        expected = self._get_expected_states(action_type, text)
        if not expected:
            return
        states, timeout = expected
        self._expect_runtime_states(states, timeout=timeout, reason=text or action_type)

    def _get_expected_states(
        self,
        action_type: str,
        text: str,
    ) -> tuple[set[RuntimeState], float] | None:
        if action_type == ActionType.PLANT:
            return (
                {RuntimeState.MAIN, RuntimeState.PLOT_MENU, RuntimeState.SEED_SELECT},
                1.5,
            )
        if action_type == ActionType.CLOSE_POPUP:
            return (
                {
                    RuntimeState.MAIN, RuntimeState.POPUP, RuntimeState.PLOT_MENU,
                    RuntimeState.SEED_SELECT, RuntimeState.SHOP, RuntimeState.BUY_CONFIRM,
                },
                1.5,
            )
        if action_type in {
            ActionType.HARVEST, ActionType.WATER, ActionType.WEED,
            ActionType.BUG, ActionType.SELL,
        }:
            return ({RuntimeState.MAIN}, 1.5)

        nav_text_map: list[tuple[str, set[RuntimeState], float]] = [
            ("点击任务", {RuntimeState.POPUP, RuntimeState.SHOP, RuntimeState.BUY_CONFIRM}, 2.0),
            ("打开商店", {RuntimeState.SHOP, RuntimeState.BUY_CONFIRM}, 2.0),
            ("好友求助", {RuntimeState.FRIEND}, 2.0),
            ("回家", {RuntimeState.MAIN}, 2.0),
            ("关闭", {RuntimeState.MAIN, RuntimeState.POPUP, RuntimeState.SHOP, RuntimeState.BUY_CONFIRM}, 1.5),
            ("点击空白处", {RuntimeState.MAIN, RuntimeState.POPUP, RuntimeState.PLOT_MENU, RuntimeState.SEED_SELECT}, 1.5),
        ]
        for keyword, states, timeout in nav_text_map:
            if keyword in text:
                return states, timeout
        return None

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

    def _worker_running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def _sleep_interruptible(self, seconds: float, session_id: int | None = None,
                             interval: float = 0.02) -> bool:
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

    def _spawn_worker(self, task_type: str):
        if self._is_cancel_requested():
            return
        if self._worker_running():
            logger.debug("上一轮操作尚未完成，跳过")
            return
        self.scheduler.update_runtime_metrics(
            current_task=task_type,
            running_tasks=1,
            pending_tasks=0,
            waiting_tasks=0,
        )
        worker = BotWorker(self, session_id=self._session_id, task_type=task_type)
        worker.finished.connect(self._on_task_finished)
        worker.error.connect(self._on_task_error)
        self._worker = worker
        worker.start()

    def update_config(self, config: AppConfig):
        self.config = config
        new_mode = self._resolve_engine_mode(config)
        if not self._worker_running() and not self._executor_running():
            self._engine_mode = new_mode
        elif new_mode != self._engine_mode:
            self.log_message.emit(f"执行模式将在下次启动时切换为: {new_mode.value}")
        self._sync_executor_tasks_from_config()

    def _resolve_crop_name(self) -> str:
        """根据策略决定种植作物"""
        planting = self.config.planting
        if planting.strategy == PlantMode.BEST_EXP_RATE:
            best = get_best_crop_for_level(planting.player_level)
            if best:
                logger.info(f"策略选择: {best[0]} (经验效率 {best[4]/best[3]:.4f}/秒)")
                return best[0]
        return planting.preferred_crop

    def _clear_screen(self, rect: tuple, session_id: int | None = None):
        """点击窗口顶部天空区域，关闭残留弹窗/菜单/土地信息

        点击位置：水平居中，垂直 5% 处（天空区域，不会触发任何游戏操作）。
        连续点击 2 次，间隔 0.3 秒等待动画消失。
        """
        if not self.action_executor:
            return

        platform = getattr(self.config.planting, "window_platform", "qq")
        platform_value = platform.value if hasattr(platform, "value") else str(platform)
        if not rect or len(rect) != 4:
            logger.warning("清屏点击跳过: capture rect 不可用")
            return

        cap_left, cap_top, cap_w, cap_h = [int(v) for v in rect]
        x1, y1, crop_w, crop_h = self.window_manager.get_preview_crop_box(
            raw_width=cap_w,
            raw_height=cap_h,
            platform=platform_value,
        )
        sky_x = int(cap_left + x1 + crop_w // 2)
        sky_y = int(cap_top + y1 + max(10, int(crop_h * 0.05)))

        for _ in range(2):
            if self._is_cancel_requested(session_id):
                break
            self.action_executor.click(sky_x, sky_y)
            if self._is_cancel_requested(session_id):
                break
            if not self._sleep_interruptible(0.3, session_id):
                break


    def start(self) -> bool:
        if self._worker_running() or self._executor_running():
            self.log_message.emit("上一轮任务仍在停止中，请稍候再启动")
            return False
        self._engine_mode = self._resolve_engine_mode(self.config)
        self.config.executor.enabled = self._engine_mode == EngineMode.EXECUTOR
        self._switch_session(cancelled=False)
        self._runtime_failure_count = 0
        self._clear_expected_states()
        self._reset_scene_confirm()
        self._set_runtime_state(RuntimeState.UNKNOWN, "start")
        self.cv_detector.load_templates()
        tpl_count = sum(len(v) for v in self.cv_detector._templates.values())
        if tpl_count == 0:
            self.log_message.emit("未找到模板图片，请先运行模板采集工具")
            return False

        window = self.window_manager.find_window(self.config.window_title_keyword)
        if not window:
            self.log_message.emit("未找到QQ农场窗口，请先打开微信小程序中的QQ农场")
            return False

        pos = getattr(self.config.planting, "window_position", "left_center")
        pos_value = pos.value if hasattr(pos, "value") else str(pos)
        platform = getattr(self.config.planting, "window_platform", "qq")
        platform_value = platform.value if hasattr(platform, "value") else str(platform)
        self.window_manager.resize_window(pos_value, platform_value)
        self._sleep_interruptible(0.5)
        window = self.window_manager.refresh_window_info(self.config.window_title_keyword)
        self.log_message.emit(
            "窗口已调整（整窗外框目标：540x960 + 非客户区增量）-> "
            f"实际外框 {window.width}x{window.height}"
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
        self._init_strategies()
        self.navigator = Navigator(
            cv_detector=self.cv_detector,
            popup_strategy=self.popup,
            capture_fn=self._capture_and_detect,
            cancel_checker=self._is_cancel_requested,
        )
        self.ui_guard = UIGuard(
            self.popup,
            navigator=self.navigator,
            on_level_up=self._on_level_up,
        )

        if self._using_executor_mode():
            self.scheduler.stop()
            self.scheduler.force_state("running")
            self.scheduler.update_runtime_metrics(
                current_task="--",
                current_page="unknown",
                failure_count=self._runtime_failure_count,
                running_tasks=0,
                pending_tasks=0,
                waiting_tasks=0,
                last_result="--",
                last_tick_ms="--",
            )
            self._init_executor()
        else:
            farm_ms = self.config.schedule.farm_check_minutes * 60 * 1000
            friend_ms = self.config.schedule.friend_check_minutes * 60 * 1000
            self.scheduler.start(farm_ms, friend_ms)
            self.scheduler.update_runtime_metrics(
                current_task="farm_main",
                current_page="unknown",
                failure_count=self._runtime_failure_count,
                running_tasks=0,
                pending_tasks=0,
                waiting_tasks=1,
            )

        self.log_message.emit(
            f"Bot已启动({self._engine_mode.value}) - 窗口: {window.title} | 模板: {tpl_count}个"
        )
        return True

    def stop(self):
        self._switch_session(cancelled=True)
        self._clear_expected_states()
        self._reset_scene_confirm()

        if self._using_executor_mode():
            self._stop_executor()
            self.scheduler.force_state("idle")
        else:
            self.scheduler.stop()

        self.scheduler.update_runtime_metrics(
            current_task="--",
            current_page="--",
            failure_count=self._runtime_failure_count,
            running_tasks=0,
            pending_tasks=0,
            waiting_tasks=0,
            last_result="--",
            last_tick_ms="--",
        )
        self.scheduler.set_next_checks(farm_ts=0.0, friend_ts=0.0)

        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            if not self._worker.wait(80):
                logger.debug("停止请求已发出，后台线程即将退出")
        if self._worker and not self._worker.isRunning():
            self._worker = None
        self.log_message.emit("Bot已停止")

    def pause(self):
        if self._using_executor_mode():
            if self._task_executor:
                self._task_executor.pause()
            self.scheduler.force_state("paused")
            return

        self._switch_session(cancelled=True)
        self._clear_expected_states()
        self._reset_scene_confirm()
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
        self.scheduler.pause()

    def resume(self):
        if self._using_executor_mode():
            if self._task_executor:
                self._task_executor.resume()
            self.scheduler.force_state("running")
            return

        self._switch_session(cancelled=False)
        self._clear_expected_states()
        self._reset_scene_confirm()
        self.scheduler.resume()

    def run_once(self):
        if self._using_executor_mode():
            if not self._task_executor or not self._task_executor.is_running():
                self.log_message.emit("执行器未运行，无法立即执行")
                return
            self._task_executor.task_call("farm_main")
            self._task_executor.resume()
            return

        if self._is_cancel_requested():
            self._switch_session(cancelled=False)
        self._on_farm_check()

    def _on_farm_check(self):
        if self._using_executor_mode():
            if self._task_executor:
                self._task_executor.task_call("farm_main")
            return
        if self._is_cancel_requested():
            return
        self._spawn_worker("farm")

    def _on_friend_check(self):
        if self._using_executor_mode():
            if self._task_executor and (self.config.features.auto_steal or self.config.features.auto_help):
                self._task_executor.task_call("friend", force_call=False)
            return
        if self._is_cancel_requested():
            return
        if not self.config.features.auto_steal and not self.config.features.auto_help:
            return
        self._spawn_worker("friend")

    def _on_task_finished(self, session_id: int, result: dict):
        if self._using_executor_mode():
            return
        sender = self.sender()
        if sender is self._worker:
            self._worker = None
        if session_id != self._session_id:
            logger.debug(f"忽略过期任务结果: session={session_id}, current={self._session_id}")
            return
        actions = result.get("actions_done", [])
        if actions:
            self.log_message.emit(f"本轮完成: {', '.join(actions)}")
        if result.get("success", False):
            self._runtime_failure_count = 0
            self.scheduler.update_runtime_metrics(
                failure_count=self._runtime_failure_count,
                current_task="farm_main",
                running_tasks=0,
                pending_tasks=0,
                waiting_tasks=1,
            )
        next_sec = result.get("next_check_seconds", 0)
        if next_sec > 0:
            self.scheduler.set_farm_interval(next_sec)

    def _on_task_error(self, session_id: int, error_msg: str):
        if self._using_executor_mode():
            return
        sender = self.sender()
        if sender is self._worker:
            self._worker = None
        if session_id != self._session_id:
            logger.debug(f"忽略过期任务异常: session={session_id}, current={self._session_id}")
            return
        self._runtime_failure_count += 1
        self.scheduler.update_runtime_metrics(
            failure_count=self._runtime_failure_count,
            current_task="farm_main",
            running_tasks=0,
            pending_tasks=0,
            waiting_tasks=1,
        )
        self.log_message.emit(f"操作异常: {error_msg}")

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
        return rect

    def _crop_preview_image(self, image: PILImage.Image | None) -> PILImage.Image | None:
        """仅用于左侧预览显示：按 nonclient 配置裁掉窗口边框/标题栏。"""
        if image is None:
            return None
        platform = getattr(self.config.planting, "window_platform", "qq")
        platform_value = platform.value if hasattr(platform, "value") else str(platform)
        return self.window_manager.crop_window_image_for_preview(image, platform_value)

    def _capture_and_detect(self, rect: tuple, prefix: str = "farm",
                            categories: list[str] | None = None,
                            save: bool = True
                            ) -> tuple[np.ndarray | None, list[DetectResult], PILImage.Image | None]:
        if save:
            image, _ = self.screen_capture.capture_and_save(rect, prefix)
        else:
            image = self.screen_capture.capture_region(rect)
        if image is None:
            return None, [], None
        preview_image = self._crop_preview_image(image)
        if preview_image is not None:
            self.screenshot_updated.emit(preview_image)
        cv_image = self.cv_detector.pil_to_cv2(image)

        if categories is not None:
            detections = []
            for cat in categories:
                detections += self.cv_detector.detect_category(cv_image, cat, threshold=0.8)
            detections = self.cv_detector._nms(detections, iou_threshold=0.5)
        else:
            detections = []
            for cat in self.cv_detector._templates:
                if cat in ("seed",):
                    continue
                if cat == "land":
                    thresh = 0.89
                elif cat == "button":
                    thresh = 0.8
                else:
                    thresh = 0.8
                detections += self.cv_detector.detect_category(cv_image, cat, threshold=thresh)
            detections = [d for d in detections
                          if d.name != "btn_shop_close"
                          and not (d.name == "btn_expand" and d.confidence < 0.85)]

        return cv_image, detections, image

    def _emit_annotated(self, cv_image: np.ndarray, detections: list[DetectResult]):
        if detections:
            annotated = self.cv_detector.draw_results(cv_image, detections)
            annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            annotated_pil = PILImage.fromarray(annotated_rgb)
            preview_annotated = self._crop_preview_image(annotated_pil)
            if preview_annotated is not None:
                self.detection_result.emit(preview_annotated)

    def _record_stat(self, action_type: str):
        type_map = {
            ActionType.HARVEST: "harvest", ActionType.PLANT: "plant",
            ActionType.WATER: "water", ActionType.WEED: "weed",
            ActionType.BUG: "bug", ActionType.STEAL: "steal",
            ActionType.SELL: "sell",
        }
        stat_key = type_map.get(action_type)
        if stat_key:
            self.scheduler.record_action(stat_key)

    def _handle_main_scene(
        self,
        rect: tuple,
        detections: list[DetectResult],
        features: dict,
        _result: dict,
        sold_this_round: bool,
    ) -> tuple[StrategyResult, bool]:
        out = StrategyResult()

        if not out.action and features.get("auto_harvest", True):
            out = StrategyResult.from_value(self.harvest.try_harvest(detections))

        if not out.action:
            out = StrategyResult.from_value(self.maintain.try_maintain(detections, features))

        if not out.action and features.get("auto_plant", True):
            out = StrategyResult.from_value(self.plant.plant_all(rect, self._resolve_crop_name()))

        if not out.action and features.get("auto_upgrade", True):
            out = StrategyResult.from_value(self.expand.try_expand(rect, detections))

        if (not out.action and features.get("auto_sell", True) and not sold_this_round):
            sa = self.sell.try_sell(rect, detections)
            if sa:
                sold_this_round = True
                out = StrategyResult.from_value(sa)

        if not out.action and features.get("auto_task", True):
            out = StrategyResult.from_value(self.task.try_task(rect, detections))

        if not out.action and features.get("auto_help", True):
            out = StrategyResult.from_value(self.friend.try_friend_help(rect, detections))

        return out, sold_this_round

    def _handle_friend_scene(self, rect: tuple, _result: dict) -> StrategyResult:
        return StrategyResult.from_value(self.friend._help_in_friend_farm(rect))

    def _handle_seed_select_scene(self, detections: list[DetectResult]) -> StrategyResult:
        crop_name = self._resolve_crop_name()
        seed = self.popup.find_by_name(detections, f"seed_{crop_name}")
        if not seed:
            return StrategyResult()
        self.popup.click(seed.x, seed.y, f"播种{crop_name}", ActionType.PLANT)
        self._record_stat(ActionType.PLANT)
        return StrategyResult.from_value(f"播种{crop_name}")

    def _on_level_up(self):
        self.config.planting.player_level += 1
        self.config.save()
        new_level = self.config.planting.player_level
        self.log_message.emit(f"升级! Lv.{new_level - 1} → Lv.{new_level}")
        self.log_message.emit(f"当前种植: {self._resolve_crop_name()}")

    def _handle_level_up_scene(self, rect: tuple, detections: list[DetectResult]) -> StrategyResult:
        if self.ui_guard:
            return StrategyResult.from_value(
                self.ui_guard.handle_global_popups(rect, Scene.LEVEL_UP, detections)
            )
        out = StrategyResult.from_value(self.popup.handle_popup(detections))
        self._on_level_up()
        return out

    def _handle_popup_scene(self, rect: tuple, detections: list[DetectResult]) -> StrategyResult:
        if self.ui_guard:
            return StrategyResult.from_value(
                self.ui_guard.handle_global_popups(rect, Scene.POPUP, detections)
            )
        return StrategyResult.from_value(self.popup.handle_popup(detections))

    def _handle_buy_confirm_scene(self, rect: tuple, detections: list[DetectResult]) -> StrategyResult:
        if self.ui_guard:
            return StrategyResult.from_value(
                self.ui_guard.handle_global_popups(rect, Scene.BUY_CONFIRM, detections)
            )
        return StrategyResult.from_value(self.popup.handle_popup(detections))

    def _handle_shop_scene(self, rect: tuple, detections: list[DetectResult]) -> StrategyResult:
        if self.ui_guard:
            return StrategyResult.from_value(
                self.ui_guard.handle_global_popups(rect, Scene.SHOP_PAGE, detections)
            )
        self.popup.close_shop(rect)
        return StrategyResult.from_value("关闭商店")

    def _dispatch_scene_action(
        self,
        scene: Scene,
        rect: tuple,
        detections: list[DetectResult],
        features: dict,
        result: dict,
        sold_this_round: bool,
    ) -> tuple[StrategyResult, bool]:
        out = StrategyResult()

        if scene == Scene.LEVEL_UP:
            out = self._handle_level_up_scene(rect, detections)
            return out, sold_this_round

        if scene == Scene.POPUP:
            return self._handle_popup_scene(rect, detections), sold_this_round

        if scene == Scene.BUY_CONFIRM:
            return self._handle_buy_confirm_scene(rect, detections), sold_this_round

        if scene == Scene.SHOP_PAGE:
            return self._handle_shop_scene(rect, detections), sold_this_round

        if scene == Scene.PLOT_MENU:
            out = StrategyResult.from_value(self.popup.handle_popup(detections))
            return out, sold_this_round

        if scene == Scene.FARM_OVERVIEW:
            return self._handle_main_scene(
                rect=rect,
                detections=detections,
                features=features,
                result=result,
                sold_this_round=sold_this_round,
            )

        if scene == Scene.FRIEND_FARM:
            return self._handle_friend_scene(rect, result), sold_this_round

        if scene == Scene.SEED_SELECT:
            return self._handle_seed_select_scene(detections), sold_this_round

        if scene == Scene.UNKNOWN:
            recovered = False
            if self.navigator:
                recovered = self.navigator.goto(
                    rect=rect,
                    target=PageId.MAIN,
                    timeout=1.2,
                    confirm_wait=0.15,
                )
            if recovered:
                return StrategyResult.from_value("导航回主界面"), sold_this_round
            self.popup.click_blank(rect)
            return StrategyResult.from_value("点击空白处"), sold_this_round

        return out, sold_this_round

    def _categories_for_tick(self) -> list[str] | None:
        if self._runtime_state in (RuntimeState.BUY_CONFIRM, RuntimeState.POPUP, RuntimeState.SHOP):
            return ["button"]
        return None


    # ============================================================
    # 主循环
    # ============================================================

    def check_farm(self, session_id: int | None = None) -> dict:
        result = {"success": False, "actions_done": [], "next_check_seconds": 5}
        if self._is_cancel_requested(session_id):
            result["message"] = "停止中"
            return result
        features = self.config.features.model_dump()

        rect = self._prepare_window()
        if not rect:
            result["message"] = "窗口未找到"
            return result

        # 清屏：点击天空区域关闭残留弹窗/菜单
        self._clear_screen(rect, session_id)
        if self.navigator:
            self.navigator.ensure(rect, PageId.MAIN, timeout=1.2, confirm_wait=0.15)

        idle_rounds = 0
        max_idle = 3
        sold_this_round = False
        tick = 0
        transition_budget = max(30, int(self.config.safety.max_actions_per_round) * 3)

        while tick < transition_budget:
            if self._is_cancel_requested(session_id) or self.popup.stopped:
                logger.info("收到停止/暂停信号，中断当前操作")
                break

            tick_start = time.perf_counter()
            detect_start = time.perf_counter()
            cv_image, detections, _ = self._capture_and_detect(
                rect,
                save=False,
                categories=self._categories_for_tick(),
            )
            detect_ms = (time.perf_counter() - detect_start) * 1000.0
            if cv_image is None:
                result["message"] = "截屏失败"
                break

            raw_scene = identify_scene(detections, self.cv_detector, cv_image)
            scene = self._confirm_scene(raw_scene)
            if scene is None:
                logger.debug(
                    f"场景候选待确认: raw={raw_scene.value}, hits={self._scene_tracker.hits}"
                )
                if not self._sleep_interruptible(0.12, session_id):
                    break
                continue
            tick += 1

            self._set_runtime_state(self._scene_to_runtime_state(scene), "scene")
            self.scheduler.update_runtime_metrics(
                current_page=scene.value,
                current_task="farm_main",
                failure_count=self._runtime_failure_count,
            )
            if not self._verify_expected_runtime():
                self.popup.click_blank(rect)
                if not self._sleep_interruptible(0.2, session_id):
                    break
                continue
            det_summary = ", ".join(f"{d.name}({d.confidence:.0%})" for d in detections[:6])
            logger.info(f"[tick={tick}] 场景={scene.value} | {det_summary}")
            self._emit_annotated(cv_image, detections)
            action_start = time.perf_counter()
            dispatch_result, sold_this_round = self._dispatch_scene_action(
                scene=scene,
                rect=rect,
                detections=detections,
                features=features,
                result=result,
                sold_this_round=sold_this_round,
            )
            action_ms = (time.perf_counter() - action_start) * 1000.0
            tick_ms = (time.perf_counter() - tick_start) * 1000.0

            # ---- 结果处理 ----
            result["actions_done"].extend(dispatch_result.actions)
            action_desc = dispatch_result.action
            logger.info(
                "task=farm_main page={} action={} detect_ms={:.1f} action_ms={:.1f} tick_ms={:.1f}",
                scene.value,
                action_desc or "none",
                detect_ms,
                action_ms,
                tick_ms,
            )
            self.scheduler.update_runtime_metrics(
                last_result=action_desc or "none",
                last_tick_ms=f"{tick_ms:.1f}ms",
            )
            if action_desc:
                idle_rounds = 0
            else:
                idle_rounds += 1
                if idle_rounds == 1:
                    self.popup.click_blank(rect)
                elif idle_rounds >= max_idle:
                    break

            if not self._sleep_interruptible(0.3, session_id):
                break
        else:
            logger.info(f"达到页面跳转预算上限: {transition_budget}，结束本轮")

        # 设置下次检查间隔
        # 有播种操作 → 5分钟后检查维护（除虫/除草/浇水）
        # 无播种操作 → 30秒后再检查（可能有新状态）
        has_planted = any("播种" in a for a in result.get("actions_done", []))
        if has_planted:
            interval = self.config.schedule.farm_check_minutes * 60
            result["next_check_seconds"] = interval
            crop_name = self._resolve_crop_name()
            crop = get_crop_by_name(crop_name)
            if crop:
                grow_time = crop[3]
                logger.info(f"已播种{crop_name}，{format_grow_time(grow_time)}后成熟，每{self.config.schedule.farm_check_minutes}分钟检查维护")
        else:
            result["next_check_seconds"] = 30

        result["success"] = True
        self.screen_capture.cleanup_old_screenshots(0)
        return result

    def check_friends(self, session_id: int | None = None) -> dict:
        friend_interval = max(60, int(self.config.schedule.friend_check_minutes) * 60)
        if self._is_cancel_requested(session_id):
            return {"success": False, "actions_done": [], "next_check_seconds": friend_interval, "message": "停止中"}
        result = {"success": True, "actions_done": [], "next_check_seconds": friend_interval}
        logger.info("好友巡查功能开发中...")
        return result
