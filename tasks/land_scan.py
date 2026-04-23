"""地块巡查任务。"""

from __future__ import annotations

import re

from loguru import logger

from core.base.timer import Timer
from core.engine.task.registry import TaskResult
from core.ui.assets import (
    BTN_CROP_MATURITY_TIME_SUFFIX,
    BTN_CROP_REMOVAL,
    BTN_EXPAND_BRAND,
    BTN_LAND_LEFT,
    BTN_LAND_POP_EMPTY,
    BTN_LAND_RIGHT,
    ICON_LAND_UPGRADE,
)
from core.ui.page import GOTO_MAIN, page_main
from tasks.base import TaskBase
from utils.land_grid import LandCell, get_lands_from_land_anchor
from utils.ocr_utils import OCRItem, OCRTool

# 画面横向回正手势点位 P1。
LAND_SCAN_SWIPE_H_P1 = (350, 190)
# 画面横向回正手势点位 P2。
LAND_SCAN_SWIPE_H_P2 = (200, 190)
# 地块网格行数（逻辑行）。
LAND_SCAN_ROWS = 4
# 地块网格列数（逻辑列）。
LAND_SCAN_COLS = 6
# 固定截图宽高（宽x高）。
LAND_SCAN_FRAME_WIDTH = 540
LAND_SCAN_FRAME_HEIGHT = 960
# 画面物理列总数（1,2,3,4,4,4,3,2,1）。
LAND_SCAN_PHYSICAL_COLS = 9
# 左滑阶段按“右到左”扫描的物理列数量。
LAND_SCAN_LEFT_STAGE_COL_COUNT = 5
# 右滑阶段按“左到右”扫描的物理列数量。
LAND_SCAN_RIGHT_STAGE_COL_COUNT = 4
# 成熟时间 OCR 识别大区域：相对 BTN_CROP_MATURITY_TIME_SUFFIX 中心 (dx1, dy1, dx2, dy2)。
LAND_SCAN_OCR_REGION_OFFSET = (-200, -50, 100, 50)
# 成熟时间 OCR 二次筛选窗口：相对 BTN_CROP_MATURITY_TIME_SUFFIX 中心，x 起点偏移（像素）。
LAND_SCAN_TIME_PICK_X1 = -100
# 成熟时间 OCR 二次筛选窗口：相对 BTN_CROP_MATURITY_TIME_SUFFIX 中心，x 终点偏移（像素）。
LAND_SCAN_TIME_PICK_X2 = -40
# 成熟时间 OCR 二次筛选窗口：相对 BTN_CROP_MATURITY_TIME_SUFFIX 中心，y 上边界偏移（像素）。
LAND_SCAN_TIME_PICK_Y1 = -20
# 成熟时间 OCR 二次筛选窗口：相对 BTN_CROP_MATURITY_TIME_SUFFIX 中心，y 下边界偏移（像素）。
LAND_SCAN_TIME_PICK_Y2 = 20
# 成熟时间文本正则（仅提取 HH:MM:SS）。
LAND_SCAN_MATURITY_TIME_PATTERN = re.compile(r'(\d{2}:\d{2}:\d{2})')
# 地块等级文本正则（中文等级关键词）。
LAND_SCAN_LEVEL_PATTERN = re.compile(r'(未扩建|普通|红|黑|金)')
# 地块等级英文值到中文日志文案映射。
LAND_SCAN_LEVEL_LABELS: dict[str, str] = {
    'unbuilt': '未扩建',
    'normal': '普通土地',
    'red': '红土地',
    'black': '黑土地',
    'gold': '金土地',
}
# 空地弹窗地块等级 OCR 区域：相对 BTN_LAND_POP_EMPTY 中心 (dx1, dy1, dx2, dy2)。
LAND_SCAN_LEVEL_REGION_OFFSET = (-60, -50, 40, 50)
# 已播种地块等级颜色采样点：相对 BTN_CROP_MATURITY_TIME_SUFFIX 中心 (dx, dy)。
LAND_SCAN_PLOTTED_LEVEL_COLOR_OFFSET = (85, -10)
# 已播种地块等级颜色采样窗口半径（像素，采样 (2r+1)x(2r+1) 均值）。
LAND_SCAN_PLOTTED_LEVEL_COLOR_SAMPLE_RADIUS = 1
# 已播种地块等级颜色判定阈值（RGB 欧氏距离）。
LAND_SCAN_PLOTTED_LEVEL_COLOR_DISTANCE_THRESHOLD = 42.0
# 已播种地块等级颜色静态表（RGB）。
LAND_SCAN_PLOTTED_LEVEL_COLORS_RGB: dict[str, tuple[int, int, int]] = {
    'normal': (178, 131, 74),
    'red': (223, 87, 55),
    'black': (92, 67, 42),
    'gold': (249, 203, 50),
}
# 空地弹窗升级图标 ROI：相对 BTN_LAND_POP_EMPTY 中心 (dx1, dy1, dx2, dy2)。
LAND_SCAN_UPGRADE_EMPTY_REGION_OFFSET = (-100, -50, 0, -0)
# 非空地弹窗升级图标 ROI：相对 BTN_CROP_MATURITY_TIME_SUFFIX 中心 (dx1, dy1, dx2, dy2)。
LAND_SCAN_UPGRADE_NON_EMPTY_REGION_OFFSET = (0, -50, 130, 50)
# 滑动后锚点稳定判定总时长（秒）。
LAND_SCAN_ANCHOR_STABLE_SECONDS = 0.5
# Timer reached 附加计数门槛（reached_count > count）。
LAND_SCAN_ANCHOR_STABLE_REQUIRED_HITS = 3


