"""地块巡查任务。"""

from __future__ import annotations

from loguru import logger

from core.engine.task.registry import TaskResult
from core.ui.assets import BTN_LAND_LEFT, BTN_LAND_RIGHT
from core.ui.page import page_main
from tasks.base import TaskBase
from utils.land_grid import LandCell, get_lands_from_land_anchor
from utils.ocr_utils import OCRTool

# 画面横向回正手势点位 P1。
LAND_SCAN_SWIPE_H_P1 = (350, 190)
# 画面横向回正手势点位 P2。
LAND_SCAN_SWIPE_H_P2 = (200, 190)
# 地块网格行数（逻辑行）。
LAND_SCAN_ROWS = 4
# 地块网格列数（逻辑列）。
LAND_SCAN_COLS = 6
# 画面物理列总数（1,2,3,4,4,4,3,2,1）。
LAND_SCAN_PHYSICAL_COLS = 9
# 左滑阶段按“右到左”扫描的物理列数量。
LAND_SCAN_LEFT_STAGE_COL_COUNT = 5
# 右滑阶段按“左到右”扫描的物理列数量。
LAND_SCAN_RIGHT_STAGE_COL_COUNT = 4
# 以点击点为中心构建 OCR 区域的半宽（像素）。
LAND_SCAN_OCR_HALF_WIDTH = 180
# 以点击点为中心构建 OCR 区域的半高（像素）。
LAND_SCAN_OCR_HALF_HEIGHT = 120


class TaskLandScan(TaskBase):
    """按预设顺序遍历地块并进行 OCR 收集。"""

    def __init__(self, engine, ui, *, ocr_tool: OCRTool | None = None):
        super().__init__(engine, ui)
        self.ocr_tool = ocr_tool
        self._ocr_disabled_logged = False

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行地块巡查流程。"""
        _ = rect
        logger.info('地块巡查: 开始')
        self.ui.ui_ensure(page_main)
        # self.ui.device.click_button(GOTO_MAIN)

        try:
            for _ in range(2):
                self.ui.device.swipe(LAND_SCAN_SWIPE_H_P1, LAND_SCAN_SWIPE_H_P2, speed=30)
                self.ui.device.sleep(0.5)
            cells_after_left = self._collect_land_cells()
            if not cells_after_left:
                logger.warning('地块巡查: 未识别到地块网格，跳过任务')
                return self.fail('未识别到地块网格')
            self._scan_cells_by_physical_columns(
                cells_after_left, from_side='right', column_count=LAND_SCAN_LEFT_STAGE_COL_COUNT
            )

            for _ in range(2):
                self.ui.device.swipe(LAND_SCAN_SWIPE_H_P2, LAND_SCAN_SWIPE_H_P1, speed=30, delay=0.2)
            cells_after_right = self._collect_land_cells()
            self._scan_cells_by_physical_columns(
                cells_after_right, from_side='left', column_count=LAND_SCAN_RIGHT_STAGE_COL_COUNT
            )
        finally:
            # TODO 画面回正
            self.ui.ui_ensure(page_main)

        logger.info('地块巡查: 结束')
        return self.ok()

    def _scan_cells_by_physical_columns(self, cells: list[LandCell], *, from_side: str, column_count: int):
        """按画面物理列扫描地块（列内顺序：从上到下）。"""
        col_map: dict[int, list[LandCell]] = {}
        for cell in cells:
            physical_col = self._physical_col_rtl(cell)
            col_map.setdefault(physical_col, []).append(cell)

        rtl_cols = sorted(col_map.keys())
        if str(from_side).strip().lower() == 'left':
            scan_cols = list(reversed(rtl_cols))[: max(0, int(column_count))]
        else:
            scan_cols = rtl_cols[: max(0, int(column_count))]

        logger.info('地块巡查: 物理列={}', scan_cols)
        for physical_col in scan_cols:
            col_cells = list(col_map.get(physical_col, []))
            col_cells.sort(key=lambda cell: (int(cell.center[1]), int(cell.center[0])))
            for cell in col_cells:
                self._click_and_ocr_cell(cell=cell, physical_col=physical_col)

        return

    def _click_and_ocr_cell(self, *, cell: LandCell, physical_col: int):
        """点击单个地块并采集 OCR 文本。"""
        x, y = int(cell.center[0]), int(cell.center[1])
        self.ui.device.click_point(x, y, desc=f'地块序号 {cell.label}')

        frame = self.ui.device.screenshot()
        roi = self._build_ocr_region(frame.shape, center=(x, y))
        text, score = self.ocr_tool.detect_text(frame, region=roi, scale=1.2, alpha=1.1, beta=0.0)
        logger.info(
            '地块巡查: OCR | land={} p_col={} l_col={} row={} center=({}, {}) roi={} text={} score={:.3f}',
            cell.label,
            physical_col,
            cell.col,
            cell.row,
            x,
            y,
            roi,
            self._short_text(text),
            score,
        )
        return

    def _collect_land_cells(self) -> list[LandCell]:
        """识别左右锚点并推算地块网格。"""
        self.ui.device.screenshot()
        right_anchor = self.ui.appear_location(BTN_LAND_RIGHT, offset=30, threshold=0.95, static=False)
        left_anchor = self.ui.appear_location(BTN_LAND_LEFT, offset=30, threshold=0.95, static=False)

        cells = get_lands_from_land_anchor(
            right_anchor, left_anchor, rows=LAND_SCAN_ROWS, cols=LAND_SCAN_COLS, start_anchor='right'
        )
        logger.info(
            '地块巡查: 网格识别 | 右锚点={} 左锚点={} 地块总计={}', right_anchor, left_anchor, len(cells)
        )
        return cells

    @staticmethod
    def _physical_col_rtl(cell: LandCell) -> int:
        """将地块映射为物理列索引（右到左，范围 1..9）。"""
        logical_col = int(cell.col)
        logical_row = int(cell.row)
        idx = (LAND_SCAN_ROWS - logical_row) + (logical_col - 1) + 1
        return max(1, min(LAND_SCAN_PHYSICAL_COLS, idx))

    @staticmethod
    def _build_ocr_region(frame_shape: tuple[int, ...], *, center: tuple[int, int]) -> tuple[int, int, int, int]:
        """以点击点为中心构造 OCR ROI。"""
        frame_h = int(frame_shape[0]) if len(frame_shape) >= 1 else 0
        frame_w = int(frame_shape[1]) if len(frame_shape) >= 2 else 0
        cx = int(center[0])
        cy = int(center[1])

        x1 = max(0, min(frame_w - 1, cx - LAND_SCAN_OCR_HALF_WIDTH))
        y1 = max(0, min(frame_h - 1, cy - LAND_SCAN_OCR_HALF_HEIGHT))
        x2 = max(x1 + 1, min(frame_w, cx + LAND_SCAN_OCR_HALF_WIDTH))
        y2 = max(y1 + 1, min(frame_h, cy + LAND_SCAN_OCR_HALF_HEIGHT))
        return x1, y1, x2, y2

    @staticmethod
    def _short_text(text: str, limit: int = 36) -> str:
        """截断 OCR 日志文本，避免日志过长。"""
        clean = str(text or '').strip().replace('\n', ' ')
        if len(clean) <= limit:
            return clean or '<empty>'
        return f'{clean[:limit]}...'
