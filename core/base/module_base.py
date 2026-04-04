"""精简版 NIKKE ModuleBase。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from core.vision.cv_detector import CVDetector
from core.base.button import Button
from core.base.timer import Timer


class ModuleBase:
    """提供按钮识别与点击的基础能力，供 UI/任务模块复用。"""
    def __init__(self, config: Any, detector: CVDetector, device):
        """注入配置、检测器与设备对象，并注册统一的按钮匹配入口。"""
        self.config = config
        self.cv_detector = detector
        self.device = device
        self.interval_timer: dict[str, Timer] = {}
        Button.set_match_provider(self._match_button)

    @staticmethod
    def _norm_offset(offset: int | tuple[int, int] | tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """将偏移参数统一为 `(left, top, right, bottom)` 形式。"""
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
        """执行单个按钮匹配，返回是否命中、命中区域与相似度。"""
        if image is None:
            return False, None, 0.0
        button.ensure_template()
        if button.image is None:
            return False, None, 0.0

        search_img = image
        off = (0, 0, 0, 0)
        if static:
            # 静态按钮：仅在按钮预设区域附近检索，减少误命中与计算量。
            off = self._norm_offset(offset)
            search_area = (
                int(button.area[0] + off[0]),
                int(button.area[1] + off[1]),
                int(button.area[2] + off[2]),
                int(button.area[3] + off[3]),
            )
            search_img = self._crop_like_pillow(image, search_area)

        # 对齐 NIKKE Button.match：直接模板匹配，不走 detector 多尺度分支。
        result = cv2.matchTemplate(button.image, search_img, cv2.TM_CCOEFF_NORMED)
        _, similarity, _, upper_left = cv2.minMaxLoc(result)
        hit = float(similarity) > float(threshold)
        if not hit:
            return False, None, float(similarity)

        if static:
            # 静态模式下将局部坐标回映射到全图逻辑坐标。
            dx = int(off[0] + upper_left[0])
            dy = int(off[1] + upper_left[1])
            area = (
                int(button._button[0] + dx),
                int(button._button[1] + dy),
                int(button._button[2] + dx),
                int(button._button[3] + dy),
            )
            return True, area, float(similarity)

        # 动态模式（全图检索）下直接使用匹配左上角与按钮原始尺寸还原区域。
        h = int(button.area[3] - button.area[1])
        w = int(button.area[2] - button.area[0])
        area = (
            int(upper_left[0]),
            int(upper_left[1]),
            int(upper_left[0] + w),
            int(upper_left[1] + h),
        )
        return True, area, float(similarity)

    @staticmethod
    def _crop_like_pillow(image: np.ndarray, area: tuple[int, int, int, int]) -> np.ndarray:
        """按 Pillow 的 `crop` 语义裁图，越界部分用黑边补齐。"""
        x1, y1, x2, y2 = [int(round(v)) for v in area]
        h, w = image.shape[:2]

        # 记录四边越界量，后续用 copyMakeBorder 补边。
        top = max(0, 0 - y1)
        bottom = max(0, y2 - h)
        left = max(0, 0 - x1)
        right = max(0, x2 - w)

        # 裁剪前先把坐标夹紧到有效像素范围。
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = max(0, x2)
        y2 = max(0, y2)

        cropped = image[y1:y2, x1:x2].copy()
        if top or bottom or left or right:
            cropped = cv2.copyMakeBorder(
                cropped,
                top,
                bottom,
                left,
                right,
                borderType=cv2.BORDER_CONSTANT,
                value=(0, 0, 0),
            )
        return cropped

    def appear_any(self, buttons, **kwargs):
        """依次检测多个按钮，任一命中即返回 `True`。"""
        for btn in buttons:
            if self.appear(btn, **kwargs):
                return True
        return False

    def appear_then_click_any(self, buttons, **kwargs):
        """依次检测并点击多个按钮，任一成功即返回 `True`。"""
        for btn in buttons:
            if self.appear_then_click(btn, **kwargs):
                return True
        return False

    def _button_interval_ready(self, key: str, interval: float) -> bool:
        """检查按钮点击节流是否到期。"""
        if interval <= 0:
            return True
        timer = self.interval_timer.get(key)
        if timer is None or abs(timer.limit - float(interval)) > 1e-6:
            timer = Timer(interval)
            self.interval_timer[key] = timer
        return timer.reached()

    def _button_interval_hit(self, key: str):
        """记录按钮刚触发一次点击，用于后续节流。"""
        timer = self.interval_timer.get(key)
        if timer:
            timer.reset()

    def appear(self, button: Button, offset=0, interval=0, threshold=None, static=True) -> bool:
        """判断按钮是否出现，支持静态区域匹配与全图匹配两种模式。"""
        image = self.device.image
        if image is None:
            return False

        key = button.name
        if interval and not self._button_interval_ready(key, float(interval)):
            return False

        if offset:
            # 有 offset 时使用模板匹配阈值（0~1）。
            t = float(threshold) if threshold is not None else 0.8
            hit = button.match(image, offset=offset, threshold=t, static=static)
        else:
            # 无 offset 时沿用按钮像素差分判定阈值（与 Button.appear_on 对齐）。
            t = float(threshold) if threshold is not None else 20.0
            hit = button.appear_on(image, threshold=t)

        if hit and interval:
            self._button_interval_hit(key)
        return bool(hit)

    def appear_then_click(
        self, button: Button, offset=0, click_offset=0, interval=0, threshold=None, static=True, screenshot=False
    ) -> bool:
        """按钮出现后执行点击；支持无模板按钮的直接点击模式。"""
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
        """重置一个或一组按钮的点击节流计时器。"""
        if isinstance(button, (list, tuple)):
            for b in button:
                self.interval_reset(b)
            return
        key = button.name if hasattr(button, 'name') else str(button)
        timer = self.interval_timer.get(key)
        if timer:
            timer.reset()


