"""精简版 NIKKE ModuleBase。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from core.cv_detector import CVDetector
from core.nklite.base.button import Button
from core.nklite.base.timer import Timer


class ModuleBase:
    def __init__(self, config: Any, detector: CVDetector, device):
        self.config = config
        self.cv_detector = detector
        self.device = device
        self.interval_timer: dict[str, Timer] = {}
        Button.set_match_provider(self._match_button)

    @staticmethod
    def _norm_offset(offset: int | tuple[int, int] | tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        if isinstance(offset, tuple):
            if len(offset) == 2:
                return -int(offset[0]), -int(offset[1]), int(offset[0]), int(offset[1])
            if len(offset) == 4:
                return int(offset[0]), int(offset[1]), int(offset[2]), int(offset[3])
        value = int(offset)
        return -3, -value, 3, value

    def _match_button(
        self,
        button: Button,
        image: np.ndarray,
        offset: int | tuple[int, int] | tuple[int, int, int, int],
        threshold: float,
        static: bool,
    ) -> tuple[bool, tuple[int, int, int, int] | None, float]:
        if image is None:
            return False, None, 0.0
        name = button.template_name
        tpl = self.cv_detector._templates_by_name.get(name)
        if tpl is None:
            return False, None, 0.0

        gray_screen = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        search_img = image
        search_gray = gray_screen
        dx = 0
        dy = 0

        if static:
            off = self._norm_offset(offset)
            x1, y1, x2, y2 = button.area
            sx1 = x1 + off[0]
            sy1 = y1 + off[1]
            sx2 = x2 + off[2]
            sy2 = y2 + off[3]
            h, w = image.shape[:2]
            sx1 = max(0, min(sx1, w - 1))
            sy1 = max(0, min(sy1, h - 1))
            sx2 = max(sx1 + 1, min(sx2, w))
            sy2 = max(sy1 + 1, min(sy2, h))
            search_img = image[sy1:sy2, sx1:sx2]
            search_gray = gray_screen[sy1:sy2, sx1:sx2]
            dx, dy = sx1, sy1

        matches, best_score = self.cv_detector._match_template_with_best(
            search_img,
            search_gray,
            tpl,
            float(threshold),
        )
        if not matches:
            return False, None, float(best_score)

        best = max(matches, key=lambda m: m.confidence)
        if static:
            center_x = best.x + dx
            center_y = best.y + dy
        else:
            center_x = best.x
            center_y = best.y
        area = (
            int(center_x - best.w // 2),
            int(center_y - best.h // 2),
            int(center_x + best.w // 2),
            int(center_y + best.h // 2),
        )
        return True, area, float(best_score)

    def appear_any(self, buttons, **kwargs):
        for btn in buttons:
            if self.appear(btn, **kwargs):
                return True
        return False

    def appear_then_click_any(self, buttons, **kwargs):
        for btn in buttons:
            if self.appear_then_click(btn, **kwargs):
                return True
        return False

    def _button_interval_ready(self, key: str, interval: float) -> bool:
        if interval <= 0:
            return True
        timer = self.interval_timer.get(key)
        if timer is None or abs(timer.limit - float(interval)) > 1e-6:
            timer = Timer(interval)
            self.interval_timer[key] = timer
        return timer.reached()

    def _button_interval_hit(self, key: str):
        timer = self.interval_timer.get(key)
        if timer:
            timer.reset()

    def appear(self, button: Button, offset=0, interval=0, threshold=None, static=True) -> bool:
        image = self.device.image
        if image is None:
            return False

        key = button.name
        if interval and not self._button_interval_ready(key, float(interval)):
            return False

        if offset:
            t = float(threshold) if threshold is not None else 0.8
            hit = button.match(image, offset=offset, threshold=t, static=static)
        else:
            t = float(threshold) if threshold is not None else 20.0
            hit = button.appear_on(image, threshold=t)

        if hit and interval:
            self._button_interval_hit(key)
        return bool(hit)

    def appear_then_click(
        self, button: Button, offset=0, click_offset=0, interval=0, threshold=None, static=True, screenshot=False
    ) -> bool:
        # 对无模板按钮（如点击空白处）直接点击，保持 NIKKE 式导航可用。
        if not button.file:
            return bool(self.device.click(button, click_offset))

        hit = self.appear(button=button, offset=offset, interval=interval, threshold=threshold, static=static)
        if not hit:
            return False
        if screenshot:
            self.device.screenshot()
        return bool(self.device.click(button, click_offset))

    def interval_reset(self, button):
        if isinstance(button, (list, tuple)):
            for b in button:
                self.interval_reset(b)
            return
        key = button.name if hasattr(button, 'name') else str(button)
        timer = self.interval_timer.get(key)
        if timer:
            timer.reset()
