"""屏幕捕获模块。"""

import ctypes
import os
import time
from ctypes import wintypes

import mss
from loguru import logger
from PIL import Image

from models.config import RunMode
from utils.image_utils import save_screenshot
from utils.run_mode_decorator import Config as DecoratorConfig, UNSET


class ScreenCapture:
    """提供前台区域截图与后台 PrintWindow 截图能力。"""

    PW_RENDERFULLCONTENT = 0x00000002
    DIB_RGB_COLORS = 0
    BI_RGB = 0

    def __init__(self, save_dir: str = 'screenshots', run_mode: RunMode = RunMode.BACKGROUND):
        self._save_dir = save_dir
        self._run_mode = run_mode
        os.makedirs(save_dir, exist_ok=True)

    def update_run_mode(self, run_mode: RunMode):
        """更新运行模式。"""
        self._run_mode = run_mode

    def resolve_dispatch_option(self, key: str):
        """为分发装饰器提供选项解析。"""
        if key == 'RUN_MODE':
            return self._run_mode
        return UNSET

    @staticmethod
    def _make_screenshot_path(save_dir: str, prefix: str = 'farm') -> str:
        ts = time.strftime('%Y%m%d_%H%M%S')
        filename = f'{prefix}_{ts}.png'
        return os.path.join(save_dir, filename)

    def capture_region(self, rect: tuple[int, int, int, int]) -> Image.Image | None:
        """前台区域截图：rect=(left, top, width, height)。"""
        left, top, width, height = rect
        monitor = {
            'left': left,
            'top': top,
            'width': width,
            'height': height,
        }
        try:
            with mss.mss() as sct:
                screenshot = sct.grab(monitor)
                image = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')
            return image
        except Exception as e:
            logger.error(f'截屏失败: {e}')
            return None

    def capture_window_print(self, hwnd: int) -> Image.Image | None:
        """后台截图：使用 PrintWindow 读取窗口位图。"""
        if not hwnd:
            return None

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        rect = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            logger.error('PrintWindow截屏失败: GetWindowRect 调用失败')
            return None
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            logger.error(f'PrintWindow截屏失败: 非法窗口尺寸 {width}x{height}')
            return None

        hwnd_dc = user32.GetWindowDC(wintypes.HWND(hwnd))
        if not hwnd_dc:
            logger.error('PrintWindow截屏失败: GetWindowDC 失败')
            return None

        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        if not mem_dc:
            user32.ReleaseDC(wintypes.HWND(hwnd), hwnd_dc)
            logger.error('PrintWindow截屏失败: CreateCompatibleDC 失败')
            return None

        bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        if not bitmap:
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(wintypes.HWND(hwnd), hwnd_dc)
            logger.error('PrintWindow截屏失败: CreateCompatibleBitmap 失败')
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ('biSize', wintypes.DWORD),
                ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG),
                ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD),
                ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD),
                ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [
                ('bmiHeader', BITMAPINFOHEADER),
                ('bmiColors', wintypes.DWORD * 3),
            ]

        old_obj = gdi32.SelectObject(mem_dc, bitmap)
        try:
            ok = user32.PrintWindow(wintypes.HWND(hwnd), mem_dc, self.PW_RENDERFULLCONTENT)
            if not ok:
                ok = user32.PrintWindow(wintypes.HWND(hwnd), mem_dc, 0)
            if not ok:
                logger.error('PrintWindow截屏失败: PrintWindow 返回 0')
                return None

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = self.BI_RGB

            buf_len = width * height * 4
            buffer = ctypes.create_string_buffer(buf_len)
            rows = gdi32.GetDIBits(
                mem_dc,
                bitmap,
                0,
                height,
                buffer,
                ctypes.byref(bmi),
                self.DIB_RGB_COLORS,
            )
            if rows != height:
                logger.error(f'PrintWindow截屏失败: GetDIBits 行数异常 ({rows}/{height})')
                return None

            return Image.frombytes('RGB', (width, height), buffer.raw, 'raw', 'BGRX')
        except Exception as e:
            logger.error(f'PrintWindow截屏失败: {e}')
            return None
        finally:
            if old_obj:
                gdi32.SelectObject(mem_dc, old_obj)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(wintypes.HWND(hwnd), hwnd_dc)

    def capture(self, rect: tuple[int, int, int, int], hwnd: int | None = None) -> Image.Image | None:
        """按运行模式截图。"""
        return self._capture_by_mode(rect, int(hwnd or 0))

    @DecoratorConfig.when(RUN_MODE=RunMode.BACKGROUND)
    def _capture_by_mode(self, rect: tuple[int, int, int, int], hwnd: int) -> Image.Image | None:
        image = self.capture_window_print(hwnd)
        if image is not None:
            return image
        return self.capture_region(rect)

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _capture_by_mode(self, rect: tuple[int, int, int, int], hwnd: int) -> Image.Image | None:
        _ = hwnd
        return self.capture_region(rect)

    def capture_and_save(
        self,
        rect: tuple[int, int, int, int],
        prefix: str = 'farm',
        *,
        hwnd: int | None = None,
    ) -> tuple[Image.Image | None, str]:
        """截图并保存到文件。"""
        image = self.capture(rect, hwnd=hwnd)
        if image is None:
            return None, ''
        filepath = self._make_screenshot_path(self._save_dir, prefix)
        save_screenshot(image, filepath)
        return image, filepath

    def capture_window_print_and_save(self, hwnd: int, prefix: str = 'farm') -> tuple[Image.Image | None, str]:
        """后台 PrintWindow 截图并保存。"""
        image = self.capture_window_print(hwnd)
        if image is None:
            return None, ''
        filepath = self._make_screenshot_path(self._save_dir, prefix)
        save_screenshot(image, filepath)
        return image, filepath

    def cleanup_old_screenshots(self, max_count: int = 50):
        """清理旧截图，保留最新 max_count 张。"""
        try:
            files = sorted(
                [os.path.join(self._save_dir, f) for f in os.listdir(self._save_dir) if f.endswith('.png')],
                key=os.path.getmtime,
            )
            if len(files) > max_count:
                for f in files[: len(files) - max_count]:
                    os.remove(f)
        except Exception as e:
            logger.warning(f'清理截图失败: {e}')
