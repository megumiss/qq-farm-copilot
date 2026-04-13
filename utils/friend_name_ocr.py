"""好友昵称 OCR 识别。"""

from __future__ import annotations

import numpy as np

from utils.ocr_provider import get_ocr_tool
from utils.ocr_utils import OCRTool


class FriendNameOCR:
    """封装好友昵称识别，支持注入 OCR 实例。"""

    def __init__(
        self,
        ocr_tool: OCRTool | None = None,
        *,
        scope: str = 'engine',
        key: str | None = None,
    ):
        """初始化 OCR 实例，优先使用注入对象。"""
        self.ocr = ocr_tool or get_ocr_tool(scope=scope, key=key)

    def detect_name(
        self,
        img_bgr: np.ndarray,
        *,
        region: tuple[int, int, int, int] | None = None,
    ) -> tuple[str, float]:
        """识别好友昵称并返回 `(name, score)`。"""
        if img_bgr is None:
            return '', 0.0
        text, score = self.ocr.detect_text(
            img_bgr,
            region=region,
            scale=1.4,
            alpha=1.15,
            beta=0.0,
            joiner='',
        )
        return str(text or '').strip(), float(score or 0.0)
