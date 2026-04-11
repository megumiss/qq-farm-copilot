"""ModuleBase。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from loguru import logger

from core.base.button import Button
from core.base.timer import Timer
from core.vision.cv_detector import CVDetector

if TYPE_CHECKING:
    from core.platform.device import Device


class ModuleBase:
    """提供按钮识别与点击的基础能力，供 UI/任务模块复用。"""

    def __init__(self, config: Any, detector: CVDetector, device: Device):
        """注入配置、检测器与设备对象，并注册统一的按钮匹配入口。"""
        self.config = config
        self.cv_detector = detector
        self.device: Device = device
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

        # 直接模板匹配
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

    def match_template_multi(
        self,
        button: Button,
        *,
        threshold: float = 0.8,
        roi: tuple[int, int, int, int] | None = None,
    ) -> list[Button]:
        """按模板名执行多命中识别，返回可直接点击的动态 Button 列表。"""
        image = self.device.image
        if image is None:
            return []

        template_name = str(getattr(button, 'template_name', '') or '').strip()
        if not template_name:
            return []

        roi_map = {template_name: roi} if roi is not None else None
        results = self.cv_detector.detect_templates(
            image,
            template_names=[template_name],
            default_threshold=float(threshold),
            roi_map=roi_map,
        )

        out: list[Button] = []
        for result in results:
            x1, y1, x2, y2 = result.bbox
            dynamic = Button(
                area=(x1, y1, x2, y2),
                color=button.color,
                button=(x1, y1, x2, y2),
                file=button.file,
                name=button.name,
            )
            out.append(dynamic)
        return out

    def match_template_result(
        self,
        button: Button,
        *,
        threshold: float = 0.8,
        roi: tuple[int, int, int, int] | None = None,
    ) -> Button | None:
        """按模板名匹配单个最佳结果。"""
        buttons = self.match_template_multi(button, threshold=threshold, roi=roi)
        if not buttons:
            return None
        return buttons[0]

    def match_icon_multi(
        self,
        icon_button: Button,
        *,
        threshold: float = 0.75,
        roi: tuple[int, int, int, int] | None = None,
    ) -> list[Button]:
        """icon_ 模板多命中识别（内部切换为 NIKKE `match_multi` 逻辑）。"""
        template_name = str(getattr(icon_button, 'template_name', '') or '')
        if not template_name.startswith('icon_'):
            return []

        image = self.device.image
        if image is None:
            return []

        icon_button.ensure_template()
        template = icon_button.image
        if template is None:
            return []

        search = image
        offset_x = 0
        offset_y = 0
        if roi is not None:
            x1, y1, x2, y2 = [int(v) for v in roi]
            sh, sw = image.shape[:2]
            x1 = max(0, min(x1, sw - 1))
            y1 = max(0, min(y1, sh - 1))
            x2 = max(x1 + 1, min(x2, sw))
            y2 = max(y1 + 1, min(y2, sh))
            if x2 <= x1 or y2 <= y1:
                return []
            search = image[y1:y2, x1:x2]
            offset_x = x1
            offset_y = y1

        th, tw = template.shape[:2]
        sh, sw = search.shape[:2]
        if th > sh or tw > sw:
            return []

        # 对齐 NIKKE Template.match_multi：matchTemplate + similarity 筛选。
        match_result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        points = np.array(np.where(match_result > float(threshold))).T[:, ::-1]
        grouped = self._group_points_like_nikke(points, threshold=3)

        out: list[Button] = []
        for point in grouped:
            x = int(point[0]) + offset_x
            y = int(point[1]) + offset_y
            area = (x, y, x + tw, y + th)
            dynamic = Button(
                area=area,
                color=icon_button.color,
                button=area,
                file=icon_button.file,
                name=icon_button.name,
            )
            out.append(dynamic)
        return out

    @staticmethod
    def _group_points_like_nikke(points: np.ndarray, threshold: int = 3) -> np.ndarray:
        """按 NIKKE Points.group 规则做点聚类（曼哈顿距离）。"""
        if points is None or len(points) == 0:
            return np.empty((0, 2), dtype=int)

        grouped: list[list[int]] = []
        remaining = np.array(points, dtype=int)
        if remaining.ndim == 1:
            remaining = np.array([remaining], dtype=int)
        if len(remaining) == 1:
            return np.array([remaining[0]], dtype=int)

        while len(remaining):
            p0 = remaining[0]
            p1 = remaining[1:]
            distance = np.sum(np.abs(p1 - p0), axis=1)
            merged = np.append(p1[distance <= threshold], [p0], axis=0)
            mean_point = np.round(np.mean(merged, axis=0)).astype(int).tolist()
            grouped.append(mean_point)
            remaining = p1[distance > threshold]

        return np.array(grouped, dtype=int)

    def match_icon_result(
        self,
        icon_button: Button,
        *,
        threshold: float = 0.75,
        roi: tuple[int, int, int, int] | None = None,
    ) -> Button | None:
        """icon_ 模板单结果识别。"""
        buttons = self.match_icon_multi(icon_button, threshold=threshold, roi=roi)
        if not buttons:
            return None
        return buttons[0]

    def appear_icon(
        self,
        icon_button: Button,
        *,
        threshold: float = 0.75,
        roi: tuple[int, int, int, int] | None = None,
    ) -> bool:
        """icon_ 模板是否出现。"""
        return self.match_icon_result(icon_button, threshold=threshold, roi=roi) is not None

    @staticmethod
    def sort_buttons_by_location(buttons: list[Button], horizontal: bool = True) -> list[Button]:
        """按按钮中心坐标排序。horizontal=True 时优先按 x，再按 y。"""
        if horizontal:
            return sorted(buttons, key=lambda b: (b.location[0], b.location[1]))
        return sorted(buttons, key=lambda b: (b.location[1], b.location[0]))

    @staticmethod
    def filter_buttons_in_area(
        buttons: list[Button],
        *,
        x_range: tuple[int, int] | None = None,
        y_range: tuple[int, int] | None = None,
    ) -> list[Button]:
        """按区域范围过滤按钮（使用 area 判定）。"""
        filtered: list[Button] = []
        for btn in buttons:
            x1, y1, x2, y2 = btn.area
            if x_range is not None and (x1 < x_range[0] or x2 > x_range[1]):
                continue
            if y_range is not None and (y1 < y_range[0] or y2 > y_range[1]):
                continue
            filtered.append(btn)
        return filtered

    def match_icon_and_click(
        self,
        icon_button: Button,
        *,
        threshold: float = 0.75,
        roi: tuple[int, int, int, int] | None = None,
        interval: float = 1,
        horizontal: bool = True,
        x_range: tuple[int, int] | None = None,
        y_range: tuple[int, int] | None = None,
    ) -> bool:
        """识别 icon_ 多命中并点击排序后的第一个结果。"""
        key = f'icon::{icon_button.name}'
        if interval and not self._button_interval_ready(key, float(interval)):
            return False

        buttons = self.match_icon_multi(icon_button, threshold=threshold, roi=roi)
        buttons = self.filter_buttons_in_area(buttons, x_range=x_range, y_range=y_range)
        buttons = self.sort_buttons_by_location(buttons, horizontal=horizontal)
        if not buttons:
            return False

        ok = bool(self.device.click_button(buttons[0]))
        if ok and interval:
            self._button_interval_hit(key)
        return ok

    def appear_then_click_icon(
        self,
        icon_button: Button,
        *,
        threshold: float = 0.75,
        roi: tuple[int, int, int, int] | None = None,
        interval: float = 1,
        horizontal: bool = True,
        x_range: tuple[int, int] | None = None,
        y_range: tuple[int, int] | None = None,
    ) -> bool:
        """icon_ 模板出现后点击（模板式接口命名）。"""
        return self.match_icon_and_click(
            icon_button,
            threshold=threshold,
            roi=roi,
            interval=interval,
            horizontal=horizontal,
            x_range=x_range,
            y_range=y_range,
        )

    def appear_then_click_any(self, buttons, interval=1, **kwargs):
        """依次检测并点击多个按钮，任一成功即返回 `True`。"""
        params = dict(kwargs)
        params.setdefault('interval', interval)
        for btn in buttons:
            if self.appear_then_click(btn, **params):
                return True
        return False

    def _button_interval_ready(self, key: str, interval: float) -> bool:
        """检查按钮点击节流是否到期。"""
        if interval <= 0:
            return True
        timer = self.interval_timer.get(key)
        if timer is None:
            self.interval_timer[key] = Timer(interval)
            return True
        if abs(timer.limit - float(interval)) > 1e-6:
            timer = Timer(interval)
            self.interval_timer[key] = timer
            return True
        if not timer.started():
            return True
        return timer.reached()

    def _button_interval_hit(self, key: str):
        """记录按钮刚触发一次点击，用于后续节流。"""
        timer = self.interval_timer.get(key)
        if timer:
            timer.reset()

    def appear(self, button: Button, offset=0, threshold=0.74, static=True) -> bool:
        """判断按钮是否出现，支持静态区域匹配与全图匹配两种模式。"""
        self.device.stuck_record_add(button)
        image = self.device.image
        if image is None:
            return False

        if offset:
            # 有 offset 时使用模板匹配阈值（0~1）。
            t = float(threshold) if threshold is not None else 0.8
            hit = button.match(image, offset=offset, threshold=t, static=static)
        else:
            # 无 offset 时沿用按钮像素差分判定阈值
            t = float(threshold) if threshold is not None else 20.0
            hit = button.appear_on(image, threshold=t)

        return bool(hit)

    def appear_location(
        self,
        button: Button,
        offset=0,
        threshold=0.74,
        static=True,
    ) -> tuple[int, int] | None:
        """判断按钮是否出现并返回中心坐标（对齐 NIKKE appear_location 语义）。"""
        self.device.stuck_record_add(button)
        image = self.device.image
        if image is None:
            return None

        if offset:
            t = float(threshold) if threshold is not None else 0.8
            hit = button.match(image, offset=offset, threshold=t, static=static)
        else:
            t = float(threshold) if threshold is not None else 20.0
            hit = button.appear_on(image, threshold=t)

        if not hit:
            return None

        button_offset = getattr(button, '_button_offset', None)
        if not button_offset:
            logger.warning(f"Button '{button.name}' matched but no offset recorded")
            return None

        x1, y1, x2, y2 = button_offset
        return (int(x1 + x2) // 2, int(y1 + y2) // 2)

    def appear_then_click(
        self, button: Button, offset=0, click_offset=0, interval=1, threshold=0.74, static=True
    ) -> bool:
        """按钮出现后执行点击；支持无模板按钮的直接点击模式。"""
        key = button.name
        if interval and not self._button_interval_ready(key, float(interval)):
            return False

        # 对无模板按钮（如点击空白处）直接点击
        if not button.file:
            ok = bool(self.device.click_button(button, click_offset))
            if ok and interval:
                self._button_interval_hit(key)
            return ok

        hit = self.appear(button=button, offset=offset, threshold=threshold, static=static)
        if not hit:
            return False
        ok = bool(self.device.click_button(button, click_offset))
        if ok and interval:
            self._button_interval_hit(key)
        return ok

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
