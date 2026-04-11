"""Seed number-box detector (digit-template aggregation only)."""

from __future__ import annotations

import re
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
    """Detect seed number boxes from digit templates (`icon_num_0..9`)."""

    def __init__(
        self,
        *,
        ui=None,
        x_min_px: int = 40,
        x_max_px: int = 500,
        y_min_px: int = 400,
        y_max_px: int = 750,
        max_box_width_px: int = 30,
        result_cluster_distance_px: int = 30,
        left_anchor_template_threshold: float = 0.7,
        left_anchor_max_right_gap_px: int = 40,
        left_anchor_max_y_gap_px: int = 15,
        iou_dedup_threshold: float = 0.35,
        digit_template_threshold: float = 0.7,
        digit_iou_dedup_threshold: float = 0.50,
    ):
        self.ui = ui
        self.x_min_px = int(x_min_px)
        self.x_max_px = int(x_max_px)
        self.y_min_px = int(y_min_px)
        self.y_max_px = int(y_max_px)
        self.max_box_width_px = int(max_box_width_px)
        self.result_cluster_distance_px = int(result_cluster_distance_px)
        self.left_anchor_template_threshold = float(left_anchor_template_threshold)
        self.left_anchor_max_right_gap_px = int(left_anchor_max_right_gap_px)
        self.left_anchor_max_y_gap_px = int(left_anchor_max_y_gap_px)
        self.iou_dedup_threshold = float(iou_dedup_threshold)
        self.digit_template_threshold = float(digit_template_threshold)
        self.digit_iou_dedup_threshold = float(digit_iou_dedup_threshold)

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
    def _digit_template_names() -> list[str]:
        return [f'icon_num_{i}' for i in range(10)]

    @staticmethod
    def _parse_digit_template_name(name: str) -> str | None:
        matched = re.fullmatch(r'icon_num_(\d)', str(name or '').strip())
        if matched is None:
            return None
        return str(matched.group(1))

    def _collect_template_digit_hits(
        self,
        img_bgr: np.ndarray,
        detect_roi: tuple[int, int, int, int],
    ) -> list[tuple[int, int, int, int, float, str]]:
        rx1, ry1, rx2, ry2 = [int(v) for v in detect_roi]
        template_names = self._digit_template_names()
        candidates: list[tuple[int, int, int, int, float, str]] = []
        if self.ui is None:
            return []

        from core.ui.assets import ASSET_NAME_TO_CONST

        left_anchor_button = ASSET_NAME_TO_CONST.get('icon_num_left')
        left_anchor_boxes: list[tuple[int, int, int, int]] = []
        if left_anchor_button is not None:
            left_matches = self.ui.match_icon_multi(
                left_anchor_button,
                threshold=float(self.left_anchor_template_threshold),
                roi=detect_roi,
            )
            for det in left_matches:
                lx1, ly1, lx2, ly2 = [int(v) for v in det.area]
                lx1 = max(rx1, lx1)
                ly1 = max(ry1, ly1)
                lx2 = min(rx2, lx2)
                ly2 = min(ry2, ly2)
                if lx2 <= lx1 or ly2 <= ly1:
                    continue
                left_anchor_boxes.append((lx1, ly1, lx2, ly2))
        if not left_anchor_boxes:
            return []

        for name in template_names:
            button = ASSET_NAME_TO_CONST.get(name)
            digit = self._parse_digit_template_name(name)
            if button is None or digit is None:
                continue
            matches = self.ui.match_icon_multi(
                button,
                threshold=float(self.digit_template_threshold),
                roi=detect_roi,
            )
            for idx, det in enumerate(matches):
                x1, y1, x2, y2 = [int(v) for v in det.area]
                x1 = max(rx1, x1)
                y1 = max(ry1, y1)
                x2 = min(rx2, x2)
                y2 = min(ry2, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                if not self._is_digit_near_left_anchor((x1, y1, x2, y2), left_anchor_boxes):
                    continue
                # match_icon_multi 返回结果已按置信度排序；用顺序构造稳定分数用于后续去重优先级。
                confidence = float(self.digit_template_threshold) - float(idx) * 1e-4
                candidates.append((x1, y1, x2, y2, confidence, digit))

        if not candidates:
            return []

        candidates.sort(key=lambda item: item[4], reverse=True)
        deduped: list[tuple[int, int, int, int, float, str]] = []
        for item in candidates:
            box = (item[0], item[1], item[2], item[3])
            cx = int(round((item[0] + item[2]) / 2.0))
            cy = int(round((item[1] + item[3]) / 2.0))
            duplicated = False
            for old in deduped:
                old_box = (old[0], old[1], old[2], old[3])
                old_cx = int(round((old[0] + old[2]) / 2.0))
                old_cy = int(round((old[1] + old[3]) / 2.0))
                if self._iou(box, old_box) >= float(self.digit_iou_dedup_threshold):
                    duplicated = True
                    break
                if abs(cx - old_cx) <= 2 and abs(cy - old_cy) <= 2:
                    duplicated = True
                    break
            if not duplicated:
                deduped.append(item)
        deduped.sort(key=lambda item: (int((item[1] + item[3]) / 2), int((item[0] + item[2]) / 2)))
        return deduped

    def _is_digit_near_left_anchor(
        self,
        digit_box: tuple[int, int, int, int],
        left_anchor_boxes: list[tuple[int, int, int, int]],
    ) -> bool:
        dx1, dy1, dx2, dy2 = [int(v) for v in digit_box]
        dcy = int(round((dy1 + dy2) / 2.0))
        for lx1, ly1, lx2, ly2 in left_anchor_boxes:
            lcy = int(round((ly1 + ly2) / 2.0))
            gap_right = int(dx1 - lx2)
            if gap_right < 0 or gap_right > int(self.left_anchor_max_right_gap_px):
                continue
            if abs(dcy - lcy) > int(self.left_anchor_max_y_gap_px):
                continue
            return True
        return False

    def _aggregate_digit_hits_to_number_boxes(
        self,
        digit_hits: list[tuple[int, int, int, int, float, str]],
        detect_roi: tuple[int, int, int, int],
    ) -> list[tuple[int, int, int, int]]:
        if not digit_hits:
            return []

        digit_boxes = sorted(
            [(int(x1), int(y1), int(x2), int(y2)) for x1, y1, x2, y2, _, _ in digit_hits],
            key=lambda box: (int((box[1] + box[3]) / 2), box[0]),
        )
        widths = [int(box[2] - box[0]) for box in digit_boxes]
        heights = [int(box[3] - box[1]) for box in digit_boxes]
        median_w = float(np.median(np.asarray(widths, dtype=np.float32))) if widths else 8.0
        median_h = float(np.median(np.asarray(heights, dtype=np.float32))) if heights else 12.0
        merge_gap = int(max(8, min(20, round(median_w * 1.8))))
        row_tol = int(max(10, min(26, round(median_h * 1.5))))

        grouped_runs: list[list[tuple[int, int, int, int]]] = []
        for box in digit_boxes:
            if not grouped_runs:
                grouped_runs.append([box])
                continue

            curr_run = grouped_runs[-1]
            last_box = curr_run[-1]
            cur_cy = int(round((box[1] + box[3]) / 2.0))
            last_cy = int(round((last_box[1] + last_box[3]) / 2.0))
            horizontal_gap = int(box[0] - last_box[2])
            run_x1 = min(item[0] for item in curr_run)
            run_x2 = max(item[2] for item in curr_run)
            merged_width = int(max(run_x2, box[2]) - min(run_x1, box[0]))
            can_merge = (
                abs(cur_cy - last_cy) <= row_tol
                and 0 <= horizontal_gap <= merge_gap
                and merged_width <= int(self.max_box_width_px)
            )
            if can_merge:
                curr_run.append(box)
            else:
                grouped_runs.append([box])

        rx1, ry1, rx2, ry2 = [int(v) for v in detect_roi]
        out: list[tuple[int, int, int, int]] = []
        for run in grouped_runs:
            if not run:
                continue
            x1 = min(box[0] for box in run)
            y1 = min(box[1] for box in run)
            x2 = max(box[2] for box in run)
            y2 = max(box[3] for box in run)
            bx1 = int(x1)
            by1 = int(y1)
            bx2 = int(x2)
            by2 = int(y2)

            bx1 = max(rx1, bx1)
            by1 = max(ry1, by1)
            bx2 = min(rx2, bx2)
            by2 = min(ry2, by2)
            if bx2 <= bx1 or by2 <= by1:
                continue
            if (bx2 - bx1) > int(self.max_box_width_px):
                continue
            out.append((bx1, by1, bx2, by2))

        out.sort(key=lambda box: (box[0], box[1]))
        deduped: list[tuple[int, int, int, int]] = []
        for box in out:
            if any(self._iou(box, old) > self.iou_dedup_threshold for old in deduped):
                continue
            deduped.append(box)
        return deduped

    @staticmethod
    def _aggregate_nearby_boxes(
        boxes: list[tuple[int, int, int, int]],
        *,
        distance_px: int,
    ) -> list[tuple[int, int, int, int]]:
        """将中心点距离在阈值内的候选框聚合为一个结果框。"""
        if not boxes:
            return []
        distance = max(1, int(distance_px))
        dist_sq = distance * distance
        remaining = [tuple(int(v) for v in box) for box in boxes]
        merged: list[tuple[int, int, int, int]] = []

        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            changed = True
            while changed:
                changed = False
                keep: list[tuple[int, int, int, int]] = []
                for candidate in remaining:
                    ccx = (candidate[0] + candidate[2]) // 2
                    ccy = (candidate[1] + candidate[3]) // 2
                    near_cluster = False
                    for item in cluster:
                        icx = (item[0] + item[2]) // 2
                        icy = (item[1] + item[3]) // 2
                        dx = ccx - icx
                        dy = ccy - icy
                        if (dx * dx + dy * dy) <= dist_sq:
                            near_cluster = True
                            break
                    if near_cluster:
                        cluster.append(candidate)
                        changed = True
                    else:
                        keep.append(candidate)
                remaining = keep

            x1 = min(item[0] for item in cluster)
            y1 = min(item[1] for item in cluster)
            x2 = max(item[2] for item in cluster)
            y2 = max(item[3] for item in cluster)
            merged.append((x1, y1, x2, y2))

        merged.sort(key=lambda box: (box[0], box[1]))
        return merged

    def detect_boxes(
        self,
        img_bgr: np.ndarray | None,
        *,
        roi: tuple[int, int, int, int] | None = None,
        x_range: tuple[int, int] | None = None,
        y_range: tuple[int, int] | None = None,
    ) -> list[NumberBox]:
        if img_bgr is None or img_bgr.size == 0 or img_bgr.ndim != 3:
            return []

        h, w = img_bgr.shape[:2]
        if roi is None:
            rx1 = 0
            ry1 = max(0, min(h - 1, int(self.y_min_px - 80)))
            rx2 = w
            ry2 = max(ry1 + 1, min(h, int(self.y_max_px)))
            primary_roi = (rx1, ry1, rx2, ry2)
        else:
            x1, y1, x2, y2 = [int(v) for v in roi]
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(x1 + 1, min(x2, w))
            y2 = max(y1 + 1, min(y2, h))
            primary_roi = (x1, y1, x2, y2)

        if primary_roi[2] <= primary_roi[0] or primary_roi[3] <= primary_roi[1]:
            return []

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

        primary_hits = self._collect_template_digit_hits(img_bgr, primary_roi)
        boxes = self._aggregate_digit_hits_to_number_boxes(primary_hits, primary_roi)
        boxes = self._filter_boxes_by_xy_range(
            boxes,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )
        selected = self._aggregate_nearby_boxes(
            boxes,
            distance_px=int(self.result_cluster_distance_px),
        )
        selected = sorted(selected, key=lambda box: box[0])

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
