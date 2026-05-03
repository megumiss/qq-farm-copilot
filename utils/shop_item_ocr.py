"""Shop item OCR locator.

Detects item cards from a full screenshot, runs OCR once on the full image,
then binds OCR text blocks into each card to resolve item names and centers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import cv2
import numpy as np
from loguru import logger

from models.game_data import get_crop_names
from utils.ocr_provider import get_ocr_tool
from utils.ocr_utils import OCRItem, OCRTool


@dataclass
class ShopCard:
    """封装 `ShopCard` 相关的数据与行为。"""

    x: int
    y: int
    w: int
    h: int
    area: int

    @property
    def x2(self) -> int:
        """返回右边界坐标。"""
        return self.x + self.w

    @property
    def y2(self) -> int:
        """返回下边界坐标。"""
        return self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        """返回中心点坐标。"""
        return self.x + self.w // 2, self.y + self.h // 2


@dataclass
class ShopItem:
    """封装 `ShopItem` 相关的数据与行为。"""

    name: str
    raw_name: str
    ocr_score: float
    name_similarity: float
    center_x: int
    center_y: int
    bbox: tuple[int, int, int, int]


@dataclass
class ShopItemMatch:
    """封装 `ShopItemMatch` 相关的数据与行为。"""

    target: ShopItem | None
    best: ShopItem | None
    best_similarity: float
    parsed_items: list[ShopItem]


class ShopItemOCR:
    """封装 `ShopItemOCR` 相关的数据与行为。"""

    def __init__(
        self,
        vocab: list[str] | None = None,
        ocr_tool: OCRTool | None = None,
        *,
        scope: str = 'engine',
        key: str | None = None,
    ):
        """初始化对象并准备运行所需状态。"""
        self.ocr = ocr_tool or get_ocr_tool(scope=scope, key=key)
        base_vocab = vocab if vocab else get_crop_names()
        self.vocab = sorted({self._norm_name(v) for v in base_vocab if v})
        self._norm_to_original = {self._norm_name(v): v for v in base_vocab if v}

    @staticmethod
    def _clean_text(text: str) -> str:
        """执行 `clean text` 相关处理。"""
        return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9（）()]+', '', text).strip()

    @staticmethod
    def _norm_name(text: str) -> str:
        """执行 `norm name` 相关处理。"""
        t = ShopItemOCR._clean_text(text)
        t = t.replace('（', '(').replace('）', ')')
        t = t.replace('詹菇', '蘑菇')
        t = t.replace('弥猴桃', '猕猴桃')
        return t

    @staticmethod
    def _iou(a: ShopCard, b: ShopCard) -> float:
        """执行 `iou` 相关处理。"""
        x1 = max(a.x, b.x)
        y1 = max(a.y, b.y)
        x2 = min(a.x2, b.x2)
        y2 = min(a.y2, b.y2)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        union = a.area + b.area - inter
        return inter / union if union > 0 else 0.0

    @staticmethod
    def detect_shop_cards(img_bgr: np.ndarray) -> list[ShopCard]:
        """检测 `shop_cards` 并输出识别结果。"""
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edge = cv2.Canny(blur, 50, 150)
        contours, _ = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        candidates: list[ShopCard] = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            area = w * h
            if h == 0:
                continue
            ar = w / h
            if 25000 <= area <= 42000 and 0.90 <= ar <= 1.05:
                candidates.append(ShopCard(x, y, w, h, area))

        candidates.sort(key=lambda r: r.area, reverse=True)
        kept: list[ShopCard] = []
        for r in candidates:
            if all(ShopItemOCR._iou(r, k) < 0.35 for k in kept):
                kept.append(r)

        kept.sort(key=lambda r: (r.y, r.x))
        return kept

    @staticmethod
    def _point_in_card(x: float, y: float, c: ShopCard) -> bool:
        """执行 `point in card` 相关处理。"""
        return c.x <= x <= c.x2 and c.y <= y <= c.y2

    @staticmethod
    def _item_center(ocr_item: OCRItem) -> tuple[float, float]:
        """执行 `item center` 相关处理。"""
        xs = [p[0] for p in ocr_item.box]
        ys = [p[1] for p in ocr_item.box]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    @staticmethod
    def _item_bbox(ocr_item: OCRItem) -> tuple[int, int, int, int]:
        """执行 `item bbox` 相关处理。"""
        xs = [p[0] for p in ocr_item.box]
        ys = [p[1] for p in ocr_item.box]
        return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))

    def _resolve_name(self, text: str) -> tuple[str, float]:
        """解析并计算 `name` 的最终结果。"""
        raw = self._norm_name(text)
        if not raw:
            return '', 0.0
        if raw in self.vocab:
            return self._norm_to_original.get(raw, raw), 1.0

        starts = [v for v in self.vocab if v.startswith(raw)]
        if len(starts) == 1:
            name = self._norm_to_original.get(starts[0], starts[0])
            return name, SequenceMatcher(None, raw, starts[0]).ratio()

        best_name = raw
        best_score = 0.0
        for v in self.vocab:
            score = SequenceMatcher(None, raw, v).ratio()
            if score > best_score:
                best_score = score
                best_name = v
        if best_score >= 0.70:
            return self._norm_to_original.get(best_name, best_name), best_score
        return raw, best_score

    def _pick_card_items(self, all_items: list[OCRItem], card: ShopCard) -> list[OCRItem]:
        """执行 `pick card items` 相关处理。"""
        out: list[OCRItem] = []
        for it in all_items:
            cx, cy = self._item_center(it)
            if self._point_in_card(cx, cy, card):
                out.append(it)
        return out

    def _parse_card_name(self, card_items: list[OCRItem]) -> tuple[str, str, float, float]:
        # name, raw_name, ocr_score, vocab_similarity
        """解析 `card_name` 并返回结构化结果。"""
        names: list[tuple[str, str, float, float]] = []
        for it in card_items:
            raw = self._norm_name(it.text)
            if not raw:
                continue
            if re.match(r'^\d+品$', raw):
                continue
            if re.match(r'^\d+$', raw):
                continue
            if not re.search(r'[\u4e00-\u9fff]', raw):
                continue

            resolved, sim = self._resolve_name(raw)
            names.append((resolved, raw, float(it.score), float(sim)))

        if not names:
            return '', '', 0.0, 0.0

        names.sort(key=lambda x: (x[3], x[2], len(x[0])), reverse=True)
        return names[0]

    def detect_items(self, img_bgr: np.ndarray) -> list[ShopItem]:
        """检测 `items` 并输出识别结果。"""
        cards = self.detect_shop_cards(img_bgr)
        all_items = self.ocr.detect(img_bgr, scale=1.4, alpha=1.15, beta=0.0)
        if not all_items:
            return []

        if not cards:
            # Fallback: no card contours, match direct OCR text boxes.
            fallback: list[ShopItem] = []
            for it in all_items:
                text = self._norm_name(it.text)
                if not text or not re.search(r'[\u4e00-\u9fff]', text):
                    continue
                name, sim = self._resolve_name(text)
                if not name:
                    continue
                cx, cy = self._item_center(it)
                fallback.append(
                    ShopItem(
                        name=name,
                        raw_name=text,
                        ocr_score=float(it.score),
                        name_similarity=float(sim),
                        center_x=int(cx),
                        center_y=int(cy),
                        bbox=self._item_bbox(it),
                    )
                )
            return fallback

        # Whole-image OCR, then card binding.
        results: list[ShopItem] = []
        for card in cards:
            card_items = self._pick_card_items(all_items, card)
            name, raw_name, ocr_score, sim = self._parse_card_name(card_items)
            if not name:
                continue
            cx, cy = card.center
            results.append(
                ShopItem(
                    name=name,
                    raw_name=raw_name,
                    ocr_score=ocr_score,
                    name_similarity=sim,
                    center_x=int(cx),
                    center_y=int(cy),
                    bbox=(card.x, card.y, card.x2, card.y2),
                )
            )
        return results

    def find_item(self, img_bgr: np.ndarray, target_name: str, min_similarity: float = 0.70) -> ShopItemMatch:
        """执行 `find item` 相关处理。"""
        parsed = self.detect_items(img_bgr)
        parsed_debug = '; '.join(f'{item.name}/{item.raw_name}@({item.center_x},{item.center_y})' for item in parsed)
        logger.debug("OCR识别内容: target='{}' | items={}", target_name, parsed_debug or '[]')
        if not parsed:
            return ShopItemMatch(target=None, best=None, best_similarity=0.0, parsed_items=[])

        target_norm = self._norm_name(target_name)
        best: ShopItem | None = None
        best_similarity = 0.0
        exact: ShopItem | None = None

        for item in parsed:
            item_norm = self._norm_name(item.name)
            raw_norm = self._norm_name(item.raw_name)
            sim = max(
                SequenceMatcher(None, target_norm, item_norm).ratio(),
                SequenceMatcher(None, target_norm, raw_norm).ratio(),
            )
            if item_norm == target_norm:
                exact = item
                best_similarity = 1.0
                break
            if sim > best_similarity:
                best_similarity = sim
                best = item

        if exact:
            logger.info(
                "OCR匹配成功: target='{}' | match='{}' raw='{}' | center=({}, {})",
                target_name,
                exact.name,
                exact.raw_name,
                exact.center_x,
                exact.center_y,
            )
            return ShopItemMatch(target=exact, best=exact, best_similarity=1.0, parsed_items=parsed)
        if best and best_similarity >= min_similarity:
            logger.info(
                "OCR匹配成功: target='{}' | match='{}' raw='{}' | center=({}, {})",
                target_name,
                best.name,
                best.raw_name,
                best.center_x,
                best.center_y,
            )
            return ShopItemMatch(target=best, best=best, best_similarity=best_similarity, parsed_items=parsed)
        return ShopItemMatch(target=None, best=best, best_similarity=best_similarity, parsed_items=parsed)
