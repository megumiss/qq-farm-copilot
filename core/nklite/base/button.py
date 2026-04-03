"""精简版 NIKKE Button。"""

from __future__ import annotations

import os
from functools import cached_property
from typing import Callable

import cv2
import numpy as np
from loguru import logger

MatchProvider = Callable[
    ['Button', np.ndarray, int | tuple[int, int, int, int] | tuple[int, int], float, bool],
    tuple[bool, tuple[int, int, int, int] | None, float],
]


class Button:
    _match_provider: MatchProvider | None = None

    def __init__(self, area, color, button, file=None, name=None):
        self.raw_area = area
        self.raw_color = color
        self.raw_button = button
        self.raw_file = file
        self.raw_name = name

        self._button_offset: tuple[int, int, int, int] | None = None
        self._match_init = False
        self.image: np.ndarray | None = None

    @classmethod
    def set_match_provider(cls, provider: MatchProvider | None):
        cls._match_provider = provider

    @cached_property
    def name(self) -> str:
        if self.raw_name:
            return str(self.raw_name)
        if self.file:
            return os.path.splitext(os.path.basename(str(self.file)))[0]
        return 'BUTTON'

    @cached_property
    def file(self):
        return self._parse_property(self.raw_file)

    @cached_property
    def area(self) -> tuple[int, int, int, int]:
        return self._to_area(self._parse_property(self.raw_area))

    @cached_property
    def color(self) -> tuple[int, int, int]:
        raw = self._parse_property(self.raw_color)
        if isinstance(raw, (list, tuple)) and len(raw) == 3:
            return int(raw[0]), int(raw[1]), int(raw[2])
        return 0, 0, 0

    @cached_property
    def _button(self) -> tuple[int, int, int, int]:
        return self._to_area(self._parse_property(self.raw_button))

    @property
    def button(self) -> tuple[int, int, int, int]:
        return self._button_offset or self._button

    @property
    def location(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.button
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def template_name(self) -> str:
        if self.raw_name and str(self.raw_name).startswith(('btn_', 'icon_', 'land_', 'seed_')):
            return str(self.raw_name)
        file_value = str(self.file or '')
        stem = os.path.splitext(os.path.basename(file_value))[0]
        if stem:
            return stem
        return str(self.raw_name or '')

    def _parse_property(self, value):
        if isinstance(value, dict):
            for key in ('zh-CN', 'zh_cn', 'default', 'en-US'):
                if key in value:
                    return value[key]
            return next(iter(value.values()))
        return value

    @staticmethod
    def _to_area(raw) -> tuple[int, int, int, int]:
        if isinstance(raw, (list, tuple)) and len(raw) == 4:
            x1, y1, x2, y2 = [int(v) for v in raw]
            if x2 <= x1:
                x2 = x1 + 1
            if y2 <= y1:
                y2 = y1 + 1
            return x1, y1, x2, y2
        return 0, 0, 1, 1

    def __str__(self):
        return self.name

    def ensure_template(self):
        if self._match_init:
            return
        if self.file and os.path.exists(str(self.file)):
            image = cv2.imread(str(self.file), cv2.IMREAD_COLOR)
            if image is not None:
                self.image = image
        self._match_init = True

    def match(self, image, offset=30, threshold=0.85, static=True) -> bool:
        if Button._match_provider is None:
            logger.debug(f'Button match provider missing: {self.name}')
            return False
        hit, area, similarity = Button._match_provider(
            self,
            image,
            offset,
            float(threshold),
            bool(static),
        )
        if area is not None:
            self._button_offset = area
        logger.debug(
            'Button: {}, similarity: {:.3f}, threshold: {:.3f}, hit: {}',
            self.name,
            similarity,
            float(threshold),
            bool(hit),
        )
        return bool(hit)

    def match_with_scale(self, image, threshold=0.85, scale_range=(0.9, 1.1), scale_step=0.02):
        # 精简版保持接口一致，先复用基础 match 行为。
        _ = scale_range, scale_step
        return self.match(image, offset=30, threshold=threshold, static=False)

    def appear_on(self, image, threshold=10) -> bool:
        x1, y1, x2, y2 = self.area
        h, w = image.shape[:2]
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            return False
        bgr = roi.mean(axis=(0, 1))
        color_bgr = np.array([self.color[2], self.color[1], self.color[0]], dtype=np.float32)
        diff = float(np.linalg.norm(bgr.astype(np.float32) - color_bgr))
        hit = diff <= float(threshold)
        logger.debug(
            'Button: {}, color_diff: {:.3f}, threshold: {:.3f}, hit: {}',
            self.name,
            diff,
            float(threshold),
            bool(hit),
        )
        return hit

    def match_several(self, image, offset=30, threshold=0.85, static=True) -> list[dict]:
        if not self.match(image=image, offset=offset, threshold=threshold, static=static):
            return []
        return [{'area': self.button, 'location': self.location}]
