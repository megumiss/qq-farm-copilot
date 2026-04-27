"""窗口管理器 - 定位并管理目标农场窗口。"""

import ctypes
import ctypes.wintypes
import os
from dataclasses import dataclass

import pygetwindow as gw
from loguru import logger

from utils.app_paths import ensure_user_configs, load_config_json_object, resolve_config_file


@dataclass
class WindowInfo:
    """封装 `WindowInfo` 相关的数据与行为。"""

    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int
    pid: int = 0
    process_name: str = ''


@dataclass
class DisplayInfo:
    """封装显示器信息（按序号存取）。"""

    index: int
    monitor: int
    left: int
    top: int
    right: int
    bottom: int
    work_left: int
    work_top: int
    work_right: int
    work_bottom: int
    width: int
    height: int
    work_width: int
    work_height: int
    scale_percent: int
    dpi: int
    is_primary: bool
    device_name: str = ''


class MONITORINFO(ctypes.Structure):
    """封装 `MONITORINFO` 相关的数据与行为。"""

    _fields_ = [
        ('cbSize', ctypes.wintypes.DWORD),
        ('rcMonitor', ctypes.wintypes.RECT),
        ('rcWork', ctypes.wintypes.RECT),
        ('dwFlags', ctypes.wintypes.DWORD),
    ]


class MONITORINFOEX(ctypes.Structure):
    """扩展版本的显示器信息（含设备名）。"""

    _fields_ = [
        ('cbSize', ctypes.wintypes.DWORD),
        ('rcMonitor', ctypes.wintypes.RECT),
        ('rcWork', ctypes.wintypes.RECT),
        ('dwFlags', ctypes.wintypes.DWORD),
        ('szDevice', ctypes.c_wchar * 32),
    ]


