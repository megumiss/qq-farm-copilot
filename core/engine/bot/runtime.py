"""Bot 生命周期与运行态控制逻辑。"""

from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loguru import logger

from core.base.button import Button
from core.platform.action_executor import ActionExecutor
from core.platform.device import Device
from core.platform.window_manager import WindowInfo
from core.ui.assets import ASSET_NAME_TO_CONST
from core.ui.page import (
    GOTO_MAIN,
    page_main,
)
from core.ui.ui import UI
from models.config import AppConfig, PlantMode, RunMode, resolve_effective_run_mode
from models.game_data import get_best_crop_for_level, get_latest_crop_for_level
from utils.template_paths import normalize_template_platform

if TYPE_CHECKING:
    from core.engine.bot.local_engine import LocalBotEngine


class BotRuntimeMixin:
    """Bot 生命周期与运行态控制逻辑。"""

    _WINDOW_LAUNCH_WAIT_TIMEOUT_SECONDS = 15.0
    _WINDOW_LAUNCH_POLL_INTERVAL_SECONDS = 1.0
    _WINDOW_LAUNCH_COOLDOWN_SECONDS = 15.0
    _WINDOW_CLOSE_WAIT_TIMEOUT_SECONDS = 15.0
    _WINDOW_CLOSE_POLL_INTERVAL_SECONDS = 0.2
    _STARTUP_UI_STABILIZE_TIMEOUT_SECONDS = 90.0
    _STARTUP_UI_STEP_SLEEP_SECONDS = 0.5

    def _engine(self) -> LocalBotEngine:
        """返回完整引擎视图，便于 IDE 识别跨 Mixin 方法。"""
        return cast('LocalBotEngine', self)

    def _wait_window_capture_stable(self, timeout: float = 0.5, interval: float = 0.04) -> None:
        """等待窗口截图区域稳定，避免固定睡眠造成的启动额外耗时。"""
        deadline = time.perf_counter() + max(0.05, float(timeout))
        last_rect: tuple[int, int, int, int] | None = None
        stable_hits = 0

        while time.perf_counter() < deadline:
            rect = self.window_manager.get_capture_rect()
            if rect and rect == last_rect:
                stable_hits += 1
                if stable_hits >= 2:
                    return
            else:
                stable_hits = 0
                last_rect = rect
            time.sleep(max(0.01, float(interval)))

    def _get_effective_run_mode(self, *, emit_hint: bool = False) -> RunMode:
        """返回生效运行模式。"""
        _ = emit_hint
        return resolve_effective_run_mode(self.config.safety.run_mode, self.config.planting.window_platform)

    def update_config(self, config: AppConfig):
        """更新配置并将变更同步到执行器。"""
        self.config = config
        engine = self._engine()
        platform_value = config.planting.window_platform.value
        normalized_platform = normalize_template_platform(platform_value)
        Button.set_template_platform(normalized_platform)
        if self.cv_detector is not None:
            self.cv_detector.set_template_platform(normalized_platform)
        effective_mode = self._get_effective_run_mode(emit_hint=True)
        if self.action_executor is not None:
            self.action_executor.update_run_mode(effective_mode)
        if self.screen_capture is not None:
            self.screen_capture.update_run_mode(effective_mode)
        engine._sync_executor_tasks_from_config()
        engine._sync_recovery_policy_from_config()

    def _resolve_crop_name_quiet(self) -> str:
        """根据策略决定种植作物（静默版本，不打印日志）。"""
        planting = self.config.planting
        if planting.strategy == PlantMode.BEST_EXP_RATE:
            best = get_best_crop_for_level(planting.player_level)
            if best:
                planting.preferred_crop = best[0]
        elif planting.strategy == PlantMode.LATEST_LEVEL:
            latest = get_latest_crop_for_level(planting.player_level)
            if latest:
                planting.preferred_crop = latest[0]
        return planting.preferred_crop

    def _resolve_crop_name(self) -> str:
        """解析并返回当前播种作物。"""
        crop_name = self._resolve_crop_name_quiet()
        if self.config.planting.strategy == PlantMode.BEST_EXP_RATE:
            best = get_best_crop_for_level(self.config.planting.player_level)
            if best:
                logger.info(f'策略自动最优: {best[0]} (经验效率 {best[4] / best[3]:.4f}/秒)')
        elif self.config.planting.strategy == PlantMode.LATEST_LEVEL:
            latest = get_latest_crop_for_level(self.config.planting.player_level)
            if latest:
                logger.info(f'策略自动最新: {latest[0]} (解锁等级 Lv{latest[2]})')
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

        platform_value = self.config.planting.window_platform.value
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

    def _window_lookup_params(self) -> tuple[str, str, str]:
        """返回当前查窗参数。"""
        return (
            str(self.config.window_title_keyword or ''),
            str(self.config.window_select_rule or 'auto'),
            self.config.planting.window_platform.value,
        )

    def _list_platform_windows_silent(self) -> list[WindowInfo]:
        """列出按标题 + 平台过滤后的候选窗口。"""
        title_keyword, select_rule, platform_value = self._window_lookup_params()
        windows = self.window_manager.list_windows(title_keyword)
        if not windows:
            return []

        filtered = [
            info
            for info in windows
            if self.window_manager._matches_platform(str(info.process_name or ''), platform_value)
        ]
        _ = select_rule
        return filtered

    @staticmethod
    def _resolve_select_index_silent(select_rule: str, total: int) -> int:
        """静默解析 `index:N` 规则，非法输入回退到 `0`。"""
        if total <= 0:
            return 0
        text = str(select_rule or 'auto').strip().lower()
        if not text or text == 'auto':
            return 0
        if text.startswith('index:'):
            suffix = text.split(':', 1)[1]
            try:
                idx = int(suffix)
            except Exception:
                return 0
            if idx < 0:
                return 0
            return min(idx, total - 1)
        return 0

    def _find_window_silent(
        self,
        *,
        baseline_hwnds: set[int] | None = None,
        prefer_new_hwnd: bool = False,
        allow_fallback_existing: bool = True,
    ) -> WindowInfo | None:
        """静默查找目标窗口（支持 `hwnd` 差分优先匹配）。"""
        _title_keyword, select_rule, _platform_value = self._window_lookup_params()
        windows = self._list_platform_windows_silent()
        if not windows:
            return None

        baseline = set(int(v) for v in (baseline_hwnds or set()) if int(v) > 0)
        if prefer_new_hwnd and baseline:
            new_windows = [info for info in windows if int(info.hwnd) not in baseline]
            if new_windows:
                matched = new_windows[0]
                self.window_manager._cached_window = matched
                return matched
            if not allow_fallback_existing:
                return None

        rule_text = str(select_rule or '').strip().lower()
        if rule_text in {'', 'auto'}:
            matched = windows[0]
        else:
            target_index = self._resolve_select_index_silent(select_rule, len(windows))
            matched = windows[target_index]

        self.window_manager._cached_window = matched
        return matched

    def _resolve_window_shortcut_path(self) -> Path | None:
        """读取并规范化窗口快捷方式路径。"""
        raw = str(self.config.window_shortcut_path or '').strip().strip('"')
        if not raw:
            return None
        expanded = os.path.expandvars(raw)
        try:
            return Path(expanded).expanduser().resolve()
        except Exception:
            return Path(expanded).expanduser()

    def _validate_window_shortcut_for_recovery(self) -> tuple[bool, str]:
        """校验异常恢复所需的窗口快捷方式是否有效。"""
        shortcut_path = self._resolve_window_shortcut_path()
        if shortcut_path is None:
            return False, '未配置快捷方式路径'
        if shortcut_path.suffix.lower() != '.lnk':
            return False, '快捷方式路径不是 .lnk 文件'
        if not shortcut_path.is_file():
            return False, '快捷方式文件不存在'
        return True, ''

    def _try_launch_window_by_shortcut(
        self,
        *,
        wait_timeout: float,
        poll_interval: float,
        emit_hint: bool,
        force_launch: bool = False,
    ) -> tuple[WindowInfo | None, bool]:
        """使用快捷方式启动小程序并等待窗口出现。"""
        shortcut_path = self._resolve_window_shortcut_path()
        if shortcut_path is None:
            return None, False

        shortcut_text = str(shortcut_path)
        if shortcut_path.suffix.lower() != '.lnk':
            logger.warning(f'窗口快捷方式路径不是 .lnk: {shortcut_text}')
            if emit_hint:
                logger.warning('快捷方式路径无效：仅支持 .lnk 文件')
            return None, False
        if not shortcut_path.is_file():
            logger.warning(f'窗口快捷方式不存在: {shortcut_text}')
            if emit_hint:
                logger.warning('快捷方式文件不存在，请在设置中重新选择')
            return None, False

        baseline_hwnds = {int(info.hwnd) for info in self._list_platform_windows_silent() if int(info.hwnd) > 0}

        now = time.monotonic()
        last_launch = float(getattr(self, '_last_window_shortcut_launch_at', 0.0) or 0.0)
        cooldown = max(0.0, float(self._WINDOW_LAUNCH_COOLDOWN_SECONDS))
        launched_recently = (not force_launch) and last_launch > 0 and (now - last_launch) < cooldown
        launched_this_round = False
        if not launched_recently:
            try:
                if emit_hint:
                    logger.info(f'未找到窗口，尝试通过快捷方式启动: {shortcut_text}')
                os.startfile(shortcut_text)
                setattr(self, '_last_window_shortcut_launch_at', now)
                launched_this_round = True
                logger.info(f'已触发快捷方式启动: {shortcut_text}')
            except Exception as exc:
                logger.error(f'快捷方式启动失败: {shortcut_text}, {exc}')
                if emit_hint:
                    logger.error(f'快捷方式启动失败: {exc}')
                return None, True
        else:
            logger.info('窗口快捷方式刚触发过，跳过重复启动并继续等待窗口出现')

        deadline = time.perf_counter() + max(0.2, float(wait_timeout))
        interval = max(0.1, float(poll_interval))
        launch_wait_start = time.perf_counter()
        last_wait_log_at = 0.0
        while time.perf_counter() < deadline:
            now_perf = time.perf_counter()
            if emit_hint and (last_wait_log_at <= 0.0 or (now_perf - last_wait_log_at) >= 3.0):
                elapsed = max(0.0, now_perf - launch_wait_start)
                remain = max(0.0, deadline - now_perf)
                logger.info(f'快捷方式启动后等待窗口中: elapsed={elapsed:.1f}s, remain={remain:.1f}s')
                last_wait_log_at = now_perf
            window = self._find_window_silent(
                baseline_hwnds=baseline_hwnds,
                prefer_new_hwnd=True,
                allow_fallback_existing=launched_recently,
            )
            if window is not None:
                if emit_hint and launched_this_round:
                    logger.info(f'已检测到窗口: {window.title}')
                return window, (launched_this_round or launched_recently)
            time.sleep(interval)
        if emit_hint:
            logger.warning('快捷方式启动后等待窗口超时')
        return None, (launched_this_round or launched_recently)

    @staticmethod
    def _is_window_alive(hwnd: int) -> bool:
        """判断窗口句柄是否仍然有效。"""
        target_hwnd = int(hwnd or 0)
        if target_hwnd <= 0:
            return False
        try:
            return bool(ctypes.windll.user32.IsWindow(target_hwnd))
        except Exception:
            return False

    def _close_window_by_hwnd(
        self,
        hwnd: int,
        *,
        wait_timeout: float | None = None,
        poll_interval: float | None = None,
    ) -> bool:
        """向目标窗口发送 `WM_CLOSE`，并等待窗口退出。"""
        target_hwnd = int(hwnd or 0)
        if target_hwnd <= 0:
            return True

        if not self._is_window_alive(target_hwnd):
            return True

        try:
            ctypes.windll.user32.PostMessageW(target_hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception as exc:
            logger.warning(f'关闭窗口失败: hwnd=0x{target_hwnd:X}, {exc}')
            return False

        deadline = time.perf_counter() + max(
            0.3,
            float(self._WINDOW_CLOSE_WAIT_TIMEOUT_SECONDS if wait_timeout is None else wait_timeout),
        )
        interval = max(
            0.05,
            float(self._WINDOW_CLOSE_POLL_INTERVAL_SECONDS if poll_interval is None else poll_interval),
        )
        while time.perf_counter() < deadline:
            if not self._is_window_alive(target_hwnd):
                if self.window_manager._cached_window and int(self.window_manager._cached_window.hwnd) == target_hwnd:
                    self.window_manager._cached_window = None
                return True
            time.sleep(interval)

        logger.warning(f'关闭窗口超时: hwnd=0x{target_hwnd:X}')
        return False

    def _apply_window_runtime_context(self, window: WindowInfo) -> tuple[int, int, int, int]:
        """将当前窗口同步到 action/device，并返回可用截图区域。"""
        rect = self.window_manager.get_capture_rect()
        if not rect:
            rect = (window.left, window.top, window.width, window.height)
        if self.action_executor is not None:
            self.action_executor.update_window_rect(rect)
            self.action_executor.update_window_handle(window.hwnd)
        if self.device is not None:
            self.device.set_rect(rect)
        return rect

    def _initialize_window_after_launch(
        self,
        *,
        window: WindowInfo,
        emit_hint: bool,
        reason: str,
    ) -> tuple[WindowInfo | None, tuple[int, int, int, int] | None]:
        """窗口拉起后的统一初始化：尺寸校准 + 进入主页面 + 运行态同步。"""
        if emit_hint:
            logger.info(f'{reason}，执行窗口初始化...')

        pos_value = self.config.planting.window_position.value
        platform_value = self.config.planting.window_platform.value
        self.window_manager.resize_window(pos_value, platform_value)
        self._wait_window_capture_stable(timeout=0.5, interval=0.04)

        refreshed = self.window_manager.refresh_cached_window_info() or self._find_window_silent()
        if refreshed is None:
            logger.error('窗口初始化失败: 窗口几何刷新失败')
            if emit_hint:
                logger.error('窗口初始化失败：窗口刷新失败')
            return None, None

        rect = self._apply_window_runtime_context(refreshed)

        if self.ui is not None and not self._stabilize_startup_ui():
            logger.error('窗口初始化失败: 启动画面等待超时')
            if emit_hint:
                logger.error('窗口初始化失败：未能进入主页面')
            return None, None

        refreshed = self.window_manager.refresh_cached_window_info() or refreshed
        rect = self._apply_window_runtime_context(refreshed)
        return refreshed, rect

    def recover_after_login_again(self, *, task_name: str) -> bool:
        """处理“重新登录”点击后的恢复：从等待加载开始收敛回主页面。

        Args:
            task_name: 触发登录恢复的任务名，用于日志上下文。

        Returns:
            `True` 表示恢复成功并回到主页面；否则返回 `False`。
        """
        logger.info(f'[{task_name}] 检测到重新登录，开始等待加载并恢复主页面...')
        window, _launched = self._resolve_target_window(
            allow_shortcut_launch=True,
            wait_timeout=self._WINDOW_LAUNCH_WAIT_TIMEOUT_SECONDS,
            poll_interval=self._WINDOW_LAUNCH_POLL_INTERVAL_SECONDS,
            emit_hint=False,
        )
        if window is None:
            logger.error(f'[{task_name}] 重新登录恢复失败: 未找到目标窗口')
            return False

        self._apply_window_runtime_context(window)
        if not self._stabilize_startup_ui():
            logger.error(f'[{task_name}] 重新登录恢复失败: 启动超时')
            return False

        logger.info(f'[{task_name}] 重新登录恢复成功: 已回到主页面')
        return True

    def _restart_target_window_for_recovery(self, *, task_name: str, attempt: int, limit: int, err_type: str) -> bool:
        """任务异常恢复：重启小程序窗口并等待重新进入主页面。

        Args:
            task_name: 当前任务名。
            attempt: 当前重启尝试次数（从 1 开始）。
            limit: 最大允许重启次数。
            err_type: 原始异常类型名（用于日志）。

        Returns:
            `True` 表示重启并完成初始化；`False` 表示恢复失败。
        """
        window = self.window_manager.refresh_cached_window_info() or self._find_window_silent()
        if window is not None:
            hwnd = int(window.hwnd or 0)
            if hwnd > 0:
                logger.warning(f'[{task_name}] 异常恢复: 正在关闭窗口 hwnd=0x{hwnd:X}')
                if not self._close_window_by_hwnd(hwnd):
                    logger.error(f'异常恢复失败：关闭窗口超时（{attempt}/{limit}）')
                    return False

        window, launched = self._try_launch_window_by_shortcut(
            wait_timeout=self._WINDOW_LAUNCH_WAIT_TIMEOUT_SECONDS,
            poll_interval=self._WINDOW_LAUNCH_POLL_INTERVAL_SECONDS,
            emit_hint=False,
            force_launch=True,
        )
        if window is None:
            logger.error(f'[{task_name}] 异常恢复失败: 快捷方式拉起后未找到窗口')
            logger.error(f'异常恢复失败：重启窗口未成功（{attempt}/{limit}）')
            return False
        if launched:
            logger.info(f'[{task_name}] 异常恢复: 已重新拉起窗口 hwnd=0x{int(window.hwnd):X}')

        initialized_window, _rect = self._initialize_window_after_launch(
            window=window,
            emit_hint=False,
            reason=f'[{task_name}] 异常恢复重启成功',
        )
        if initialized_window is None:
            logger.error(f'异常恢复失败：未能回到主页面（{attempt}/{limit}）')
            return False

        logger.info(f'[{task_name}] 异常恢复完成: {err_type} | 重启窗口 {attempt}/{limit}')
        logger.info(f'异常恢复完成：已重启窗口并回到主页面（{attempt}/{limit}）')
        return True

    def _resolve_target_window(
        self,
        *,
        allow_shortcut_launch: bool,
        wait_timeout: float = _WINDOW_LAUNCH_WAIT_TIMEOUT_SECONDS,
        poll_interval: float = _WINDOW_LAUNCH_POLL_INTERVAL_SECONDS,
        emit_hint: bool = False,
    ) -> tuple[WindowInfo | None, bool]:
        """查找目标窗口；未命中时可选通过快捷方式自动拉起。

        Args:
            allow_shortcut_launch: 未找到窗口时是否允许触发快捷方式启动。
            wait_timeout: 通过快捷方式拉起后的最大等待时长（秒）。
            poll_interval: 等待窗口出现时的轮询间隔（秒）。
            emit_hint: 是否向 UI 输出启动提示文案。

        Returns:
            `(window, launched)`：
            - `window`: 命中的窗口对象，未命中时为 `None`；
            - `launched`: 本轮是否执行过/沿用了快捷方式拉起流程。
        """
        window = self._find_window_silent()
        if window is not None:
            return window, False
        if not allow_shortcut_launch:
            return None, False
        return self._try_launch_window_by_shortcut(
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
            emit_hint=emit_hint,
        )

    def _stabilize_startup_ui(self) -> bool:
        """NIKKE 风格启动状态机：等待启动画面完成并收敛到主页。"""
        if self.ui is None:
            return False

        logger.info('启动后状态检查中：等待加载完成并进入主页面...')
        recovery_cfg = self.config.recovery
        stabilize_timeout = float(recovery_cfg.startup_stabilize_timeout_seconds)
        retry_step_sleep = float(recovery_cfg.startup_retry_step_sleep_seconds)
        deadline = time.perf_counter() + max(5.0, stabilize_timeout)
        step_sleep = max(0.1, retry_step_sleep)
        last_error = 'startup_state_unresolved'
        retry_count = 0
        loop_count = 0
        last_progress_log_at = 0.0
        pos_value = self.config.planting.window_position.value
        platform_value = self.config.planting.window_platform.value
        cached_window = self.window_manager.refresh_cached_window_info() or self._find_window_silent()
        last_window_hwnd = int(getattr(cached_window, 'hwnd', 0) or 0)

        while time.perf_counter() < deadline:
            loop_count += 1
            now_perf = time.perf_counter()
            remain = max(0.2, deadline - now_perf)
            if loop_count == 1 or (now_perf - last_progress_log_at) >= 3.0:
                logger.info(f'启动检查中: remain={remain:.1f}s, last_error={last_error}')
                last_progress_log_at = now_perf
            wait_timeout = min(float(self._WINDOW_LAUNCH_WAIT_TIMEOUT_SECONDS), max(1.0, remain))
            window, _launched = self._resolve_target_window(
                allow_shortcut_launch=True,
                wait_timeout=wait_timeout,
                poll_interval=self._WINDOW_LAUNCH_POLL_INTERVAL_SECONDS,
                emit_hint=False,
            )
            if window is None:
                last_error = 'window_not_found'
                time.sleep(step_sleep)
                continue

            current_hwnd = int(getattr(window, 'hwnd', 0) or 0)
            if current_hwnd > 0 and current_hwnd != last_window_hwnd:
                logger.info(f'启动窗口句柄变化: 0x{last_window_hwnd:X} -> 0x{current_hwnd:X}，重新校准窗口尺寸')
                self.window_manager.resize_window(pos_value, platform_value)
                self._wait_window_capture_stable(timeout=0.5, interval=0.04)
                refreshed = self.window_manager.refresh_cached_window_info() or self._find_window_silent()
                if refreshed is not None:
                    window = refreshed
                    current_hwnd = int(getattr(window, 'hwnd', 0) or 0)
            if current_hwnd > 0:
                last_window_hwnd = current_hwnd

            rect = self._apply_window_runtime_context(window)

            try:
                self.ui.ui_wait_loading()
                current_page = self.ui.ui_get_current_page()
                if current_page == page_main:
                    logger.info('启动后页面已稳定到主页面')
                    return True

                page_name = getattr(current_page, 'cn_name', getattr(current_page, 'name', 'unknown'))
                logger.info(f'启动窗口: 当前页面={page_name}，继续执行回主流程')

                handled = False
                if self.ui.ui_additional():
                    handled = True
                if self.ui._click_goto_main(interval=1):
                    handled = True

                if not handled and current_page != page_main:
                    # 兜底一次完整导航；若过程触发异常，由外层接管。
                    self.ui.ui_ensure(page_main, confirm_wait=1)
                    current_page = self.ui.ui_get_current_page()
                    if current_page == page_main:
                        logger.info('启动后页面到达主页面')
                        return True
                last_error = f'page_not_main:{getattr(current_page, "name", "unknown")}'
            except Exception as exc:
                continue_loop, error_text = self._engine()._handle_startup_exception(exc=exc)
                if not continue_loop:
                    return False
                last_error = str(error_text or type(exc).__name__)
                retry_count += 1
                logger.info(
                    f'启动窗口: 检测到启动恢复信号，继续重试启动流程 '
                    f'(retry={retry_count}, loop={loop_count}) | {last_error}'
                )
                time.sleep(step_sleep)
                continue

            time.sleep(step_sleep)

        logger.error(f'启动超时：未能进入主页面 ({last_error})')
        return False

    def start(self) -> bool:
        """启动当前模块的主流程。"""
        engine = self._engine()
        if engine._executor_running():
            logger.warning('上一轮任务仍在停止中，请稍候再启动')
            return False
        self._fatal_error_stop_requested = False
        self._task_exception_retry_counts.clear()
        self._restart_task_payload = None
        engine._sync_recovery_policy_from_config()
        engine._reset_recovery_metrics()
        current_platform_value = self.config.planting.window_platform.value
        normalized_platform = normalize_template_platform(current_platform_value)
        Button.set_template_platform(normalized_platform)
        if self.cv_detector is not None:
            self.cv_detector.set_template_platform(normalized_platform)
        asset_count = len(ASSET_NAME_TO_CONST)
        if asset_count == 0:
            logger.error('未找到 assets 按钮模板，请先运行 button_extract 工具')
            return False

        window, launched_by_shortcut = self._resolve_target_window(
            allow_shortcut_launch=True,
            wait_timeout=self._WINDOW_LAUNCH_WAIT_TIMEOUT_SECONDS,
            poll_interval=self._WINDOW_LAUNCH_POLL_INTERVAL_SECONDS,
            emit_hint=True,
        )
        if not window:
            if str(self.config.window_shortcut_path or '').strip():
                if launched_by_shortcut:
                    logger.error('未找到QQ农场窗口，快捷方式启动后等待超时，请检查快捷方式是否可正常打开小程序')
                else:
                    logger.error('未找到QQ农场窗口，且快捷方式路径无效，请在设置中重新选择 .lnk 文件')
            else:
                logger.error('未找到QQ农场窗口，请先打开QQ农场小程序或配置快捷方式路径')
            return False

        display_metrics = self.window_manager.get_display_metrics(window.hwnd)
        if display_metrics:
            logger.info(
                '屏幕信息: 主屏={screen_width}x{screen_height} 监视器={monitor_width}x{monitor_height} '
                '工作区={work_width}x{work_height} DPI={dpi} 缩放={scale_percent}%'.format(**display_metrics)
            )

        # [窗口阶段] 调整窗口尺寸与位置，确保截图区域稳定。
        pos_value = self.config.planting.window_position.value
        platform_value = self.config.planting.window_platform.value
        self.window_manager.resize_window(pos_value, platform_value)
        self._wait_window_capture_stable(timeout=0.5, interval=0.04)
        # 统一走 _find_window_silent（已包含平台过滤 + index 规则），避免非 auto 分支绕过平台筛选。
        window = self.window_manager.refresh_cached_window_info() or self._find_window_silent()
        if not window:
            logger.error('窗口刷新失败，请检查窗口是否仍存在')
            return False
        logger.info(f'窗口已调整（整窗外框目标：540x960 + 非客户区增量）-> 实际外框 {window.width}x{window.height}')

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
        if not self._stabilize_startup_ui():
            return False
        # 启动后立即推送一帧预览，避免在“无可执行任务”时左侧截图空白。
        try:
            self.device.screenshot(rect=rect, save=False)
        except Exception as exc:
            logger.debug(f'startup screenshot failed: {exc}')

        self.scheduler.stop()
        self.scheduler.force_state('running')
        window_id_text = '--'
        try:
            window_id_text = f'0x{int(getattr(window, "hwnd", 0)):X}'
        except Exception:
            window_id_text = '--'
        self.scheduler.update_runtime_metrics(
            current_task='--',
            next_task='--',
            next_run='--',
            current_platform=str(current_platform_value or '--'),
            window_id=window_id_text,
            running_tasks=0,
            pending_tasks=0,
            waiting_tasks=0,
            recovery_total=self._recovery_total_count,
            recovery_last_error=self._recovery_last_error,
            recovery_last_action=self._recovery_last_action,
            recovery_last_outcome=self._recovery_last_outcome,
            recovery_last_task=self._recovery_last_task,
        )
        engine._init_executor()

        logger.info(f'Bot已启动(executor) - 窗口: {window.title} | assets: {asset_count}个')
        return True

    def stop(self):
        """停止当前模块并释放运行状态。"""
        engine = self._engine()
        self._fatal_error_stop_requested = False
        self._restart_task_payload = None
        if not engine._stop_executor():
            logger.warning('执行器仍在停止中，请稍候重试')
            return
        self.ui = None
        self.device = None
        self.scheduler.force_state('idle')

        self.scheduler.update_runtime_metrics(
            current_task='--',
            next_task='--',
            next_run='--',
            current_platform='--',
            window_id='--',
            running_tasks=0,
            pending_tasks=0,
            waiting_tasks=0,
            recovery_total=0,
            recovery_last_error='--',
            recovery_last_action='--',
            recovery_last_outcome='--',
            recovery_last_task='--',
        )
        # 兜底刷新：确保UI在点击停止后立即看到最新状态。
        self.state_changed.emit('idle')
        self.stats_updated.emit(self.scheduler.get_stats())
        logger.info('Bot已停止')

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
