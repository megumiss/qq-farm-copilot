"""nklite 设备适配：桥接现有 BotEngine 截图与点击。"""

from __future__ import annotations

import time
from typing import Callable

import numpy as np

from core.base.button import Button


class NKLiteDevice:
    """提供 `NKLiteDevice` 的设备能力适配接口。"""
    def __init__(
        self,
        screenshot_fn: Callable[[tuple[int, int, int, int]], np.ndarray | None],
        click_fn: Callable[[int, int, str], bool],
        sleep_fn: Callable[[float], bool],
        cancel_checker: Callable[[], bool],
    ):
        """初始化对象并准备运行所需状态。"""
        self._screenshot_fn = screenshot_fn
        self._click_fn = click_fn
        self._sleep_fn = sleep_fn
        self._cancel_checker = cancel_checker
        self.rect: tuple[int, int, int, int] | None = None
        self.image: np.ndarray | None = None

    def set_rect(self, rect: tuple[int, int, int, int]):
        """设置 `rect` 参数。"""
        self.rect = rect

    def screenshot(self):
        """执行 `screenshot` 相关处理。"""
        if self.rect is None:
            self.image = None
            return None
        self.image = self._screenshot_fn(self.rect)
        return self.image

    def set_image(self, image: np.ndarray | None):
        """设置 `image` 参数。"""
        self.image = image

    def click(self, button: Button, click_offset=0):
        """执行点击动作并返回是否成功。"""
        _ = click_offset
        x, y = button.location
        return self._click_fn(x, y, button.name)

    def click_minitouch(self, x: int, y: int):
        """执行点击动作并返回是否成功。"""
        return self._click_fn(int(x), int(y), 'minitouch')

    def long_click_minitouch(self, x: int, y: int, seconds: float):
        """执行 `long click minitouch` 相关处理。"""
        ok = self._click_fn(int(x), int(y), f'long_click({seconds:.1f}s)')
        if ok:
            self.sleep(seconds)
        return ok

    def sleep(self, seconds: float):
        """执行 `sleep` 相关处理。"""
        return self._sleep_fn(float(seconds))

    def stuck_record_add(self, _button):
        """执行 `stuck record add` 相关处理。"""
        return None

    def stuck_record_clear(self):
        """执行 `stuck record clear` 相关处理。"""
        return None

    def click_record_clear(self):
        """执行点击动作并返回是否成功。"""
        return None

    def app_is_running(self) -> bool:
        """执行 `app is running` 相关处理。"""
        return not self._cancel_checker()

    def get_orientation(self):
        """获取 `orientation` 信息。"""
        return 0


