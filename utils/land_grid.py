"""Land grid helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

LAND_GRID_SLOPE_COL = -0.5091743119
LAND_GRID_SLOPE_ROW = 0.5091743119


@dataclass(frozen=True)
class LandCell:
    """Single land cell info."""

    order: int
    row: int
    col: int
    label: str
    center: tuple[int, int]
    vertices: list[tuple[int, int]]


def _unit_by_slope(slope: float) -> tuple[float, float]:
    """Convert a slope to a unit direction vector."""
    dx = 1.0
    dy = float(slope)
    norm = math.hypot(dx, dy)
    if norm <= 1e-8:
        return 1.0, 0.0
    return dx / norm, dy / norm


def _order_vertices_top_clockwise(points: Sequence[tuple[float, float]]) -> list[tuple[int, int]]:
    """Sort vertices clockwise and rotate so the top-most point is first."""
    if len(points) != 4:
        return [(int(round(x)), int(round(y))) for x, y in points]

    cx = sum(p[0] for p in points) / 4.0
    cy = sum(p[1] for p in points) / 4.0
    sorted_points = sorted(points, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

    # Start from top-most point; tie-break by smaller x.
    start_idx = min(range(4), key=lambda i: (sorted_points[i][1], sorted_points[i][0]))
    ordered = sorted_points[start_idx:] + sorted_points[:start_idx]
    return [(int(round(x)), int(round(y))) for x, y in ordered]


def get_lands_from_land_anchor(
    land_right_anchor: tuple[int, int] | None,
    land_left_anchor: tuple[int, int] | None,
    *,
    rows: int = 4,
    cols: int = 6,
    slope_col: float = LAND_GRID_SLOPE_COL,
    slope_row: float = LAND_GRID_SLOPE_ROW,
    start_anchor: str = 'right',
) -> list[LandCell]:
    """Build land-center points from left/right land anchor positions.

    Args:
        land_right_anchor: Center position of `BTN_LAND_RIGHT`.
        land_left_anchor: Center position of `BTN_LAND_LEFT`.
        rows: Land rows count.
        cols: Land columns count.
        slope_col: Column direction slope (dy / dx).
        slope_row: Row direction slope (dy / dx).
        start_anchor: Grid origin anchor, `right` or `left`.
    Returns:
        Full land-cell info list.
        Label rule follows the original tools logic: `label = f"{col}-{rows-r}"`.
    """
    if land_right_anchor is None or land_left_anchor is None:
        return []

    cell_rows = max(1, int(rows))
    cell_cols = max(1, int(cols))
    step_rows = cell_rows
    step_cols = cell_cols

    right_anchor = (float(land_right_anchor[0]), float(land_right_anchor[1]))
    left_anchor = (float(land_left_anchor[0]), float(land_left_anchor[1]))
    use_right = str(start_anchor).strip().lower() != 'left'
    start = right_anchor if use_right else left_anchor
    end = left_anchor if use_right else right_anchor

    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]

    ux, uy = _unit_by_slope(float(slope_col))
    vx, vy = _unit_by_slope(float(slope_row))

    m00 = float(step_cols) * ux
    m01 = float(step_rows) * vx
    m10 = float(step_cols) * uy
    m11 = float(step_rows) * vy
    det = m00 * m11 - m01 * m10
    if abs(det) <= 1e-6:
        return []

    scale_col = (delta_x * m11 - delta_y * m01) / det
    scale_row = (m00 * delta_y - m10 * delta_x) / det
    col_step_x = ux * scale_col
    col_step_y = uy * scale_col
    row_step_x = vx * scale_row
    row_step_y = vy * scale_row

    lands: list[LandCell] = []
    order = 0
    for r in range(cell_rows):
        for c in range(cell_cols):
            order += 1
            x00 = start[0] + col_step_x * float(c) + row_step_x * float(r)
            y00 = start[1] + col_step_y * float(c) + row_step_y * float(r)
            x01 = x00 + col_step_x
            y01 = y00 + col_step_y
            x11 = x01 + row_step_x
            y11 = y01 + row_step_y
            x10 = x00 + row_step_x
            y10 = y00 + row_step_y
            center_x = int(round((x00 + x11) * 0.5))
            center_y = int(round((y00 + y11) * 0.5))
            ordered = _order_vertices_top_clockwise(
                [
                    (x00, y00),
                    (x01, y01),
                    (x11, y11),
                    (x10, y10),
                ]
            )
            logical_row = cell_rows - r
            logical_col = c + 1
            lands.append(
                LandCell(
                    order=order,
                    row=logical_row,
                    col=logical_col,
                    label=f'{logical_col}-{logical_row}',
                    center=(center_x, center_y),
                    vertices=ordered,
                )
            )

    return lands
