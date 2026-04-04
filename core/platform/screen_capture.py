"""屏幕捕获模块"""

import os
import time

import mss
from loguru import logger
from PIL import Image

from utils.image_utils import save_screenshot


class ScreenCapture:
    """封装 `ScreenCapture` 相关的数据与行为。"""
    def __init__(self, save_dir: str = 'screenshots'):
        """初始化对象并准备运行所需状态。"""
        self._save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def capture_region(self, rect: tuple[int, int, int, int]) -> Image.Image | None:
        """截取指定区域 (left, top, width, height)"""
        left, top, width, height = rect
        monitor = {
            'left': left,
            'top': top,
            'width': width,
            'height': height,
        }
        try:
            # 每次截图创建新的mss实例，避免跨线程问题
            with mss.mss() as sct:
                screenshot = sct.grab(monitor)
                image = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')
            return image
        except Exception as e:
            logger.error(f'截屏失败: {e}')
            return None

    def capture_and_save(self, rect: tuple[int, int, int, int], prefix: str = 'farm') -> tuple[Image.Image | None, str]:
        """截屏并保存到文件，返回(图片, 文件路径)"""
        image = self.capture_region(rect)
        if image is None:
            return None, ''
        ts = time.strftime('%Y%m%d_%H%M%S')
        filename = f'{prefix}_{ts}.png'
        filepath = os.path.join(self._save_dir, filename)
        save_screenshot(image, filepath)
        return image, filepath

    def cleanup_old_screenshots(self, max_count: int = 50):
        """清理旧截图，保留最新的max_count张"""
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