class WindowManager:
    """封装 `WindowManager` 相关的数据与行为。"""

    TARGET_CLIENT_WIDTH = 540
    TARGET_CLIENT_HEIGHT = 960
    _MONITORINFOF_PRIMARY = 0x00000001
    _MONITOR_DEFAULTTONULL = 0
    _MONITOR_DEFAULTTONEAREST = 2
    _SWP_NOZORDER = 0x0004
    _SWP_NOOWNERZORDER = 0x0200
    _GWL_STYLE = -16
    _GWL_EXSTYLE = -20
    _MDT_EFFECTIVE_DPI = 0

    def __init__(self):
        """初始化对象并准备运行所需状态。"""
        self._enable_dpi_awareness()
        self._cached_window: WindowInfo | None = None
        ensure_user_configs()
        self._nonclient_json_path = resolve_config_file('nonclient_metrics.json', prefer_user=True)
        self._nonclient_config = self._load_nonclient_config()
        self._last_capture_rect_is_client: bool = False

    @staticmethod
    def _enable_dpi_awareness() -> None:
        """尽量开启 DPI 感知，减少尺寸虚拟化误差。"""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def _load_nonclient_config(self) -> dict:
        """加载窗口边框/标题高度配置。"""
        try:
            return load_config_json_object('nonclient_metrics.json', prefer_user=True)
        except Exception as e:
            logger.warning(f'加载 nonclient 配置失败: {self._nonclient_json_path}, {e}')
        return {}

    @staticmethod
    def _get_window_scale_percent(hwnd: int) -> int:
        """读取窗口 DPI 对应的缩放百分比。"""
        try:
            dpi = int(ctypes.windll.user32.GetDpiForWindow(hwnd))
        except Exception:
            dpi = 96
        scale = int(round((dpi / 96.0) * 100))
        return max(50, min(scale, 500))

    @staticmethod
    def _get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
        """获取 `window rect` 信息。"""
        rect = ctypes.wintypes.RECT()
        ok = ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if not ok:
            return None
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

    @staticmethod
    def _get_window_outer_size(hwnd: int) -> tuple[int, int] | None:
        """获取 `window outer size` 信息。"""
        rect = WindowManager._get_window_rect(hwnd)
        if not rect:
            return None
        return int(rect[2] - rect[0]), int(rect[3] - rect[1])

    @staticmethod
    def _get_client_size(hwnd: int) -> tuple[int, int] | None:
        """获取 `client size` 信息。"""
        rect = ctypes.wintypes.RECT()
        ok = ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
        if not ok:
            return None
        return int(rect.right - rect.left), int(rect.bottom - rect.top)

    @staticmethod
    def _get_client_rect_screen(hwnd: int) -> tuple[int, int, int, int] | None:
        """返回客户区在屏幕坐标中的矩形 (left, top, width, height)。"""
        user32 = ctypes.windll.user32
        rect = ctypes.wintypes.RECT()
        if not bool(user32.GetClientRect(hwnd, ctypes.byref(rect))):
            return None
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            return None
        pt = ctypes.wintypes.POINT(0, 0)
        if not bool(user32.ClientToScreen(hwnd, ctypes.byref(pt))):
            return None
        return int(pt.x), int(pt.y), width, height

    @staticmethod
    def _calc_outer_size_by_adjust_rect(
        hwnd: int, client_width: int, client_height: int
    ) -> tuple[int, int, int] | None:
        """参考 NIKKE change_resolution_compat：按窗口 style/exstyle + DPI 计算外框尺寸。"""
        try:
            user32 = ctypes.windll.user32
            dpi = 96
            try:
                dpi = int(user32.GetDpiForWindow(hwnd))
            except Exception:
                dpi = 96

            rect = ctypes.wintypes.RECT(0, 0, int(client_width), int(client_height))
            style = int(user32.GetWindowLongW(hwnd, WindowManager._GWL_STYLE))
            ex_style = int(user32.GetWindowLongW(hwnd, WindowManager._GWL_EXSTYLE))

            ok = False
            try:
                ok = bool(user32.AdjustWindowRectExForDpi(ctypes.byref(rect), style, False, ex_style, int(dpi)))
            except Exception:
                ok = bool(user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, ex_style))
            if not ok:
                return None

            outer_w = int(rect.right - rect.left)
            outer_h = int(rect.bottom - rect.top)
            return outer_w, outer_h, int(dpi)
        except Exception:
            return None

    @staticmethod
    def _get_system_scale_percent() -> int:
        """读取系统缩放百分比。"""
        try:
            dpi = int(ctypes.windll.user32.GetDpiForSystem())
        except Exception:
            dpi = 96
        scale = int(round((float(dpi) / 96.0) * 100))
        return max(50, min(scale, 500))

    def _get_monitor_scale_percent(self, monitor: int) -> int:
        """读取指定显示器缩放百分比。"""
        monitor_value = int(monitor or 0)
        if monitor_value <= 0:
            return self._get_system_scale_percent()
        try:
            shcore = ctypes.windll.shcore
            dpi_x = ctypes.wintypes.UINT(0)
            dpi_y = ctypes.wintypes.UINT(0)
            hr = int(
                shcore.GetDpiForMonitor(
                    ctypes.c_void_p(monitor_value),
                    int(self._MDT_EFFECTIVE_DPI),
                    ctypes.byref(dpi_x),
                    ctypes.byref(dpi_y),
                )
            )
            if hr == 0 and int(dpi_x.value) > 0:
                scale = int(round((float(dpi_x.value) / 96.0) * 100))
                return max(50, min(scale, 500))
        except Exception:
            pass
        return self._get_system_scale_percent()

    def list_displays(self) -> list[DisplayInfo]:
        """枚举当前系统显示器列表（按主屏优先）。"""
        user32 = ctypes.windll.user32
        displays: list[DisplayInfo] = []
        monitor_handles: list[int] = []

        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.RECT),
            ctypes.c_long,
        )

        def _enum_proc(hmonitor, _hdc, _rect, _lparam) -> int:
            monitor_handles.append(int(hmonitor or 0))
            return 1

        enum_proc = callback_type(_enum_proc)
        try:
            ok = bool(user32.EnumDisplayMonitors(0, 0, enum_proc, 0))
            if not ok:
                monitor_handles.clear()
        except Exception:
            monitor_handles.clear()

        for seq, monitor in enumerate(monitor_handles, start=1):
            if int(monitor) <= 0:
                continue
            info = MONITORINFOEX()
            info.cbSize = ctypes.sizeof(MONITORINFOEX)
            ok = bool(user32.GetMonitorInfoW(ctypes.c_void_p(int(monitor)), ctypes.byref(info)))
            if not ok:
                continue

            left = int(info.rcMonitor.left)
            top = int(info.rcMonitor.top)
            right = int(info.rcMonitor.right)
            bottom = int(info.rcMonitor.bottom)
            work_left = int(info.rcWork.left)
            work_top = int(info.rcWork.top)
            work_right = int(info.rcWork.right)
            work_bottom = int(info.rcWork.bottom)
            width = max(0, right - left)
            height = max(0, bottom - top)
            work_width = max(0, work_right - work_left)
            work_height = max(0, work_bottom - work_top)
            scale_percent = int(self._get_monitor_scale_percent(int(monitor)))
            dpi = int(round((float(scale_percent) / 100.0) * 96))
            is_primary = bool(int(info.dwFlags) & int(self._MONITORINFOF_PRIMARY))
            device_name = str(info.szDevice or '').strip('\x00').strip()
            displays.append(
                DisplayInfo(
                    index=int(seq),
                    monitor=int(monitor),
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                    work_left=work_left,
                    work_top=work_top,
                    work_right=work_right,
                    work_bottom=work_bottom,
                    width=width,
                    height=height,
                    work_width=work_width,
                    work_height=work_height,
                    scale_percent=scale_percent,
                    dpi=dpi,
                    is_primary=is_primary,
                    device_name=device_name,
                )
            )

        if not displays:
            scale_percent = self._get_system_scale_percent()
            dpi = int(round((float(scale_percent) / 100.0) * 96))
            screen_w = int(user32.GetSystemMetrics(0))
            screen_h = int(user32.GetSystemMetrics(1))
            work_area = ctypes.wintypes.RECT()
            ok = bool(user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0))
            if ok:
                work_left = int(work_area.left)
                work_top = int(work_area.top)
                work_right = int(work_area.right)
                work_bottom = int(work_area.bottom)
            else:
                work_left = 0
                work_top = 0
                work_right = screen_w
                work_bottom = screen_h
            displays.append(
                DisplayInfo(
                    index=1,
                    monitor=0,
                    left=0,
                    top=0,
                    right=screen_w,
                    bottom=screen_h,
                    work_left=work_left,
                    work_top=work_top,
                    work_right=work_right,
                    work_bottom=work_bottom,
                    width=max(0, screen_w),
                    height=max(0, screen_h),
                    work_width=max(0, work_right - work_left),
                    work_height=max(0, work_bottom - work_top),
                    scale_percent=scale_percent,
                    dpi=dpi,
                    is_primary=True,
                    device_name='',
                )
            )
        return displays

    def _resolve_display_for_window(self, hwnd: int) -> DisplayInfo | None:
        """按窗口句柄解析所在显示器；失败时回退首屏。"""
        displays = self.list_displays()
        if not displays:
            return None

        target_hwnd = int(hwnd or 0)
        if target_hwnd > 0:
            try:
                monitor = int(
                    ctypes.windll.user32.MonitorFromWindow(
                        ctypes.wintypes.HWND(target_hwnd),
                        int(self._MONITOR_DEFAULTTONEAREST),
                    )
                    or 0
                )
            except Exception:
                monitor = 0
            if monitor > 0:
                for item in displays:
                    if int(item.monitor) == monitor:
                        return item
        return self._primary_display(displays)

    @staticmethod
    def _primary_display(displays: list[DisplayInfo]) -> DisplayInfo:
        """在显示器列表中选择主屏；未命中时回退首项。"""
        for item in displays:
            if bool(item.is_primary):
                return item
        return displays[0]

    def _resolve_display_for_index(self, screen_index: int, hwnd: int = 0) -> DisplayInfo | None:
        """按配置序号选择显示器；`<=0` 使用主屏。"""
        displays = self.list_displays()
        if not displays:
            return None
        primary = self._primary_display(displays)
        idx = int(screen_index)
        if idx <= 0:
            return primary
        for item in displays:
            if int(item.index) == idx:
                return item
        logger.warning(f'屏幕序号越界({idx}/{len(displays)})，回退到主屏#{primary.index}')
        return primary

    def _get_work_area_for_window(self, hwnd: int) -> ctypes.wintypes.RECT | None:
        """获取窗口当前所在显示器的工作区。"""
        display = self._resolve_display_for_window(hwnd)
        if display is not None:
            return ctypes.wintypes.RECT(display.work_left, display.work_top, display.work_right, display.work_bottom)

        work_area = ctypes.wintypes.RECT()
        ok = bool(ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0))
        if not ok:
            return None
        return work_area

    def _get_work_area_for_screen_index(
        self, screen_index: int, hwnd: int
    ) -> tuple[ctypes.wintypes.RECT | None, DisplayInfo | None]:
        """获取配置屏幕对应的工作区。"""
        display = self._resolve_display_for_index(screen_index, hwnd=hwnd)
        if display is not None:
            return (
                ctypes.wintypes.RECT(display.work_left, display.work_top, display.work_right, display.work_bottom),
                display,
            )
        return self._get_work_area_for_window(hwnd), None

    def get_display_metrics(self, hwnd: int | None = None) -> dict[str, int] | None:
        """读取屏幕/显示器分辨率与缩放信息。"""
        try:
            user32 = ctypes.windll.user32
            target_hwnd = int(hwnd or 0)
            if target_hwnd <= 0 and self._cached_window:
                target_hwnd = int(self._cached_window.hwnd)

            screen_w = int(user32.GetSystemMetrics(0))
            screen_h = int(user32.GetSystemMetrics(1))
            metrics = {
                'screen_width': screen_w,
                'screen_height': screen_h,
                'monitor_width': screen_w,
                'monitor_height': screen_h,
                'work_width': screen_w,
                'work_height': screen_h,
                'dpi': 96,
                'scale_percent': 100,
                'monitor_index': 1,
            }

            target_display: DisplayInfo | None = None
            if target_hwnd > 0:
                target_display = self._resolve_display_for_window(target_hwnd)
            else:
                displays = self.list_displays()
                if displays:
                    target_display = self._primary_display(displays)

            if target_display is not None:
                metrics['monitor_width'] = int(target_display.width)
                metrics['monitor_height'] = int(target_display.height)
                metrics['work_width'] = int(target_display.work_width)
                metrics['work_height'] = int(target_display.work_height)
                metrics['scale_percent'] = int(target_display.scale_percent)
                metrics['dpi'] = int(target_display.dpi)
                metrics['monitor_index'] = int(target_display.index)

            return metrics
        except Exception as exc:
            logger.debug(f'读取屏幕信息失败: {exc}')
            return None

    def _set_window_outer_rect(self, hwnd: int, x: int, y: int, width: int, height: int) -> tuple[bool, str]:
        """设置 `window outer rect` 参数。"""
        user32 = ctypes.windll.user32
        ok = bool(
            user32.SetWindowPos(
                hwnd,
                0,
                int(x),
                int(y),
                int(width),
                int(height),
                self._SWP_NOZORDER | self._SWP_NOOWNERZORDER,
            )
        )
        if ok:
            return True, 'SetWindowPos'
        ok = bool(user32.MoveWindow(hwnd, int(x), int(y), int(width), int(height), True))
        if ok:
            return True, 'MoveWindow'
        return False, 'SetWindowPos/MoveWindow failed'

    def _set_window_outer_size_with_retry(
        self,
        hwnd: int,
        x: int,
        y: int,
        target_outer_width: int,
        target_outer_height: int,
        max_rounds: int = 6,
        verbose_log: bool = False,
    ) -> tuple[bool, str]:
        """参考 debug 脚本：按外框误差迭代修正。"""
        current_w = int(target_outer_width)
        current_h = int(target_outer_height)
        apply_method = 'unknown'

        for round_idx in range(1, max_rounds + 1):
            ok, apply_method = self._set_window_outer_rect(hwnd, x, y, current_w, current_h)
            if not ok:
                return False, f'第{round_idx}轮调整失败: {apply_method}'

            outer_size = self._get_window_outer_size(hwnd)
            if not outer_size:
                return False, f'第{round_idx}轮调整失败: 无法读取窗口外框'

            err_w = int(target_outer_width - outer_size[0])
            err_h = int(target_outer_height - outer_size[1])
            if err_w == 0 and err_h == 0:
                return True, (f'{round_idx}轮调整成功; 实际外框={outer_size[0]}x{outer_size[1]}; 应用={apply_method}')

            current_w = max(120, int(current_w + err_w))
            current_h = max(120, int(current_h + err_h))

        final_outer = self._get_window_outer_size(hwnd)
        if not final_outer:
            return False, '达到最大轮次，且无法读取最终外框'
        return False, (
            f'达到最大轮次; 最终外框={final_outer[0]}x{final_outer[1]}, '
            f'目标外框={target_outer_width}x{target_outer_height}; 应用={apply_method}'
        )

    def _get_nonclient_metrics(self, platform: str, scale_percent: int) -> tuple[int, int, int]:
        """按平台+缩放取边框/标题高度；缩放值使用最近匹配。"""
        cfg = self._nonclient_config or {}
        platforms = cfg.get('platforms', {}) if isinstance(cfg, dict) else {}
        platform_key = (platform or '').strip().lower()
        if platform_key not in platforms:
            platform_key = str(cfg.get('default_platform', 'qq')).lower()
        platform_cfg = platforms.get(platform_key, {})
        scales = platform_cfg.get('scales', {}) if isinstance(platform_cfg, dict) else {}

        valid_pairs: list[tuple[int, dict]] = []
        for k, v in scales.items():
            try:
                valid_pairs.append((int(k), v))
            except Exception:
                continue
        if not valid_pairs:
            # 兜底：QQ 100%
            return 1, 39, 100

        matched_scale, matched_value = min(valid_pairs, key=lambda item: abs(item[0] - int(scale_percent)))
        border = int(matched_value.get('border_width', 1))
        title = int(matched_value.get('title_height', 39))
        return border, title, matched_scale

    def get_preview_crop_margins(self, platform: str = 'qq') -> tuple[int, int, int, int]:
        """返回基于 nonclient json 的预览裁切边距 (left, top, right, bottom)。"""
        if not self._cached_window:
            return 0, 0, 0, 0
        try:
            hwnd = self._cached_window.hwnd
            scale_percent = self._get_window_scale_percent(hwnd)
            border_width, title_height, _ = self._get_nonclient_metrics(platform, scale_percent)
            left = max(0, int(border_width))
            right = max(0, int(border_width))
            top = max(0, int(title_height + border_width))
            bottom = max(0, int(border_width))
            return left, top, right, bottom
        except Exception:
            return 0, 0, 0, 0

    def crop_window_image_for_preview(self, image, platform: str = 'qq'):
        """统一按目标分辨率裁切预览图（优先落到 540x960）。"""
        if image is None:
            return image
        width, height = image.size
        x1, y1, crop_w, crop_h = self.get_preview_crop_box(width, height, platform)
        if crop_w == width and crop_h == height and x1 == 0 and y1 == 0:
            return image
        x2 = x1 + crop_w
        y2 = y1 + crop_h
        return image.crop((x1, y1, x2, y2))

    def get_preview_crop_box(self, raw_width: int, raw_height: int, platform: str = 'qq') -> tuple[int, int, int, int]:
        """按预览裁切规则返回裁切框 (x1, y1, width, height)。"""
        width = int(raw_width)
        height = int(raw_height)
        target_w = int(self.TARGET_CLIENT_WIDTH)
        target_h = int(self.TARGET_CLIENT_HEIGHT)

        # 与 crop_window_image_for_preview 保持一致：尺寸足够则裁成目标尺寸，否则不裁切
        if width >= target_w and height >= target_h:
            left_pref, top_pref, _, _ = self.get_preview_crop_margins(platform)
            x1 = min(max(0, int(left_pref)), max(0, width - target_w))
            y1 = min(max(0, int(top_pref)), max(0, height - target_h))
            return x1, y1, target_w, target_h

        return 0, 0, width, height

    @staticmethod
    def _matches_keyword(title: str, title_keyword: str) -> bool:
        """判断窗口标题是否匹配关键词规则。"""
        title_text = str(title or '')
        keyword = str(title_keyword or '').strip().lower()
        if not keyword:
            return '农场' in title_text
        title_lower = title_text.lower()
        if keyword in title_lower:
            return True
        parts = [part for part in keyword.split() if part]
        return bool(parts) and all(part in title_lower for part in parts)

    @staticmethod
    def _get_window_pid(hwnd: int) -> int:
        """通过窗口句柄读取进程 PID。"""
        try:
            pid = ctypes.wintypes.DWORD(0)
            ctypes.windll.user32.GetWindowThreadProcessId(ctypes.wintypes.HWND(hwnd), ctypes.byref(pid))
            return int(pid.value)
        except Exception:
            return 0

    @staticmethod
    def _get_process_name(pid: int) -> str:
        """通过 PID 读取进程名。"""
        if int(pid) <= 0:
            return ''
        kernel32 = ctypes.windll.kernel32
        process_handle = 0
        try:
            process_handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if not process_handle:
                return ''
            size = ctypes.wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            ok = bool(kernel32.QueryFullProcessImageNameW(process_handle, 0, buf, ctypes.byref(size)))
            if not ok:
                return ''
            full_path = str(buf.value or '').strip()
            if not full_path:
                return ''
            return os.path.basename(full_path).lower()
        except Exception:
            return ''
        finally:
            if process_handle:
                try:
                    kernel32.CloseHandle(process_handle)
                except Exception:
                    pass

    @staticmethod
    def _matches_platform(process_name: str, platform: str | None) -> bool:
        """判断进程名是否符合平台。"""
        p = str(process_name or '').strip().lower()
        target = str(platform or '').strip().lower()
        if not target:
            return False
        if target == 'qq':
            return p == 'qq.exe' or p.startswith('qq')
        if target == 'wechat':
            return p.startswith('wechat') or 'weixin' in p
        return False

    @staticmethod
    def _resolve_select_index(select_rule: str, total: int) -> int:
        """将选择规则解析为窗口索引，非法规则回退到 0。"""
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
            if idx >= total:
                logger.warning(f'窗口选择规则超出范围({text})，已回退自动选择')
                return 0
            return idx
        return 0

    def _resolve_auto_index(self, windows: list[WindowInfo], platform: str | None) -> int | None:
        """自动选择窗口：仅按平台命中；未命中则返回 `None`。"""
        if not windows:
            return None

        target = str(platform or '').strip().lower()
        if not target:
            logger.warning('自动选窗失败: 平台为空，无法按平台匹配窗口')
            return None

        for idx, info in enumerate(windows):
            if self._matches_platform(info.process_name, target):
                return idx

        logger.warning(f'自动选窗失败: 未找到匹配平台窗口 平台={target}')
        return None

    @classmethod
    def list_windows(cls, title_keyword: str = 'QQ经典农场') -> list[WindowInfo]:
        """按关键词列出候选窗口（用于设置下拉与运行时选择）。"""
        try:
            all_windows = gw.getAllWindows()
            matched: list[WindowInfo] = []
            seen_hwnd: set[int] = set()

            def append_if_match(window_obj, *, fallback_farm: bool = False) -> None:
                title = str(getattr(window_obj, 'title', '') or '')
                if not title.strip():
                    return
                if fallback_farm:
                    if '农场' not in title:
                        return
                elif not cls._matches_keyword(title, title_keyword):
                    return

                hwnd = int(getattr(window_obj, '_hWnd', 0) or 0)
                if hwnd <= 0 or hwnd in seen_hwnd:
                    return
                width = int(getattr(window_obj, 'width', 0) or 0)
                height = int(getattr(window_obj, 'height', 0) or 0)
                if width <= 0 or height <= 0:
                    return
                pid = cls._get_window_pid(hwnd)
                process_name = cls._get_process_name(pid)
                matched.append(
                    WindowInfo(
                        hwnd=hwnd,
                        title=title,
                        left=int(getattr(window_obj, 'left', 0) or 0),
                        top=int(getattr(window_obj, 'top', 0) or 0),
                        width=width,
                        height=height,
                        pid=pid,
                        process_name=process_name,
                    )
                )
                seen_hwnd.add(hwnd)

            for win in all_windows:
                append_if_match(win, fallback_farm=False)

            # 未命中关键词时回退“农场”包含匹配，兼容标题轻微变化。
            if not matched:
                for win in all_windows:
                    append_if_match(win, fallback_farm=True)

            matched.sort(key=lambda item: (int(item.left), int(item.top), int(item.hwnd)))
            return matched
        except Exception as e:
            logger.error(f'列出窗口失败: {e}')
            return []

    def find_window(
        self,
        title_keyword: str = 'QQ经典农场',
        select_rule: str = 'auto',
        platform: str | None = None,
    ) -> WindowInfo | None:
        """通过标题关键词与选择规则查找窗口。"""
        windows = self.list_windows(title_keyword)
        if not windows:
            logger.warning(f"未找到包含 '{title_keyword}' 的窗口")
            return None
        if str(select_rule or '').strip().lower() in {'', 'auto'}:
            target_index = self._resolve_auto_index(windows, platform)
            if target_index is None:
                return None
        else:
            target_index = self._resolve_select_index(select_rule, len(windows))
        info = windows[target_index]
        self._cached_window = info
        logger.debug(
            f'找到窗口[{target_index + 1}/{len(windows)}]: {info.title} ({info.width}x{info.height}), '
            f'平台={platform}, process={info.process_name or "unknown"}'
        )
        return info

    def get_window_rect(self) -> tuple[int, int, int, int] | None:
        """获取缓存窗口的区域 (left, top, width, height)"""
        if not self._cached_window:
            return None
        w = self._cached_window
        return (w.left, w.top, w.width, w.height)

    def get_window_handle(self) -> int | None:
        """获取当前缓存窗口句柄。"""
        if not self._cached_window:
            return None
        return int(self._cached_window.hwnd)

    def get_capture_rect(self) -> tuple[int, int, int, int] | None:
        """获取截图区域，优先客户区，失败时回退整窗。"""
        if not self._cached_window:
            return None

        hwnd = self._cached_window.hwnd
        client_rect = self._get_client_rect_screen(hwnd)
        if client_rect:
            self._last_capture_rect_is_client = True
            return client_rect

        outer_rect = self._get_window_rect(hwnd)
        if outer_rect:
            self._last_capture_rect_is_client = False
            return (
                int(outer_rect[0]),
                int(outer_rect[1]),
                int(outer_rect[2] - outer_rect[0]),
                int(outer_rect[3] - outer_rect[1]),
            )

        self._last_capture_rect_is_client = False
        w = self._cached_window
        return (w.left, w.top, w.width, w.height)

    def is_capture_rect_client(self) -> bool:
        """判断是否满足 `capture rect client` 条件。"""
        return bool(self._last_capture_rect_is_client)

    def activate_window(self) -> bool:
        """激活并置顶窗口"""
        if not self._cached_window:
            return False
        try:
            hwnd = self._cached_window.hwnd
            # 使用win32 API置顶窗口
            SW_RESTORE = 9
            ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            logger.debug('窗口已激活')
            return True
        except Exception as e:
            logger.error(f'激活窗口失败: {e}')
            return False

    @staticmethod
    def _calculate_position(
        work_area: ctypes.wintypes.RECT, window_width: int, window_height: int, position: str = 'left_center'
    ) -> tuple[int, int]:
        """根据工作区计算窗口左上角坐标"""
        wa_left, wa_top = work_area.left, work_area.top
        wa_right, wa_bottom = work_area.right, work_area.bottom
        wa_width = wa_right - wa_left
        wa_height = wa_bottom - wa_top

        if position == 'center':
            x = wa_left + (wa_width - window_width) // 2
            y = wa_top + (wa_height - window_height) // 2
        elif position == 'right_center':
            x = wa_right - window_width
            y = wa_top + (wa_height - window_height) // 2
        elif position == 'top_left':
            x = wa_left
            y = wa_top
        elif position == 'top_right':
            x = wa_right - window_width
            y = wa_top
        elif position == 'left_bottom':
            x = wa_left
            y = wa_bottom - window_height
        elif position == 'right_bottom':
            x = wa_right - window_width
            y = wa_bottom - window_height
        else:
            # 默认：左侧中央
            x = wa_left
            y = wa_top + (wa_height - window_height) // 2

        # 边界保护，避免超出工作区
        x = max(wa_left, min(x, wa_right - window_width))
        y = max(wa_top, min(y, wa_bottom - window_height))
        return x, y

    def resize_window(self, position: str = 'left_center', platform: str = 'qq', screen_index: int = 1) -> bool:
        """按平台规则将窗口调整到目标尺寸并放置到指定位置。

        核心目标：
        - 保证最终客户区可稳定用于 540x960 模板识别。
        - 在 QQ/微信两种窗口模型下使用不同的外框计算公式。
        - 输出详细误差日志，便于排查 DPI/边框差异导致的偏移问题。
        """
        if not self._cached_window:
            return False
        try:
            hwnd = self._cached_window.hwnd
            base_width = self.TARGET_CLIENT_WIDTH
            base_height = self.TARGET_CLIENT_HEIGHT
            target_work_area, target_display = self._get_work_area_for_screen_index(screen_index, hwnd)
            if not target_work_area:
                logger.error('调整窗口大小失败: 无法获取目标屏幕工作区')
                return False

            target_display_index = int(getattr(target_display, 'index', 1))
            target_scale_percent = int(getattr(target_display, 'scale_percent', 0) or 0)
            if target_scale_percent <= 0:
                target_scale_percent = int(self._get_window_scale_percent(hwnd))
            target_display_desc = f'#{target_display_index}'
            if target_display is not None:
                target_display_desc = (
                    f'#{target_display.index} '
                    f'{target_display.width}x{target_display.height} '
                    f'{target_display.scale_percent}%'
                )

            # 1) 读取当前窗口缩放与非客户区参数（边框/标题栏）。
            scale_percent = int(target_scale_percent)
            border_width, title_height, matched_scale = self._get_nonclient_metrics(platform, scale_percent)
            platform_key = (platform or '').strip().lower()
            is_wechat = platform_key in ('wechat', 'wx', 'weixin')
            target_client_w = int(base_width)
            target_client_h = int(base_height)
            before_outer = self._get_window_outer_size(hwnd)
            before_client = self._get_client_size(hwnd)

            if not before_outer or not before_client:
                logger.error('调整窗口大小失败: 无法读取当前窗口外框/客户区尺寸')
                return False

            # tools/resize_window.py: 动态 nonclient
            nonclient_w = max(0, int(before_outer[0] - before_client[0]))
            nonclient_h = max(0, int(before_outer[1] - before_client[1]))

            # 2) 依据平台差异计算“目标外框尺寸”。
            # 目标物理尺寸（target_physical_w/h）
            # 1) 微信: 540 x (960 + border + title)
            # 2) QQ  : (540 + border*2) x (960 + border*2 + title)
            if is_wechat:
                target_physical_w = int(base_width)
                target_physical_h = int(base_height + border_width + title_height)

                # tools: 微信最终尺寸 = target_physical + 当前 nonclient
                target_outer_w = int(target_physical_w + nonclient_w)
                target_outer_h = int(target_physical_h + nonclient_h)

                width_add = 0
                height_add = int(border_width + title_height)
                formula_desc = '微信公式: 最终外框=目标物理尺寸+当前非客户区'
            else:
                target_physical_w = int(base_width + border_width * 2)
                target_physical_h = int(base_height + border_width * 2 + title_height)

                # tools: QQ 最终尺寸 = target_physical（不额外加 nonclient）
                target_outer_w = int(target_physical_w)
                target_outer_h = int(target_physical_h)

                width_add = int(border_width * 2)
                height_add = int(border_width * 2 + title_height)
                formula_desc = 'QQ公式: 最终外框=目标物理尺寸'

            # 3) 计算目标放置坐标（目标屏工作区内，避免遮挡任务栏）。
            pos_x, pos_y = self._calculate_position(target_work_area, target_outer_w, target_outer_h, position)

            before_outer_text = f'{before_outer[0]}x{before_outer[1]}' if before_outer else 'unknown'
            before_client_text = f'{before_client[0]}x{before_client[1]}' if before_client else 'unknown'
            logger.debug(
                f'[窗口调整][开始] 公式={formula_desc} 调整前外框={before_outer_text} '
                f'调整前客户区={before_client_text} 目标外框={target_outer_w}x{target_outer_h} '
                f'目标客户区={target_client_w}x{target_client_h} '
                f'非客户区={nonclient_w}x{nonclient_h} 屏幕={target_display_desc} '
                f'位置={position} 目标坐标=({pos_x},{pos_y})'
            )

            # 4) 尝试应用窗口外框尺寸与位置（跨屏场景用迭代可消除 DPI 换算抖动）。
            ok, resize_msg = self._set_window_outer_size_with_retry(
                hwnd=hwnd,
                x=pos_x,
                y=pos_y,
                target_outer_width=target_outer_w,
                target_outer_height=target_outer_h,
                max_rounds=6,
            )
            if not ok:
                logger.error(f'调整窗口大小失败: {resize_msg}')
                return False

            # 5) 回读最终尺寸，计算客户区/外框误差并更新缓存。
            final_rect = self._get_window_rect(hwnd)
            final_client = self._get_client_size(hwnd)
            if final_rect:
                self._cached_window.left = int(final_rect[0])
                self._cached_window.top = int(final_rect[1])
                self._cached_window.width = int(final_rect[2] - final_rect[0])
                self._cached_window.height = int(final_rect[3] - final_rect[1])
            else:
                self._cached_window.left = pos_x
                self._cached_window.top = pos_y
                self._cached_window.width = target_outer_w
                self._cached_window.height = target_outer_h

            actual_outer_w = int(self._cached_window.width)
            actual_outer_h = int(self._cached_window.height)
            actual_client_text = f'{final_client[0]}x{final_client[1]}' if final_client else 'unknown'
            outer_err_w = int(target_outer_w - actual_outer_w)
            outer_err_h = int(target_outer_h - actual_outer_h)
            client_err_w = int(target_client_w - final_client[0]) if final_client else 0
            client_err_h = int(target_client_h - final_client[1]) if final_client else 0

            # 某些窗口上 GetClientRect 可能返回整窗尺寸（与外框一致），此时按外框校验更可靠。
            client_same_as_outer = bool(
                final_client and int(final_client[0]) == actual_outer_w and int(final_client[1]) == actual_outer_h
            )
            has_nonclient_add = bool(int(width_add) > 0 or int(height_add) > 0)
            use_outer_as_primary = (not final_client) or (client_same_as_outer and has_nonclient_add)
            if use_outer_as_primary:
                judged_by = '外框'
                judge_err_w, judge_err_h = outer_err_w, outer_err_h
            else:
                judged_by = '客户区'
                judge_err_w, judge_err_h = client_err_w, client_err_h

            # 微信分支下，客户区高度可能按 (960 + 边框 + 标题) 呈现；外框命中时视为正常。
            wechat_client_expected_w = int(target_client_w + width_add)
            wechat_client_expected_h = int(target_client_h + height_add)
            wechat_client_match = bool(
                is_wechat
                and final_client
                and int(final_client[0]) == wechat_client_expected_w
                and int(final_client[1]) == wechat_client_expected_h
            )
            if wechat_client_match and outer_err_w == 0 and outer_err_h == 0:
                judged_by = '外框(微信规则)'
                judge_err_w, judge_err_h = 0, 0

            logger.debug(
                f'[窗口调整][结束] 最终外框={self._cached_window.width}x{self._cached_window.height} '
                f'最终客户区={actual_client_text} 客户区误差=({client_err_w},{client_err_h}) '
                f'外框误差=({outer_err_w},{outer_err_h}) 校验基准={judged_by}'
            )

            actual_outer_text = f'{self._cached_window.width}x{self._cached_window.height}'
            logger.debug(
                f'[窗口调整][细节] 目标客户区={target_client_w}x{target_client_h}, '
                f'平台={platform}, 屏幕={target_display_desc}, DPI缩放={scale_percent}% (匹配={matched_scale}%), '
                f'增量=(宽+{width_add},高+{height_add},边框={border_width},标题={title_height}), '
                f'目标外框={target_outer_w}x{target_outer_h}, 实际外框={actual_outer_text}, '
                f'实际客户区={actual_client_text}'
            )

            # 6) 输出最终结论：误差不为 0 记 warning，否则记 info。
            if judge_err_w != 0 or judge_err_h != 0:
                logger.warning(
                    f'窗口调整完成但{judged_by}存在偏差: '
                    f'目标客户区={target_client_w}x{target_client_h}, 实际客户区={actual_client_text}, '
                    f'目标外框={target_outer_w}x{target_outer_h}, 实际外框={actual_outer_w}x{actual_outer_h}, '
                    f'{judged_by}误差=({judge_err_w},{judge_err_h}), '
                    f'位置=({self._cached_window.left},{self._cached_window.top}) '
                    f'[{target_display_desc} | {position}]'
                )
            else:
                logger.info(
                    f'窗口调整完成: 客户区={actual_client_text}, '
                    f'外框={actual_outer_w}x{actual_outer_h}, 校验={judged_by}, '
                    f'位置=({self._cached_window.left},{self._cached_window.top}) '
                    f'[{target_display_desc} | {position}]'
                )
            logger.debug(f'[窗口调整][应用] {resize_msg}')
            return True
        except Exception as e:
            logger.error(f'调整窗口大小失败: {e}')
            return False

    def is_window_visible(self) -> bool:
        """检查窗口是否可见"""
        if not self._cached_window:
            return False
        try:
            return bool(ctypes.windll.user32.IsWindowVisible(self._cached_window.hwnd))
        except Exception:
            return False

    def refresh_window_info(
        self,
        title_keyword: str = 'QQ农场',
        select_rule: str = 'auto',
        platform: str | None = None,
    ) -> WindowInfo | None:
        """刷新窗口位置信息。"""
        return self.find_window(title_keyword, select_rule, platform)

    def refresh_cached_window_info(self) -> WindowInfo | None:
        """按缓存句柄快速刷新窗口几何信息（不重新枚举所有窗口）。"""
        if not self._cached_window:
            return None

        hwnd = int(self._cached_window.hwnd or 0)
        if hwnd <= 0:
            return None

        rect = self._get_window_rect(hwnd)
        if not rect:
            return None

        left, top, right, bottom = rect
        self._cached_window.left = int(left)
        self._cached_window.top = int(top)
        self._cached_window.width = int(max(0, right - left))
        self._cached_window.height = int(max(0, bottom - top))
        if int(self._cached_window.pid or 0) <= 0:
            self._cached_window.pid = self._get_window_pid(hwnd)
            self._cached_window.process_name = self._get_process_name(self._cached_window.pid)
        return self._cached_window
