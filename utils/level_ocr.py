"""主界面等级 OCR 识别。"""

from __future__ import annotations

import re

import numpy as np

from utils.ocr_utils import OCRItem, OCRTool


class LevelOCR:
    """封装等级识别逻辑，支持传入 ROI。"""

    _shared_ocr: OCRTool | None = None

    def __init__(self):
        """初始化并复用 OCR 实例。"""
        if LevelOCR._shared_ocr is None:
            LevelOCR._shared_ocr = OCRTool()
        self.ocr = LevelOCR._shared_ocr

    @staticmethod
    def _normalize_text(text: str) -> str:
        """标准化 OCR 文本用于等级提取。"""
        raw = str(text or '')
        raw = raw.replace('：', ':').replace('（', '(').replace('）', ')')
        return ''.join(raw.split())

    @staticmethod
    def _extract_level(text: str, *, min_level: int, max_level: int) -> tuple[int | None, int]:
        """从文本提取等级，返回等级与优先级。"""
        normalized = LevelOCR._normalize_text(text)
        if not normalized:
            return None, 0

        patterns = [
            (re.compile(r'(?i)(?:lv|级别|等级)[:：]?(\d{1,3})'), 3),
            (re.compile(r'(\d{1,3})级'), 2),
            (re.compile(r'^(\d{1,3})$'), 1),
        ]
        for pattern, priority in patterns:
            matched = pattern.search(normalized)
            if matched is None:
                continue
            try:
                level = int(matched.group(1))
            except Exception:
                continue
            if min_level <= level <= max_level:
                return level, priority
        return None, 0

    @staticmethod
    def _sort_items(items: list[OCRItem]) -> list[OCRItem]:
        """按视觉阅读顺序排序 OCR item。"""
        return sorted(
            items,
            key=lambda item: (
                min(point[1] for point in item.box),
                min(point[0] for point in item.box),
            ),
        )

    def detect_level(
        self,
        img_bgr: np.ndarray,
        *,
        region: tuple[int, int, int, int] | None = None,
        min_level: int = 1,
        max_level: int = 99,
    ) -> tuple[int | None, float, str]:
        """识别等级并返回 `(level, score, raw_text)`。"""
        if img_bgr is None:
            return None, 0.0, ''

        lower = max(1, int(min_level))
        upper = max(lower, int(max_level))
        items = self.ocr.detect(img_bgr, region=region, scale=1.5, alpha=1.15, beta=0.0)
        if not items:
            return None, 0.0, ''

        ordered = self._sort_items(items)
        candidates: list[tuple[int, int, float, str]] = []
        for item in ordered:
            level, priority = self._extract_level(item.text, min_level=lower, max_level=upper)
            if level is None:
                continue
            candidates.append((priority, level, float(item.score), str(item.text)))

        if not candidates:
            merged_text = ''.join(self._normalize_text(item.text) for item in ordered)
            level, priority = self._extract_level(merged_text, min_level=lower, max_level=upper)
            if level is None:
                return None, 0.0, merged_text
            return level, 0.0, merged_text

        candidates.sort(key=lambda item: (item[0], item[2]), reverse=True)
        best = candidates[0]
        return best[1], best[2], best[3]
