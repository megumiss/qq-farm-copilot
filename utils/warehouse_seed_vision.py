"""仓库种子页结构定位工具。"""

from __future__ import annotations

import cv2
import numpy as np
from loguru import logger

# 仓库种子页上半部 5x4 种子格区域，用于分割当前可见 20 个种子格。
WAREHOUSE_SEED_GRID_ROI: tuple[int, int, int, int] = (18, 180, 522, 616)


def clip_bbox(
    bbox: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """将 bbox 夹紧到图像范围。"""
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(int(x1), int(width) - 1))
    y1 = max(0, min(int(y1), int(height) - 1))
    x2 = max(x1 + 1, min(int(x2), int(width)))
    y2 = max(y1 + 1, min(int(y2), int(height)))
    return x1, y1, x2, y2


def cluster_axis_values(values: list[float], *, threshold: float) -> list[float]:
    """将同轴坐标聚类为行/列中心。"""
    if not values:
        return []
    clusters: list[list[float]] = []
    for value in sorted(float(v) for v in values):
        if not clusters or abs(value - float(np.median(clusters[-1]))) > float(threshold):
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [float(np.median(cluster)) for cluster in clusters]


def detect_warehouse_seed_slot_boxes(screenshot: np.ndarray) -> list[tuple[int, int, int, int]]:
    """按仓库种子页上半区域轮廓推断 5x4 种子格。"""
    if screenshot is None or screenshot.size == 0:
        return []

    sh, sw = screenshot.shape[:2]
    rx1, ry1, rx2, ry2 = clip_bbox(WAREHOUSE_SEED_GRID_ROI, width=sw, height=sh)
    roi_img = screenshot[ry1:ry2, rx1:rx2]
    gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    proc = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(proc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        if 65 <= w <= 110 and 75 <= h <= 125 and area >= 1500:
            candidates.append((rx1 + int(x), ry1 + int(y), rx1 + int(x + w), ry1 + int(y + h)))

    if len(candidates) < 5:
        logger.warning('仓库种子格分割失败: 轮廓数={}', len(candidates))
        return []

    centers_x = [(box[0] + box[2]) / 2.0 for box in candidates]
    centers_y = [(box[1] + box[3]) / 2.0 for box in candidates]
    col_centers = cluster_axis_values(centers_x, threshold=35.0)
    row_centers = cluster_axis_values(centers_y, threshold=40.0)

    if len(col_centers) < 5 or not row_centers:
        logger.warning(
            '仓库种子格分割不足: 轮廓数={} 列数={} 行数={}',
            len(candidates),
            len(col_centers),
            len(row_centers),
        )
        return sorted(candidates, key=lambda box: (box[1], box[0]))

    col_centers = sorted(col_centers)[:5]
    row_centers = sorted(row_centers)
    if len(row_centers) < 4:
        row_step = float(np.median(np.diff(row_centers))) if len(row_centers) >= 2 else 110.0
        while len(row_centers) < 4:
            row_centers.append(row_centers[-1] + row_step)
    row_centers = row_centers[:4]

    widths = [box[2] - box[0] for box in candidates]
    heights = [box[3] - box[1] for box in candidates]
    cell_w = int(round(float(np.median(widths)))) if widths else 95
    cell_h = int(round(float(np.median(heights)))) if heights else 105
    cell_w = max(80, min(100, cell_w))
    cell_h = max(95, min(110, cell_h))

    boxes: list[tuple[int, int, int, int]] = []
    for cy in row_centers:
        for cx in col_centers:
            x1 = int(round(cx - cell_w / 2.0))
            y1 = int(round(cy - cell_h / 2.0))
            boxes.append(clip_bbox((x1, y1, x1 + cell_w, y1 + cell_h), width=sw, height=sh))

    if len(candidates) != 20:
        logger.debug(
            '仓库种子格轮廓推断: 原始轮廓数={} 候选轮廓数={} 过滤轮廓数={} 推断格数={} 列中心={} 行中心={}',
            len(contours),
            len(candidates),
            max(0, len(contours) - len(candidates)),
            len(boxes),
            [round(v, 1) for v in col_centers],
            [round(v, 1) for v in row_centers],
        )
    return boxes[:20]


def group_warehouse_seed_rows(
    boxes: list[tuple[int, int, int, int]],
    *,
    row_threshold: float = 40.0,
) -> list[list[tuple[int, int, int, int]]]:
    """将仓库种子格按行分组，行内从左到右排序。"""
    if not boxes:
        return []
    rows: list[list[tuple[int, int, int, int]]] = []
    for box in sorted(boxes, key=lambda item: ((item[1] + item[3]) / 2.0, item[0])):
        cy = (box[1] + box[3]) / 2.0
        if not rows:
            rows.append([box])
            continue
        last_row = rows[-1]
        last_cy = float(np.median([(item[1] + item[3]) / 2.0 for item in last_row]))
        if abs(cy - last_cy) <= float(row_threshold):
            last_row.append(box)
        else:
            rows.append([box])
    return [sorted(row, key=lambda item: item[0])[:5] for row in rows if row]


def warehouse_seed_row_image_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算两行种子截图的粗略相似度，1 表示完全一致。"""
    if a is None or b is None or a.size == 0 or b.size == 0:
        return 0.0
    target_w = 240
    target_h = 48
    a_gray = cv2.cvtColor(cv2.resize(a, (target_w, target_h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    b_gray = cv2.cvtColor(cv2.resize(b, (target_w, target_h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(a_gray, b_gray)
    return 1.0 - float(np.mean(diff)) / 255.0
