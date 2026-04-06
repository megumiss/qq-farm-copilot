"""Button。"""

from __future__ import annotations

import os
import weakref
from functools import cached_property
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from loguru import logger

from utils.template_paths import normalize_template_platform

MatchProvider = Callable[
    ['Button', np.ndarray, int | tuple[int, int, int, int] | tuple[int, int], float, bool],
    tuple[bool, tuple[int, int, int, int] | None, float],
]


class Button:
    """封装 `Button` 相关的数据与行为。"""

    _match_provider: MatchProvider | None = None
    _template_platform: str = 'qq'
    _instances: weakref.WeakSet = weakref.WeakSet()

    def __init__(self, area, color, button, file=None, name=None):
        """初始化对象并准备运行所需状态。"""
        self.raw_area = area
        self.raw_color = color
        self.raw_button = button
        self.raw_file = file
        self.raw_name = name

        self._button_offset: tuple[int, int, int, int] | None = None
        self._last_score: float = 0.0
        self._last_metric: str = 'similarity'
        self._match_init = False
        self.image: np.ndarray | None = None
        Button._instances.add(self)

    @classmethod
    def set_match_provider(cls, provider: MatchProvider | None):
        """设置 `match_provider` 参数。"""
        cls._match_provider = provider

    @classmethod
    def set_template_platform(cls, platform: str | None):
        """设置模板平台并清理已缓存模板，确保后续匹配使用新平台资源。"""
        normalized = normalize_template_platform(platform)
        if cls._template_platform == normalized:
            return
        cls._template_platform = normalized
        for inst in list(cls._instances):
            try:
                inst._match_init = False
                inst.image = None
                inst._button_offset = None
            except Exception:
                continue

    @cached_property
    def name(self) -> str:
        """返回对象名称。"""
        if self.raw_name:
            return str(self.raw_name)
        if self.file:
            return os.path.splitext(os.path.basename(str(self.file)))[0]
        return 'BUTTON'

    @cached_property
    def file(self):
        """返回模板文件路径。"""
        return self._parse_property(self.raw_file)

    @cached_property
    def area(self) -> tuple[int, int, int, int]:
        """返回按钮区域坐标。"""
        return self._to_area(self._parse_property(self.raw_area))

    @cached_property
    def color(self) -> tuple[int, int, int]:
        """返回按钮颜色采样值。"""
        raw = self._parse_property(self.raw_color)
        if isinstance(raw, (list, tuple)) and len(raw) == 3:
            return int(raw[0]), int(raw[1]), int(raw[2])
        return 0, 0, 0

    @cached_property
    def _button(self) -> tuple[int, int, int, int]:
        """返回按钮原始点击区域。"""
        return self._to_area(self._parse_property(self.raw_button))

    @property
    def button(self) -> tuple[int, int, int, int]:
        """返回按钮当前点击区域（含偏移）。"""
        return self._button_offset or self._button

    @property
    def location(self) -> tuple[int, int]:
        """返回按钮中心坐标。"""
        x1, y1, x2, y2 = self.button
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def template_name(self) -> str:
        """返回用于匹配的模板名称。"""
        if self.raw_name and str(self.raw_name).startswith(('btn_', 'icon_', 'land_', 'seed_')):
            return str(self.raw_name)
        file_value = str(self.file or '')
        stem = os.path.splitext(os.path.basename(file_value))[0]
        if stem:
            return stem
        return str(self.raw_name or '')

    def _parse_property(self, value):
        """解析属性值：字典类型仅按当前平台取值。"""
        if isinstance(value, dict):
            platform = normalize_template_platform(Button._template_platform)
            if platform in value:
                return value[platform]
            keys = ','.join(str(k) for k in value.keys())
            raise KeyError(
                f"Button property missing platform '{platform}' key (name={self.raw_name}, available=[{keys}])"
            )
        return value

    @staticmethod
    def _to_area(raw) -> tuple[int, int, int, int]:
        """将输入值标准化为区域坐标 `(x1,y1,x2,y2)`。"""
        if isinstance(raw, (list, tuple)) and len(raw) == 4:
            x1, y1, x2, y2 = [int(v) for v in raw]
            if x2 <= x1:
                x2 = x1 + 1
            if y2 <= y1:
                y2 = y1 + 1
            return x1, y1, x2, y2
        return 0, 0, 1, 1

    def __str__(self):
        """返回对象的可读字符串表示。"""
        return self.name

    def ensure_template(self):
        """按当前平台字段加载模板图片。"""
        if self._match_init:
            return
        file_raw = self._parse_property(self.raw_file)
        file_text = str(file_raw or '').strip()
        if file_text:
            file_path = Path(file_text)
            if not file_path.is_absolute():
                file_path = Path(__file__).resolve().parents[2] / file_text
            file_path_str = str(file_path)
        else:
            file_path_str = ''

        if file_path_str and os.path.exists(file_path_str):
            # 使用 imdecode 兼容中文路径
            image = cv2.imdecode(np.fromfile(file_path_str, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if image is not None:
                if image.ndim == 2:
                    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
                elif image.shape[2] > 3:
                    image = image[:, :, :3]
                self.image = self._crop_like_pillow(image, self.area)
        self._match_init = True

    @staticmethod
    def _crop_like_pillow(image: np.ndarray, area: tuple[int, int, int, int]) -> np.ndarray:
        """超出边界部分用黑色补齐。"""
        x1, y1, x2, y2 = [int(round(v)) for v in area]
        h, w = image.shape[:2]

        top = max(0, 0 - y1)
        bottom = max(0, y2 - h)
        left = max(0, 0 - x1)
        right = max(0, x2 - w)

        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = max(0, x2)
        y2 = max(0, y2)

        cropped = image[y1:y2, x1:x2].copy()
        if top or bottom or left or right:
            cropped = cv2.copyMakeBorder(
                cropped, top, bottom, left, right, borderType=cv2.BORDER_CONSTANT, value=(0, 0, 0)
            )
        return cropped

    def match(self, image, offset=30, threshold=0.85, static=True) -> bool:
        """执行 `目标` 匹配判定。"""
        if Button._match_provider is None:
            logger.debug(f'Button match provider missing: {self.name}')
            return False
        hit, area, similarity = Button._match_provider(self, image, offset, float(threshold), bool(static))
        self._last_score = float(similarity)
        self._last_metric = 'similarity'
        if area is not None:
            self._button_offset = area
        logger.debug(f'按钮: {self.name}, 相似度: {similarity}, 阈值: {float(threshold)}, 命中: {bool(hit)}')
        return bool(hit)

    def match_with_scale(self, image, threshold=0.85, scale_range=(0.9, 1.1), scale_step=0.02):
        """匹配 `with_scale` 条件。"""
        _ = scale_range, scale_step
        return self.match(image, offset=30, threshold=threshold, static=False)

    def appear_on(self, image, threshold=10) -> bool:
        """执行按钮出现判定并返回命中结果。"""
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
        self._last_score = diff
        self._last_metric = 'color_diff'
        hit = diff <= float(threshold)
        logger.debug(f'按钮: {self.name}, 色差: {diff}, 阈值: {float(threshold)}, 命中: {bool(hit)}')
        return hit

    def match_several(self, image, offset=30, threshold=0.85, static=True) -> list[dict]:
        """匹配 `several` 条件。"""
        if not self.match(image=image, offset=offset, threshold=threshold, static=static):
            return []
        return [{'area': self.button, 'location': self.location}]