class TaskLandScan(TaskBase):
    """按预设顺序遍历地块并进行 OCR 收集。"""

    def __init__(self, engine, ui, *, ocr_tool: OCRTool | None = None):
        super().__init__(engine, ui)
        self.ocr_tool = ocr_tool
        self._ocr_disabled_logged = False

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """
        执行地块巡查流程，按照物理排列顺序依次点击收集信息。
        列顺序为：1-4 1-3 1-2 1-1 2-1， 6-1 5-1 4-1 3-1
        ---------------1-1---------
        ------------2-1---1-2------
        ---------3-1---2-2---1-3---
        ------4-1---3-2---2-3---1-4
        ---5-1---4-2---3-3---2-4---
        6-1---5-2---4-3---3-4------
        ---6-2---5-3---4-4---------
        ------6-3---5-4------------
        ---------6-4---------------
        """
        _ = rect
        logger.info('地块巡查: 开始')
        self.ui.ui_ensure(page_main)
        # self.ui.device.click_button(GOTO_MAIN)

        try:
            for _ in range(2):
                self.ui.device.swipe(LAND_SCAN_SWIPE_H_P1, LAND_SCAN_SWIPE_H_P2, speed=30)
            self._wait_anchor_position_stable(anchor_button=BTN_LAND_RIGHT)

            cells_after_left = self._collect_land_cells()
            if not cells_after_left:
                logger.warning('地块巡查: 未识别到地块网格，跳过任务')
                return self.fail('未识别到地块网格')
            cells_after_left = self._exclude_expand_brand_related_cells(cells_after_left)
            self._scan_cells_by_physical_columns(
                cells_after_left, from_side='right', column_count=LAND_SCAN_LEFT_STAGE_COL_COUNT
            )

            for _ in range(2):
                self.ui.device.swipe(LAND_SCAN_SWIPE_H_P2, LAND_SCAN_SWIPE_H_P1, speed=30)
            self._wait_anchor_position_stable(anchor_button=BTN_LAND_LEFT)

            cells_after_right = self._collect_land_cells()
            if not cells_after_right:
                logger.warning('地块巡查: 未识别到地块网格，跳过任务')
                return self.fail('未识别到地块网格')
            right_scan_cols = self._resolve_scan_columns(
                cells_after_right,
                from_side='left',
                column_count=LAND_SCAN_RIGHT_STAGE_COL_COUNT,
            )
            cells_after_right = self._exclude_expand_brand_related_cells(cells_after_right)
            self._scan_cells_by_physical_columns(
                cells_after_right,
                from_side='left',
                column_count=LAND_SCAN_RIGHT_STAGE_COL_COUNT,
                fixed_cols=right_scan_cols,
            )
        finally:
            # TODO 画面回正
            self.ui.ui_ensure(page_main)

        self._trigger_main_task_if_needed()
        logger.info('地块巡查: 结束')
        return self.ok()

    def _trigger_main_task_if_needed(self) -> None:
        """存在待播种或待升级地块时，拉起农场巡查任务。"""
        pending_planting = bool(self.parse_land_detail_plots_by_flag('need_planting'))
        pending_upgrade = bool(self.parse_land_detail_plots_by_flag('need_upgrade'))
        if not pending_planting and not pending_upgrade:
            return

        self.engine._task_executor.task_call('main', force_call=False)
        logger.info(
            '地块巡查: 存在待处理地块，执行农场巡查 | 待播种={} 待升级={}',
            pending_planting,
            pending_upgrade,
        )

    def _wait_anchor_position_stable(self, *, anchor_button) -> bool:
        """等待锚点位置稳定：同坐标保持 0.5s 且 reached 计数超过阈值后继续。"""
        stable_seconds = float(LAND_SCAN_ANCHOR_STABLE_SECONDS)
        required_hits = int(LAND_SCAN_ANCHOR_STABLE_REQUIRED_HITS)
        stable_timer = Timer(stable_seconds, count=required_hits)
        last_anchor: tuple[int, int] | None = None

        while 1:
            self.ui.device.screenshot()
            location = self.ui.appear_location(anchor_button, offset=30, threshold=0.95, static=False)
            current_anchor: tuple[int, int] | None = None
            if location is not None:
                current_anchor = (int(location[0]), int(location[1]))

            if current_anchor is None:
                last_anchor = None
                stable_timer.clear()
                continue

            if current_anchor != last_anchor:
                last_anchor = current_anchor
                if stable_timer.started():
                    stable_timer.reset()
                else:
                    stable_timer.start()
                continue

            if stable_timer.reached():
                return True

    def _scan_cells_by_physical_columns(
        self,
        cells: list[LandCell],
        *,
        from_side: str,
        column_count: int,
        fixed_cols: list[int] | None = None,
    ):
        """按画面物理列扫描地块（列内顺序：从上到下）。"""
        col_map: dict[int, list[LandCell]] = {}
        for cell in cells:
            physical_col = self._physical_col_rtl(cell)
            col_map.setdefault(physical_col, []).append(cell)

        if fixed_cols is not None:
            scan_cols = [int(col) for col in fixed_cols]
        else:
            scan_cols = self._resolve_scan_columns(cells, from_side=from_side, column_count=column_count)

        logger.info('地块巡查: 物理列={}', scan_cols)
        for physical_col in scan_cols:
            col_cells = list(col_map.get(physical_col, []))
            col_cells.sort(key=lambda cell: (int(cell.center[1]), int(cell.center[0])))
            for cell in col_cells:
                self._click_and_ocr_cell(cell=cell)
                self.ui.device.click_button(GOTO_MAIN)
                self.ui.device.sleep(0.2)

        return

    def _resolve_scan_columns(self, cells: list[LandCell], *, from_side: str, column_count: int) -> list[int]:
        """根据当前网格确定本轮应扫描的物理列（排除前确定，避免补列）。"""
        col_map: dict[int, list[LandCell]] = {}
        for cell in cells:
            physical_col = self._physical_col_rtl(cell)
            col_map.setdefault(physical_col, []).append(cell)
        rtl_cols = sorted(col_map.keys())
        if str(from_side).strip().lower() == 'left':
            return list(reversed(rtl_cols))[: max(0, int(column_count))]
        return rtl_cols[: max(0, int(column_count))]

    def _click_and_ocr_cell(self, *, cell: LandCell):
        """点击单个地块并采集 OCR 文本。"""
        x, y = int(cell.center[0]), int(cell.center[1])
        self.ui.device.click_point(x, y, desc=f'序号 {cell.label}')

        while 1:
            self.ui.device.screenshot()
            # 正常弹窗
            if self.ui.appear(BTN_CROP_REMOVAL, offset=30, static=False) and self.ui.appear(
                BTN_CROP_MATURITY_TIME_SUFFIX, offset=30, threshold=0.65, static=False
            ):
                break
            # 空土地弹窗
            if self.ui.appear(BTN_LAND_POP_EMPTY, offset=30, threshold=0.65, static=False):
                removal_location = self.ui.appear_location(BTN_LAND_POP_EMPTY, offset=30, threshold=0.65, static=False)
                need_upgrade = self._detect_need_upgrade(anchor=removal_location, empty_plot=True)
                need_planting = True
                roi = self._build_land_level_region(removal_location)
                level_items = self.ocr_tool.detect(self.ui.device.image, region=roi, scale=1.2, alpha=1.1, beta=0.0)
                level_text = self._merge_ocr_items_text(level_items)
                level = self._extract_land_level(level_text)
                logger.info(
                    '地块巡查: 空地等级OCR | 序号={} text={} 等级={}',
                    cell.label,
                    self._short_text(level_text),
                    self._level_label(level),
                )
                update_level = level or None
                if not level:
                    logger.warning(
                        '地块巡查: 未识别到等级，更新其他字段 | 序号={} 等级={} 需要升级={} 需要播种={}',
                        cell.label,
                        level_text,
                        need_upgrade,
                        need_planting,
                    )
                updated = self._update_plot_fields(
                    plot_id=cell.label,
                    level=update_level,
                    countdown='',
                    need_upgrade=need_upgrade,
                    need_planting=need_planting,
                )
                if updated:
                    self._save_plot_update(
                        plot_id=cell.label,
                        level=update_level,
                        countdown='',
                        need_upgrade=need_upgrade,
                        need_planting=need_planting,
                    )
                return
            self.ui.device.sleep(0.2)

        removal_location = self.ui.appear_location(
            BTN_CROP_MATURITY_TIME_SUFFIX, offset=30, threshold=0.65, static=False
        )
        need_upgrade = self._detect_need_upgrade(anchor=removal_location, empty_plot=False)
        need_planting = False
        countdown: str | None = None

        if removal_location is None:
            logger.warning('地块巡查: 未识别到成熟时间锚点，跳过 OCR | 序号={}', cell.label)
        else:
            roi = self._build_ocr_region(removal_location)
            items = self.ocr_tool.detect(self.ui.device.image, region=roi, scale=1.2, alpha=1.1, beta=0.0)
            text, score, tokens = self._pick_time_tokens_near_suffix(items=items, anchor=removal_location)
            countdown = self._extract_maturity_time(text)
            display_text = countdown or text
            logger.debug(
                '地块巡查: OCR筛选 | region={} pick_offset=({}, {}, {}, {}) tokens={} text={}',
                roi,
                LAND_SCAN_TIME_PICK_X1,
                LAND_SCAN_TIME_PICK_Y1,
                LAND_SCAN_TIME_PICK_X2,
                LAND_SCAN_TIME_PICK_Y2,
                tokens,
                display_text or '<empty>',
            )
            logger.info(
                '地块巡查: OCR | 序号={} text={} score={:.3f}', cell.label, self._short_text(display_text), score
            )

        level, _, _ = self._detect_plotted_land_level_by_color(removal_location)

        updated = self._update_plot_fields(
            plot_id=cell.label,
            level=level or None,
            countdown=countdown,
            need_upgrade=need_upgrade,
            need_planting=need_planting,
        )
        if updated:
            self._save_plot_update(
                plot_id=cell.label,
                level=level or None,
                countdown=countdown,
                need_upgrade=need_upgrade,
                need_planting=need_planting,
            )
        return

    def _detect_need_upgrade(self, *, anchor: tuple[int, int] | None, empty_plot: bool) -> bool:
        """识别当前地块弹窗是否出现升级图标（GIF 多帧匹配）。"""
        if anchor is None:
            return False
        roi = self._build_upgrade_icon_region(anchor, empty_plot=empty_plot)
        matched = self.ui.match_gif_multi(ICON_LAND_UPGRADE, roi=roi)
        return bool(matched)

    @staticmethod
    def _build_upgrade_icon_region(center: tuple[int, int], *, empty_plot: bool) -> tuple[int, int, int, int]:
        """按锚点与偏移构造升级图标检测 ROI。"""
        dx1, dy1, dx2, dy2 = (
            LAND_SCAN_UPGRADE_EMPTY_REGION_OFFSET if empty_plot else LAND_SCAN_UPGRADE_NON_EMPTY_REGION_OFFSET
        )
        cx = int(center[0])
        cy = int(center[1])
        x1 = int(cx + dx1)
        y1 = int(cy + dy1)
        x2 = int(cx + dx2)
        y2 = int(cy + dy2)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        x1 = max(0, min(x1, LAND_SCAN_FRAME_WIDTH - 1))
        y1 = max(0, min(y1, LAND_SCAN_FRAME_HEIGHT - 1))
        x2 = max(x1 + 1, min(x2, LAND_SCAN_FRAME_WIDTH))
        y2 = max(y1 + 1, min(y2, LAND_SCAN_FRAME_HEIGHT))
        return x1, y1, x2, y2

    def _detect_plotted_land_level_by_color(
        self,
        anchor: tuple[int, int] | None,
    ) -> tuple[str, tuple[int, int, int] | None, float]:
        """按成熟时间后缀锚点偏移取色，识别已播种地块等级。"""
        if anchor is None:
            return '', None, 0.0
        bgr = self._sample_color_bgr_near_anchor(
            anchor=anchor,
            offset=LAND_SCAN_PLOTTED_LEVEL_COLOR_OFFSET,
            radius=LAND_SCAN_PLOTTED_LEVEL_COLOR_SAMPLE_RADIUS,
        )
        if bgr is None:
            return '', None, 0.0
        rgb = (int(bgr[2]), int(bgr[1]), int(bgr[0]))
        best_level = ''
        best_distance = float('inf')
        for level, color_rgb in LAND_SCAN_PLOTTED_LEVEL_COLORS_RGB.items():
            dr = float(rgb[0] - int(color_rgb[0]))
            dg = float(rgb[1] - int(color_rgb[1]))
            db = float(rgb[2] - int(color_rgb[2]))
            distance = float((dr * dr + dg * dg + db * db) ** 0.5)
            if distance < best_distance:
                best_distance = distance
                best_level = str(level)
        if best_distance > float(LAND_SCAN_PLOTTED_LEVEL_COLOR_DISTANCE_THRESHOLD):
            return '', rgb, best_distance
        return best_level, rgb, best_distance

    def _sample_color_bgr_near_anchor(
        self,
        *,
        anchor: tuple[int, int],
        offset: tuple[int, int],
        radius: int,
    ) -> tuple[int, int, int] | None:
        """相对锚点采样颜色均值（BGR）。"""
        image = getattr(getattr(self.ui, 'device', None), 'image', None)
        if image is None:
            return None
        h, w = image.shape[:2]
        cx = int(anchor[0]) + int(offset[0])
        cy = int(anchor[1]) + int(offset[1])
        cx = max(0, min(cx, w - 1))
        cy = max(0, min(cy, h - 1))
        r = max(0, int(radius))
        x1 = max(0, cx - r)
        y1 = max(0, cy - r)
        x2 = min(w, cx + r + 1)
        y2 = min(h, cy + r + 1)
        patch = image[y1:y2, x1:x2]
        if patch.size <= 0:
            return None
        mean_bgr = patch.reshape(-1, 3).mean(axis=0)
        return int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])

    def _collect_land_cells(self) -> list[LandCell]:
        """识别左右锚点并推算地块网格。"""
        self.ui.device.screenshot()
        right_anchor = self.ui.appear_location(BTN_LAND_RIGHT, offset=30, threshold=0.95, static=False)
        left_anchor = self.ui.appear_location(BTN_LAND_LEFT, offset=30, threshold=0.95, static=False)

        cells = get_lands_from_land_anchor(
            right_anchor, left_anchor, rows=LAND_SCAN_ROWS, cols=LAND_SCAN_COLS, start_anchor='right'
        )
        logger.info('地块巡查: 网格识别 | 右锚点={} 左锚点={} 地块总计={}', right_anchor, left_anchor, len(cells))
        return cells

    def _exclude_expand_brand_related_cells(self, cells: list[LandCell]) -> list[LandCell]:
        """按 BTN_EXPAND_BRAND 位置排除不可统计地块。"""
        brand_location = self.ui.appear_location(BTN_EXPAND_BRAND, offset=30, static=False)
        if brand_location is None:
            return cells
        target_cell = self._pick_nearest_cell(cells, brand_location)
        if target_cell is None:
            return cells

        excluded_labels = self._build_expand_brand_excluded_labels(target_cell)
        filtered = [cell for cell in cells if cell.label not in excluded_labels]
        logger.info(
            '地块巡查: 排除未扩建地块 | 排除序号={} 剩余={}/{}', sorted(excluded_labels), len(filtered), len(cells)
        )
        return filtered

    @staticmethod
    def _pick_nearest_cell(cells: list[LandCell], point: tuple[int, int]) -> LandCell | None:
        """返回与 point 距离最近的地块。"""
        if not cells:
            return None
        px = int(point[0])
        py = int(point[1])
        return min(cells, key=lambda cell: (int(cell.center[0]) - px) ** 2 + (int(cell.center[1]) - py) ** 2)

    @staticmethod
    def _build_expand_brand_excluded_labels(cell: LandCell) -> set[str]:
        """构造需排除的序号集合：当前及下方整列、左侧整列。"""
        col = int(cell.col)
        row = int(cell.row)
        labels: set[str] = set()

        # 当前列：从命中行到最下方全部排除（当前 + 下侧）。
        for r in range(row, LAND_SCAN_ROWS + 1):
            labels.add(f'{col}-{r}')

        # 左侧列：整列排除（全行）。
        left_col = col + 1
        if left_col <= LAND_SCAN_COLS:
            for r in range(1, LAND_SCAN_ROWS + 1):
                labels.add(f'{left_col}-{r}')
        return labels

    @staticmethod
    def _physical_col_rtl(cell: LandCell) -> int:
        """将地块映射为物理列索引（右到左，范围 1..9）。"""
        logical_col = int(cell.col)
        logical_row = int(cell.row)
        idx = (LAND_SCAN_ROWS - logical_row) + (logical_col - 1) + 1
        return max(1, min(LAND_SCAN_PHYSICAL_COLS, idx))

    @staticmethod
    def _build_ocr_region(center: tuple[int, int]) -> tuple[int, int, int, int]:
        """以 center 为基准，按固定偏移构造 OCR ROI。"""
        cx = int(center[0])
        cy = int(center[1])
        dx1, dy1, dx2, dy2 = LAND_SCAN_OCR_REGION_OFFSET
        x1 = int(cx + dx1)
        y1 = int(cy + dy1)
        x2 = int(cx + dx2)
        y2 = int(cy + dy2)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        x1 = max(0, min(x1, LAND_SCAN_FRAME_WIDTH - 1))
        y1 = max(0, min(y1, LAND_SCAN_FRAME_HEIGHT - 1))
        x2 = max(x1 + 1, min(x2, LAND_SCAN_FRAME_WIDTH))
        y2 = max(y1 + 1, min(y2, LAND_SCAN_FRAME_HEIGHT))
        return x1, y1, x2, y2

    @staticmethod
    def _build_land_level_region(center: tuple[int, int]) -> tuple[int, int, int, int]:
        """以空地弹窗锚点为基准，构造地块等级 OCR ROI。"""
        cx = int(center[0])
        cy = int(center[1])
        dx1, dy1, dx2, dy2 = LAND_SCAN_LEVEL_REGION_OFFSET
        x1 = int(cx + dx1)
        y1 = int(cy + dy1)
        x2 = int(cx + dx2)
        y2 = int(cy + dy2)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        x1 = max(0, min(x1, LAND_SCAN_FRAME_WIDTH - 1))
        y1 = max(0, min(y1, LAND_SCAN_FRAME_HEIGHT - 1))
        x2 = max(x1 + 1, min(x2, LAND_SCAN_FRAME_WIDTH))
        y2 = max(y1 + 1, min(y2, LAND_SCAN_FRAME_HEIGHT))
        return x1, y1, x2, y2

    @staticmethod
    def _merge_ocr_items_text(items: list[OCRItem]) -> str:
        """将 OCR items 按 x 坐标拼接为文本。"""
        if not items:
            return ''
        ordered = sorted(items, key=lambda item: min(float(point[0]) for point in item.box))
        return ''.join(str(item.text or '').strip() for item in ordered if str(item.text or '').strip()).strip()

    @staticmethod
    def _extract_land_level(text: str) -> str:
        """从中文 land_level 文本解析配置 level 值。"""
        raw = str(text or '').strip().replace(' ', '')
        if not raw:
            return ''
        match = LAND_SCAN_LEVEL_PATTERN.search(raw)
        if not match:
            return ''
        token = str(match.group(1))
        if token == '未扩建':
            return 'unbuilt'
        if token == '普通':
            return 'normal'
        if token == '红':
            return 'red'
        if token == '黑':
            return 'black'
        if token == '金':
            return 'gold'
        return ''

    @staticmethod
    def _level_label(level: str | None) -> str:
        """将配置等级值映射为中文日志文案。"""
        text = str(level or '').strip().lower()
        if not text:
            return '<empty>'
        return str(LAND_SCAN_LEVEL_LABELS.get(text, level))

    @staticmethod
    def _pick_time_tokens_near_suffix(
        items: list[OCRItem],
        anchor: tuple[int, int],
    ) -> tuple[str, float, list[str]]:
        """从 OCR 明细中二次筛选目标窗口内的 token，并按 x 从左到右拼接。"""
        ax = int(anchor[0])
        ay = int(anchor[1])
        x1 = float(ax + LAND_SCAN_TIME_PICK_X1)
        x2 = float(ax + LAND_SCAN_TIME_PICK_X2)
        y1 = float(ay + LAND_SCAN_TIME_PICK_Y1)
        y2 = float(ay + LAND_SCAN_TIME_PICK_Y2)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        candidates: list[tuple[float, str, float]] = []
        for item in items:
            text = str(item.text or '').strip()
            if not text:
                continue
            xs = [float(point[0]) for point in item.box]
            ys = [float(point[1]) for point in item.box]
            min_x = float(min(xs))
            max_x = float(max(xs))
            min_y = float(min(ys))
            max_y = float(max(ys))
            # 参考好友昵称做法：先拿 OCR item，再按目标窗口做 bbox 筛选。
            if max_x <= x1 or min_x >= x2:
                continue
            if max_y <= y1 or min_y >= y2:
                continue
            candidates.append((min_x, text, float(item.score)))

        candidates.sort(key=lambda row: row[0])
        tokens = [row[1] for row in candidates]
        merged = ''.join(tokens).strip()
        if not candidates:
            return '', 0.0, []
        score = float(sum(row[2] for row in candidates) / len(candidates))
        return merged, score, tokens

    @staticmethod
    def _short_text(text: str, limit: int = 36) -> str:
        """截断 OCR 日志文本，避免日志过长。"""
        clean = str(text or '').strip().replace('\n', ' ')
        if len(clean) <= limit:
            return clean or '<empty>'
        return f'{clean[:limit]}...'

    @staticmethod
    def _extract_maturity_time(text: str) -> str:
        """从 OCR 文本提取 HH:MM:SS。"""
        raw = str(text or '').strip()
        if not raw:
            return ''
        match = LAND_SCAN_MATURITY_TIME_PATTERN.search(raw)
        if not match:
            return ''
        return str(match.group(1))

    def _update_plot_fields(
        self,
        *,
        plot_id: str,
        level: str | None = None,
        countdown: str | None = None,
        need_upgrade: bool | None = None,
        need_planting: bool | None = None,
    ) -> bool:
        """回写单个地块字段（同地块统一更新）。"""
        target = str(plot_id or '').strip()
        if not target:
            return False
        land_cfg = getattr(self.engine.config, 'land', None)
        plots = getattr(land_cfg, 'plots', None)
        if not isinstance(plots, list):
            return False

        normalized_level: str | None = None
        if level is not None:
            raw_level = str(level or '').strip().lower()
            normalized_level = raw_level or None
        normalized_countdown: str | None = None
        if countdown is not None:
            normalized_countdown = str(countdown or '').strip()

        for item in plots:
            if not isinstance(item, dict):
                continue
            if str(item.get('plot_id', '')).strip() != target:
                continue
            old_level = str(item.get('level', '') or '').strip().lower()
            old_countdown = str(item.get('maturity_countdown', '') or '').strip()
            old_need_upgrade = bool(item.get('need_upgrade', False))
            old_need_planting = bool(item.get('need_planting', False))
            changed = False
            if normalized_level is not None and old_level != normalized_level:
                item['level'] = normalized_level
                changed = True
            if normalized_countdown is not None and old_countdown != normalized_countdown:
                item['maturity_countdown'] = normalized_countdown
                changed = True
            if need_upgrade is not None and old_need_upgrade != bool(need_upgrade):
                item['need_upgrade'] = bool(need_upgrade)
                changed = True
            if need_planting is not None and old_need_planting != bool(need_planting):
                item['need_planting'] = bool(need_planting)
                changed = True
            return changed
        return False

    def _save_plot_update(
        self,
        *,
        plot_id: str,
        level: str | None = None,
        countdown: str | None = None,
        need_upgrade: bool | None = None,
        need_planting: bool | None = None,
    ) -> None:
        """单地块统一字段更新后立即落盘。"""
        try:
            self.engine.config.save()
        except Exception as exc:
            logger.warning(
                '地块巡查: 地块信息写入配置失败 | 序号={} 等级={} 成熟倒计时={} 需要升级={} 需要播种={} error={}',
                plot_id,
                self._level_label(level),
                countdown,
                need_upgrade,
                need_planting,
                exc,
            )
            return
        self._emit_config_snapshot()
        logger.info(
            '地块巡查: 地块信息已更新 | 序号={} 等级={} 成熟倒计时={} 需要升级={} 需要播种={}',
            plot_id,
            self._level_label(level),
            countdown,
            need_upgrade,
            need_planting,
        )

    def _emit_config_snapshot(self) -> None:
        """写盘后主动推送一次配置快照，避免 UI 长时间持有旧数据。"""
        emitter = getattr(self.engine, '_emit_config_now', None)
        if callable(emitter):
            try:
                emitter()
            except Exception:
                return

    def _get_config_path_for_log(self) -> str:
        """返回当前配置路径，便于日志排查写入目标。"""
        path = str(getattr(getattr(self.engine, 'config', None), '_config_path', '') or '').strip()
        return path or '<empty>'
