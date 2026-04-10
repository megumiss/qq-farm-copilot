"""Seed number-box detector (contour-only)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from loguru import logger


@dataclass(frozen=True)
class NumberBox:
    """Single number box info."""

    order: int
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    size: tuple[int, int]


class NumberBoxDetector:
    """Detect number boxes from seed bar area by contour geometry."""

    def __init__(
        self,
        *,
        x_min_px: int = 40,
        x_max_px: int = 500,
        y_min_px: int = 400,
        y_max_px: int = 750,
        seed_bar_search_y_min_px: int = 430,
        seed_bar_search_y_max_px: int = 860,
        min_area: int = 260,
        max_area: int = 12000,
        min_w: int = 22,
        max_w: int = 140,
        min_h: int = 14,
        max_h: int = 90,
        min_aspect: float = 0.90,
        max_aspect: float = 4.20,
        min_dark_ratio: float = 0.010,
        min_fill_ratio: float = 0.20,
        min_solidity: float = 0.68,
        min_circularity: float = 0.18,
        row_y_tolerance: int = 18,
        min_gap: int = 42,
        max_gap: int = 140,
        iou_dedup_threshold: float = 0.35,
    ):
        self.x_min_px = int(x_min_px)
        self.x_max_px = int(x_max_px)
        self.y_min_px = int(y_min_px)
        self.y_max_px = int(y_max_px)
        self.seed_bar_search_y_min_px = int(seed_bar_search_y_min_px)
        self.seed_bar_search_y_max_px = int(seed_bar_search_y_max_px)
        self.min_area = int(min_area)
        self.max_area = int(max_area)
        self.min_w = int(min_w)
        self.max_w = int(max_w)
        self.min_h = int(min_h)
        self.max_h = int(max_h)
        self.min_aspect = float(min_aspect)
        self.max_aspect = float(max_aspect)
        self.min_dark_ratio = float(min_dark_ratio)
        self.min_fill_ratio = float(min_fill_ratio)
        self.min_solidity = float(min_solidity)
        self.min_circularity = float(min_circularity)
        self.row_y_tolerance = int(row_y_tolerance)
        self.min_gap = int(min_gap)
        self.max_gap = int(max_gap)
        self.iou_dedup_threshold = float(iou_dedup_threshold)

    @staticmethod
    def _filter_boxes_by_xy_range(
        boxes: list[tuple[int, int, int, int]],
        *,
        x_min: int,
        x_max: int,
        y_min: int,
        y_max: int,
    ) -> list[tuple[int, int, int, int]]:
        out: list[tuple[int, int, int, int]] = []
        for box in boxes:
            cx = int((box[0] + box[2]) // 2)
            cy = int((box[1] + box[3]) // 2)
            if cx < int(x_min) or cx > int(x_max):
                continue
            if cy < int(y_min) or cy > int(y_max):
                continue
            out.append(box)
        return out

    @staticmethod
    def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / float(area_a + area_b - inter)

    def _estimate_seed_bar_row(self, gray: np.ndarray) -> int:
        """Estimate translucent seed-bar row by dark-ratio peak."""
        h, _ = gray.shape[:2]
        y1 = int(self.seed_bar_search_y_min_px)
        y2 = int(self.seed_bar_search_y_max_px)
        y1 = max(0, min(y1, h - 2))
        y2 = max(y1 + 1, min(y2, h))
        region = gray[y1:y2, :]
        if region.size == 0:
            return int(min(h - 1, max(0, (self.seed_bar_search_y_min_px + self.seed_bar_search_y_max_px) // 2)))

        dark = (region <= 120).astype(np.float32)
        row_dark = dark.mean(axis=1)
        row_dark = cv2.GaussianBlur(row_dark.reshape(-1, 1), (1, 17), 0).reshape(-1)
        peak_idx = int(np.argmax(row_dark))
        return int(y1 + peak_idx)

    @staticmethod
    def _build_mask(gray: np.ndarray) -> np.ndarray:
        """Build bright bubble mask by gray thresholds."""
        _, mask_global = cv2.threshold(gray, 168, 255, cv2.THRESH_BINARY)
        mask_adapt = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            29,
            -8,
        )
        mask = cv2.bitwise_and(mask_global, mask_adapt)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        return mask

    def _collect_candidates(
        self,
        img_bgr: np.ndarray,
        roi: tuple[int, int, int, int],
    ) -> list[tuple[int, int, int, int]]:
        x1, y1, x2, y2 = roi
        region = img_bgr[y1:y2, x1:x2]
        if region.size == 0:
            return []

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        mask = self._build_mask(gray)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: list[tuple[int, int, int, int]] = []

        region_h = int(y2 - y1)
        min_local_y = int(round(region_h * 0.10))
        max_local_y = int(round(region_h * 0.92))
        for contour in contours:
            rx, ry, rw, rh = cv2.boundingRect(contour)
            area = int(rw * rh)
            if area < self.min_area or area > self.max_area:
                continue
            if rw < self.min_w or rw > self.max_w or rh < self.min_h or rh > self.max_h:
                continue
            if ry < min_local_y or ry > max_local_y:
                continue

            aspect = float(rw) / max(1.0, float(rh))
            if aspect < self.min_aspect or aspect > self.max_aspect:
                continue

            contour_area = float(cv2.contourArea(contour))
            if contour_area <= 1.0:
                continue
            fill_ratio = contour_area / float(max(1, rw * rh))
            if fill_ratio < self.min_fill_ratio:
                continue

            hull = cv2.convexHull(contour)
            hull_area = float(cv2.contourArea(hull))
            if hull_area <= 1.0:
                continue
            solidity = contour_area / hull_area
            if solidity < self.min_solidity:
                continue

            perimeter = float(cv2.arcLength(contour, True))
            if perimeter <= 1.0:
                continue
            circularity = (4.0 * np.pi * contour_area) / (perimeter * perimeter)
            if circularity < self.min_circularity:
                continue

            crop_gray = gray[ry : ry + rh, rx : rx + rw]
            bright_ratio = float((crop_gray >= 165).sum()) / float(crop_gray.size)
            if bright_ratio < 0.34:
                continue
            dark_ratio = float((crop_gray <= 120).sum()) / float(crop_gray.size)
            if dark_ratio < self.min_dark_ratio:
                continue

            boxes.append((int(rx + x1), int(ry + y1), int(rx + rw + x1), int(ry + rh + y1)))

        boxes.sort(key=lambda b: (b[1], b[0]))
        deduped: list[tuple[int, int, int, int]] = []
        for box in boxes:
            if any(self._iou(box, old) > self.iou_dedup_threshold for old in deduped):
                continue
            deduped.append(box)

        return deduped

    def _cluster_rows(self, boxes: list[tuple[int, int, int, int]]) -> list[list[tuple[int, int, int, int]]]:
        rows: list[list[tuple[int, int, int, int]]] = []
        for box in sorted(boxes, key=lambda b: ((b[1] + b[3]) / 2.0, b[0])):
            cy = (box[1] + box[3]) / 2.0
            placed = False
            for row in rows:
                mean_y = sum((b[1] + b[3]) / 2.0 for b in row) / float(len(row))
                if abs(cy - mean_y) <= float(self.row_y_tolerance):
                    row.append(box)
                    placed = True
                    break
            if not placed:
                rows.append([box])
        for row in rows:
            row.sort(key=lambda b: b[0])
        return rows

    def _best_run_in_row(self, row: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
        if not row:
            return []
        if len(row) <= 1:
            return row[:]

        runs: list[list[tuple[int, int, int, int]]] = []
        curr = [row[0]]
        for prev, now in zip(row, row[1:]):
            prev_cx = int((prev[0] + prev[2]) // 2)
            now_cx = int((now[0] + now[2]) // 2)
            gap = int(now_cx - prev_cx)
            if self.min_gap <= gap <= self.max_gap:
                curr.append(now)
            else:
                runs.append(curr)
                curr = [now]
        runs.append(curr)
        runs.sort(
            key=lambda r: (
                len(r),
                (r[-1][0] - r[0][0]) if len(r) > 1 else 0,
            ),
            reverse=True,
        )
        return runs[0]

    def _select_boxes(self, boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
        if not boxes:
            return []
        rows = self._cluster_rows(boxes)
        candidates: list[list[tuple[int, int, int, int]]] = []
        for row in rows:
            run = self._best_run_in_row(row)
            if run:
                candidates.append(run)
        if not candidates:
            return []

        candidates.sort(
            key=lambda r: (
                len(r),
                (r[-1][0] - r[0][0]) if len(r) > 1 else 0,
                -sum((b[1] + b[3]) / 2.0 for b in r) / float(len(r)),
            ),
            reverse=True,
        )
        best = candidates[0]
        return sorted(best, key=lambda b: b[0])

    @staticmethod
    def _normalize_box_sizes(
        boxes: list[tuple[int, int, int, int]],
        frame_w: int,
        frame_h: int,
    ) -> list[tuple[int, int, int, int]]:
        if not boxes:
            return []
        widths = [b[2] - b[0] for b in boxes]
        heights = [b[3] - b[1] for b in boxes]
        ref_w = int(round(float(np.median(widths))))
        ref_h = int(round(float(np.median(heights))))
        ref_w = max(34, min(ref_w, 52))
        ref_h = max(20, min(ref_h, 38))

        out: list[tuple[int, int, int, int]] = []
        for x1, y1, x2, y2 in boxes:
            cx = int(round((x1 + x2) / 2.0))
            cy = int(round((y1 + y2) / 2.0))
            nx1 = int(round(cx - ref_w / 2.0))
            ny1 = int(round(cy - ref_h / 2.0))
            nx2 = int(nx1 + ref_w)
            ny2 = int(ny1 + ref_h)
            nx1 = max(0, nx1)
            ny1 = max(0, ny1)
            nx2 = min(frame_w, nx2)
            ny2 = min(frame_h, ny2)
            out.append((nx1, ny1, nx2, ny2))
        return out

    def detect_boxes(
        self,
        img_bgr: np.ndarray | None,
        *,
        roi: tuple[int, int, int, int] | None = None,
        x_range: tuple[int, int] | None = None,
        y_range: tuple[int, int] | None = None,
    ) -> list[NumberBox]:
        if img_bgr is None or img_bgr.size == 0:
            return []
        if img_bgr.ndim != 3:
            return []

        h, w = img_bgr.shape[:2]
        if roi is None:
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            seed_bar_row = self._estimate_seed_bar_row(gray)
            number_row = int(seed_bar_row - 55)
            primary_roi = (0, max(0, number_row - 38), w, min(h, number_row + 42))
            fallback_roi = (0, max(0, number_row - 55), w, min(h, number_row + 60))
        else:
            x1, y1, x2, y2 = [int(v) for v in roi]
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(x1 + 1, min(x2, w))
            y2 = max(y1 + 1, min(y2, h))
            primary_roi = (x1, y1, x2, y2)
            fallback_roi = primary_roi

        px1, py1, px2, py2 = primary_roi
        fx1, fy1, fx2, fy2 = fallback_roi
        if px2 <= px1 or py2 <= py1:
            return []
        if fx2 <= fx1 or fy2 <= fy1:
            fallback_roi = primary_roi

        if x_range is not None:
            x_min = int(min(x_range[0], x_range[1]))
            x_max = int(max(x_range[0], x_range[1]))
        else:
            x_min = int(self.x_min_px)
            x_max = int(self.x_max_px)
        x_min = max(0, min(x_min, w - 1))
        x_max = max(x_min, min(x_max, w - 1))
        if y_range is not None:
            y_min = int(min(y_range[0], y_range[1]))
            y_max = int(max(y_range[0], y_range[1]))
        else:
            y_min = int(self.y_min_px)
            y_max = int(self.y_max_px)
        y_min = max(0, min(y_min, h - 1))
        y_max = max(y_min, min(y_max, h - 1))

        candidates_primary = self._collect_candidates(img_bgr, primary_roi)
        candidates_primary = self._filter_boxes_by_xy_range(
            candidates_primary,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )
        selected_primary = self._select_boxes(candidates_primary)
        candidates_fallback = self._collect_candidates(img_bgr, fallback_roi)
        candidates_fallback = self._filter_boxes_by_xy_range(
            candidates_fallback,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )
        selected_fallback = self._select_boxes(candidates_fallback)

        selected = selected_primary
        if len(selected_fallback) > len(selected_primary):
            selected = selected_fallback
        selected = self._normalize_box_sizes(selected, frame_w=w, frame_h=h)

        out: list[NumberBox] = []
        for idx, box in enumerate(selected, start=1):
            bx1, by1, bx2, by2 = box
            center = ((bx1 + bx2) // 2, (by1 + by2) // 2)
            size = (bx2 - bx1, by2 - by1)
            out.append(NumberBox(order=idx, bbox=box, center=center, size=size))

        logger.info('数字框识别: 完成 | count={} boxes={}', len(out), [item.bbox for item in out])
        return out

    @staticmethod
    def draw_boxes(img_bgr: np.ndarray, boxes: list[NumberBox]) -> np.ndarray:
        canvas = img_bgr.copy()
        for item in boxes:
            x1, y1, x2, y2 = item.bbox
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 255), 2)
            cv2.putText(
                canvas,
                str(item.order),
                (x1, max(18, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
        return canvas
