"""nklite 设备适配：桥接现有 BotEngine 截图与点击。"""

from __future__ import annotations

import time
from typing import Callable

import numpy as np

from core.nklite.base.button import Button


class NKLiteDevice:
    def __init__(
        self,
        screenshot_fn: Callable[[tuple[int, int, int, int]], np.ndarray | None],
        click_fn: Callable[[int, int, str], bool],
        sleep_fn: Callable[[float], bool],
        cancel_checker: Callable[[], bool],
    ):
        self._screenshot_fn = screenshot_fn
        self._click_fn = click_fn
        self._sleep_fn = sleep_fn
        self._cancel_checker = cancel_checker
        self.rect: tuple[int, int, int, int] | None = None
        self.image: np.ndarray | None = None

    def set_rect(self, rect: tuple[int, int, int, int]):
        self.rect = rect

    def screenshot(self):
        if self.rect is None:
            self.image = None
            return None
        self.image = self._screenshot_fn(self.rect)
        return self.image

    def set_image(self, image: np.ndarray | None):
        self.image = image

    def click(self, button: Button, click_offset=0):
        _ = click_offset
        x, y = button.location
        return self._click_fn(x, y, button.name)

    def click_minitouch(self, x: int, y: int):
        return self._click_fn(int(x), int(y), 'minitouch')

    def long_click_minitouch(self, x: int, y: int, seconds: float):
        ok = self._click_fn(int(x), int(y), f'long_click({seconds:.1f}s)')
        if ok:
            self.sleep(seconds)
        return ok

    def sleep(self, seconds: float):
        return self._sleep_fn(float(seconds))

    def stuck_record_add(self, _button):
        return None

    def stuck_record_clear(self):
        return None

    def click_record_clear(self):
        return None

    def app_is_running(self) -> bool:
        return not self._cancel_checker()

    def get_orientation(self):
        return 0
