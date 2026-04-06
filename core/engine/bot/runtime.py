"""Bot 生命周期与运行态控制逻辑。"""

from __future__ import annotations

import time

from loguru import logger

from core.base.button import Button
from core.platform.action_executor import ActionExecutor
from core.platform.device import Device
from core.ui.assets import ASSET_NAME_TO_CONST
from core.ui.page import (
    GOTO_MAIN,
)
from core.ui.ui import UI
from models.config import AppConfig, PlantMode, RunMode, resolve_effective_run_mode
from models.game_data import get_best_crop_for_level
from utils.template_paths import normalize_template_platform


class BotRuntimeMixin:
    """Bot 生命周期与运行态控制逻辑。"""

    def _get_effective_run_mode(self, *, emit_hint: bool = False) -> RunMode:
        """返回生效运行模式（仅 QQ 支持后台模式）。"""
        mode = resolve_effective_run_mode(self.config.safety.run_mode, self.config.planting.window_platform)
        if emit_hint and mode != self.config.safety.run_mode:
            self.log_message.emit('提示：仅QQ平台支持后台模式，已自动使用前台模式')
        return mode

    def update_config(self, config: AppConfig):
        """更新配置并将变更同步到执行器。"""
        self.config = config
        platform = getattr(config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        Button.set_template_platform(normalize_template_platform(platform_value))
        effective_mode = self._get_effective_run_mode(emit_hint=True)
        if self.action_executor is not None:
            self.action_executor.update_run_mode(effective_mode)
        if self.screen_capture is not None:
            self.screen_capture.update_run_mode(effective_mode)
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

    def _clear_screen(self, rect: tuple):
        """通过 GOTO_MAIN 连续点击 2 次，尽量回到稳定主界面。"""
        if not self.action_executor:
            return

        goto_x, goto_y = GOTO_MAIN.location
        for _ in range(2):
            if self.device:
                self.device.click_point(goto_x, goto_y, desc='goto_main')
            time.sleep(0.3)

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
        if self.device is not None:
            rect = getattr(self.device, 'rect', None)
        return self.resolve_capture_point(int(x), int(y), rect=rect)

    def _resolve_goto_main_point(self, rect: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
        """计算“回主按钮”在当前截图中的点击坐标。"""
        return self.resolve_capture_point(*GOTO_MAIN.location, rect=rect)

    def start(self) -> bool:
        """启动当前模块的主流程。"""
        if self._executor_running():
            self.log_message.emit('上一轮任务仍在停止中，请稍候再启动')
            return False
        self._fatal_error_stop_requested = False
        self._task_error_delay_overrides.clear()
        self._task_error_type_names.clear()
        # [启动阶段] 重置运行会话与计数器。
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
        time.sleep(0.5)
        window = self.window_manager.refresh_window_info(self.config.window_title_keyword)
        self.log_message.emit(
            f'窗口已调整（整窗外框目标：540x960 + 非客户区增量）-> 实际外框 {window.width}x{window.height}'
        )

        rect = self.window_manager.get_capture_rect()
        if not rect:
            rect = (window.left, window.top, window.width, window.height)
        self.action_executor = ActionExecutor(
            window_rect=rect,
            hwnd=window.hwnd,
            run_mode=self._get_effective_run_mode(emit_hint=True),
            delay_min=self.config.safety.random_delay_min,
            delay_max=self.config.safety.random_delay_max,
            click_offset=self.config.safety.click_offset_range,
        )
        if self.screen_capture is not None:
            self.screen_capture.update_run_mode(self._get_effective_run_mode())
        # [适配层阶段] 构建设备/UI/任务对象，供执行器回调使用。
        self.device = Device(engine=self)
        self.device.set_rect(rect)
        self.ui = UI(
            config=self.config,
            detector=self.cv_detector,
            device=self.device,
            crop_name_resolver=self._resolve_crop_name_quiet,
        )
        # 启动后立即推送一帧预览，避免在“无可执行任务”时左侧截图空白。
        try:
            self.device.screenshot(rect=rect, save=False)
        except Exception as exc:
            logger.debug(f'startup screenshot failed: {exc}')

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
        self._fatal_error_stop_requested = False
        self._stop_executor()
        self.ui = None
        self.device = None
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
        """立即触发一次 `main` 任务执行。"""
        if not self._task_executor or not self._task_executor.is_running():
            self.log_message.emit('执行器未运行，无法立即执行')
            return
        self._task_executor.task_call('main')
        self._task_executor.resume()
