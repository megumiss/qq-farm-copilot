"""TaskMain 播种逻辑。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from loguru import logger

from core.base.timer import Timer
from core.ui.assets import *
from core.ui.page import GOTO_MAIN, page_main
from tasks.main import (
    ALWAYS_SKIP_SEED_BUTTONS,
    BACKGROUND_TREE_STABLE_CHECK_INTERVAL_SECONDS,
    LAND_MATCH_Y_RANGE,
    SEED_POPUP_NUMBER_REGION_X_MAX,
    SEED_POPUP_NUMBER_REGION_X_MIN,
    SEED_POPUP_NUMBER_REGION_Y_OFFSET_BOTTOM,
    SEED_POPUP_NUMBER_REGION_Y_OFFSET_TOP,
)
from tasks.main_buy_seed import TaskMainBuySeedMixin
from utils.bg_patch_number_ocr import BgPatchNumberItem

if TYPE_CHECKING:
    from core.engine.bot.local_engine import LocalBotEngine
    from core.ui.ui import UI
    from models.config import AppConfig


class TaskMainPlantingMixin(TaskMainBuySeedMixin):
    """提供播种主链路。"""

    config: 'AppConfig'
    engine: 'LocalBotEngine'
    ui: 'UI'

    def _run_feature_plant(self) -> str | None:
        """自动播种"""
        logger.info('自动播种: 开始')
        self.ui.ui_ensure(page_main)

        # 点击空白处
        self.ui.device.click_button(GOTO_MAIN)
        self.align_view_by_background_tree(log_prefix='自动播种')

        # 判断是否需要播种
        # has_land = self.ui.appear_any(LAND_LIST, offset=30, threshold=0.89, static=False)
        # if not has_land:
        #     logger.info('无需播种')
        #     return

        self._plant_all(self.engine._resolve_crop_name())

    @staticmethod
    def _get_icon_land_buttons() -> list[Button]:
        """返回 assets 中所有 `icon_land_` 按钮定义。"""
        buttons = [btn for name, btn in ASSET_NAME_TO_CONST.items() if str(name).startswith('icon_land_')]
        buttons.sort(key=lambda btn: str(btn.name))
        return buttons

    @staticmethod
    def _get_seed_buttons_for_exclusion() -> list[Button]:
        """返回当前应参与排除的作物模板列表。"""
        buttons: list[Button] = [btn for btn in ALWAYS_SKIP_SEED_BUTTONS if btn is not None]
        buttons.sort(key=lambda btn: str(btn.name))
        return buttons

    @staticmethod
    def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        """计算两个框的 IoU。"""
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
    def _bbox_center(area: tuple[int, int, int, int]) -> tuple[float, float]:
        """返回框中心点。"""
        x1, y1, x2, y2 = area
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0

    def _is_same_land_bbox(self, a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
        """地块去重判定：IoU 或中心点距离接近。"""
        if self._bbox_iou(a, b) >= 0.35:
            return True
        ax, ay = self._bbox_center(a)
        bx, by = self._bbox_center(b)
        return math.hypot(ax - bx, ay - by) <= 10.0

    def _collect_land_coords_for_plant(
        self,
        threshold: float = 0.85,
        y_range: tuple[int, int] | None = None,
    ) -> list[tuple[int, int]]:
        """匹配并去重空白地块模板，按 y 轴范围过滤后返回全部地块中心坐标。"""
        self.ui.device.screenshot()

        land_buttons = self._get_icon_land_buttons()
        if not land_buttons:
            logger.warning('自动播种: 未找到地块模板')
            return []

        priority = {
            'icon_land_amethyst': 50,
            'icon_land_gold': 40,
            'icon_land_gold_2': 40,
            'icon_land_red': 30,
            'icon_land_black': 20,
            'icon_land_stand': 10,
        }

        raw_hits: list[dict] = []
        for button in land_buttons:
            matches = self.ui.match_template_multi(button, threshold=float(threshold))
            for det in matches:
                x1, y1, x2, y2 = map(int, det.area)
                raw_hits.append(
                    {
                        'name': str(button.name),
                        'area': (x1, y1, x2, y2),
                        'priority': int(priority.get(str(button.name), 0)),
                    }
                )

        raw_total = len(raw_hits)
        if y_range is not None:
            y_min, y_max = int(y_range[0]), int(y_range[1])
            if y_min > y_max:
                y_min, y_max = y_max, y_min
            filtered_hits: list[dict] = []
            for hit in raw_hits:
                _, y1, _, y2 = hit['area']
                center_y = (y1 + y2) // 2
                if y_min <= center_y <= y_max:
                    filtered_hits.append(hit)
            raw_hits = filtered_hits

        raw_hits.sort(key=lambda item: (-item['priority'], item['area'][1], item['area'][0]))

        deduped: list[dict] = []
        for cand in raw_hits:
            if any(self._is_same_land_bbox(cand['area'], old['area']) for old in deduped):
                continue
            deduped.append(cand)

        coords = []
        for det in deduped:
            x1, y1, x2, y2 = det['area']
            coords.append(((x1 + x2) // 2, (y1 + y2) // 2))
        coords.sort(key=lambda p: (p[1], p[0]))

        logger.info(
            '自动播种: 地块匹配完成 | 模板数={} 原始命中={} 范围内命中={} 去重后={} 坐标数={} 纵向范围={}',
            len(land_buttons),
            raw_total,
            len(raw_hits),
            len(deduped),
            len(coords),
            y_range,
        )
        return coords

    @staticmethod
    def _merge_land_coords(
        base_coords: list[tuple[int, int]],
        extra_coords: list[tuple[int, int]],
        *,
        near_distance: float = 10.0,
    ) -> list[tuple[int, int]]:
        """合并并去重点位坐标。"""
        merged: list[tuple[int, int]] = []
        for point in [*base_coords, *extra_coords]:
            px, py = int(point[0]), int(point[1])
            if any(math.hypot(float(px - ox), float(py - oy)) <= float(near_distance) for ox, oy in merged):
                continue
            merged.append((px, py))
        merged.sort(key=lambda p: (p[1], p[0]))
        return merged

    @staticmethod
    def _select_center_land_coord(coords: list[tuple[int, int]]) -> tuple[int, int] | None:
        """优先选最上方地块，再选 x 最靠近中心的地块。"""
        if not coords:
            return None
        avg_x = sum(x for x, _ in coords) / float(len(coords))
        min_y = min(y for _, y in coords)
        top_row = [point for point in coords if point[1] == min_y]
        return min(top_row, key=lambda p: abs(p[0] - avg_x))

    def _get_labor_anchor_location(self) -> tuple[int, int] | None:
        """识别背景树锚点位置，用于估计画面平移。"""
        self.ui.device.screenshot()
        return self.ui.appear_location(BTN_BACKGROUND_TREE, offset=30, threshold=0.8, static=False)

    def _wait_labor_anchor_stable(self) -> tuple[int, int] | None:
        """等待背景树锚点连续稳定一段时间后返回坐标。"""
        stable_seconds = max(0.1, float(self.config.planting.planting_stable_seconds))
        stable_timer = Timer(stable_seconds, count=3)
        timeout_seconds = max(0.1, float(self.config.planting.planting_stable_timeout_seconds))
        timeout_timer = Timer(timeout_seconds, count=1).start()
        last_anchor: tuple[int, int] | None = None
        while 1:
            anchor = self._get_labor_anchor_location()
            if anchor is None:
                last_anchor = None
                stable_timer.clear()
            else:
                current_anchor = (int(anchor[0]), int(anchor[1]))
                if current_anchor != last_anchor:
                    last_anchor = current_anchor
                    stable_timer.start()
                elif stable_timer.reached():
                    return current_anchor

            if timeout_timer.reached():
                logger.warning(
                    '自动播种: 背景树锚点稳定等待超时 | 超时={}s',
                    timeout_seconds,
                )
                return None
            self.ui.device.sleep(BACKGROUND_TREE_STABLE_CHECK_INTERVAL_SECONDS)

    @staticmethod
    def _shift_land_coords(coords: list[tuple[int, int]], dx: float, dy: float) -> list[tuple[int, int]]:
        """按平移量修正地块坐标。"""
        return [(int(round(x + dx)), int(round(y + dy))) for x, y in coords]

    def _build_seed_popup_number_region(self, land_click_point: tuple[int, int]) -> tuple[int, int, int, int]:
        """按地块点击坐标构建种子数字识别区域。"""
        click_y = int(land_click_point[1])
        x1 = int(SEED_POPUP_NUMBER_REGION_X_MIN)
        x2 = int(SEED_POPUP_NUMBER_REGION_X_MAX)
        y1 = click_y + int(SEED_POPUP_NUMBER_REGION_Y_OFFSET_TOP)
        y2 = click_y + int(SEED_POPUP_NUMBER_REGION_Y_OFFSET_BOTTOM)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        return x1, y1, x2, y2

    def _detect_seed_number_items(
        self,
        cv_img,
        land_click_point: tuple[int, int],
    ) -> list[BgPatchNumberItem]:
        """在种子弹窗区域识别数字块。"""
        if cv_img is None:
            return []
        region = self._build_seed_popup_number_region(land_click_point)
        items = self.seed_number_ocr.detect_items(cv_img, region=region)
        logger.info(
            '自动播种: 种子数量 | 点击纵坐标={} 区域={} 数量={} 数字={}',
            int(land_click_point[1]),
            region,
            len(items),
            [it.text for it in items],
        )
        return items

    def _collect_excluded_seed_item_indexes(
        self,
        number_items: list[BgPatchNumberItem],
        *,
        threshold: float = 0.80,
        near_distance: float = 50.0,
    ) -> set[int]:
        """识别固定排除模板并返回需排除的数字块索引集合。"""
        if not number_items:
            return set()

        seed_buttons = self._get_seed_buttons_for_exclusion()
        if not seed_buttons:
            return set()

        seed_points: list[tuple[int, int]] = []
        for seed_btn in seed_buttons:
            loc = self.ui.appear_location(seed_btn, offset=30, threshold=float(threshold), static=False)
            if loc is None:
                continue
            if any(math.hypot(float(loc[0] - old[0]), float(loc[1] - old[1])) <= 6.0 for old in seed_points):
                continue
            seed_points.append((int(loc[0]), int(loc[1])))

        excluded_indexes: set[int] = set()
        for idx, item in enumerate(number_items):
            box_x, box_y, box_w, box_h = item.box
            box_cx = float(box_x) + float(box_w) / 2.0
            box_cy = float(box_y) + float(box_h) / 2.0
            dynamic_near = max(float(near_distance), float(max(box_w, box_h)) * 0.75)
            for sx, sy in seed_points:
                if math.hypot(box_cx - float(sx), box_cy - float(sy)) <= dynamic_near:
                    excluded_indexes.add(int(idx))
                    break
        return excluded_indexes

    def _select_seed_from_popup_by_exclusion_policy(
        self,
        land_click_point: tuple[int, int],
    ) -> tuple[int, int] | None:
        """按固定排除规则选择候选框中从左到右的首个可用种子。"""
        cv_img = self.ui.device.screenshot()
        number_items = self._detect_seed_number_items(cv_img, land_click_point)
        if not number_items:
            logger.warning('自动播种: 候选框未识别到种子数量块，无法按排除规则选种')
            return None

        excluded_indexes = self._collect_excluded_seed_item_indexes(number_items)
        ordered_indexes = sorted(
            range(len(number_items)),
            key=lambda idx: float(number_items[idx].box[0] + number_items[idx].box[2] / 2.0),
        )
        for idx in ordered_indexes:
            if idx in excluded_indexes:
                continue
            box_x, box_y, box_w, box_h = number_items[idx].box
            point = (int(box_x + box_w / 2), int(box_y + box_h / 2))
            logger.info(
                '自动播种: 按排除规则选择种子 | 数量块序号={} 拖拽点={} 排除索引={}',
                idx + 1,
                point,
                sorted(excluded_indexes),
            )
            return point

        logger.warning(
            '自动播种: 候选框内种子均被固定排除，无法播种 | 总数={} 排除索引={}',
            len(number_items),
            sorted(excluded_indexes),
        )
        return None

    def _collect_pending_plant_land_coords(self) -> tuple[list[tuple[int, int]], list[str]]:
        """收集当前需要播种的地块坐标与配置引用。"""
        detected_land_coords = self._collect_land_coords_for_plant(threshold=0.85, y_range=LAND_MATCH_Y_RANGE)
        if self.is_task_enabled('land_scan'):
            detail_targets = self.collect_land_targets_by_flag('need_planting', log_prefix='自动播种: 空地补充')
        else:
            detail_targets = []
        detail_land_coords = [point for _, point in detail_targets]
        pending_plot_refs = [str(ref) for ref, _ in detail_targets]
        land_coords = self._merge_land_coords(detected_land_coords, detail_land_coords)
        logger.info('自动播种: 空地识别完成 | 数量={}', len(land_coords))
        return land_coords, pending_plot_refs

    def _open_seed_popup(self, land_click_point: tuple[int, int]) -> bool:
        """点击空地并等待种子候选框出现。"""
        land_x, land_y = int(land_click_point[0]), int(land_click_point[1])
        for attempt in range(1, 3):
            self.engine.device.click_point(land_x, land_y, desc='点击可播种地块')
            self.ui.device.sleep(0.5)
            cv_img = self.ui.device.screenshot()
            number_items = self._detect_seed_number_items(cv_img, (land_x, land_y))
            if number_items:
                return True
            if self.ui.appear(BTN_CROP_REMOVAL, offset=30, static=False):
                logger.info('自动播种: 该地块已种植，结束本轮播种 | 坐标=({}, {})', land_x, land_y)
                self.ui.device.click_button(GOTO_MAIN)
                self.ui.device.sleep(0.2)
                return False
            logger.debug('自动播种: 种子候选框未出现，重试 | 次数={}', attempt)
        return False

    def _get_seed_popup_item_points(self, land_click_point: tuple[int, int]) -> list[tuple[int, int]]:
        """返回当前候选框中按从左到右排列的种子拖拽点。"""
        cv_img = self.ui.device.screenshot()
        items = self._detect_seed_number_items(cv_img, land_click_point)
        ordered = sorted(items, key=lambda item: float(item.box[0] + item.box[2] / 2.0))
        points: list[tuple[int, int]] = []
        for item in ordered[:5]:
            box_x, box_y, box_w, box_h = item.box
            points.append((int(box_x + box_w / 2), int(box_y + box_h / 2)))
        return points

    def _turn_seed_popup_to_page(self, page_index: int) -> bool:
        """将种子候选框翻到指定页，page_index 从 0 开始。"""
        target_page = max(0, int(page_index))
        for _ in range(target_page):
            if not self.ui.appear_then_click(
                BTN_SEED_SELECT_POPUP_RIGHT,
                offset=30,
                threshold=0.85,
                interval=1,
                static=False,
            ):
                logger.warning('自动播种: 种子候选框翻页失败 | 目标页={}', target_page)
                return False
            self.ui.device.sleep(1.05)
        return True

    def _select_seed_from_popup_by_warehouse_index(
        self,
        seed_index: int,
        land_click_point: tuple[int, int],
    ) -> tuple[int, int] | None:
        """按仓库序号在空地种子候选框中选择种子。"""
        if seed_index <= 0:
            return None
        page_index = (int(seed_index) - 1) // 5
        page_slot_index = (int(seed_index) - 1) % 5
        if not self._turn_seed_popup_to_page(page_index):
            return None

        points = self._get_seed_popup_item_points(land_click_point)
        if page_slot_index >= len(points):
            logger.warning(
                '自动播种: 候选框种子数量不足 | 仓库序号={} 页码={} 页内格={} 坐标列表={}',
                seed_index,
                page_index,
                page_slot_index + 1,
                points,
            )
            return None
        point = points[page_slot_index]
        logger.info(
            '自动播种: 按仓库序号选择种子 | 仓库序号={} 页码={} 页内格={} 拖拽点={}',
            seed_index,
            page_index,
            page_slot_index + 1,
            point,
        )
        return point

    def _drag_seed_to_lands(
        self,
        seed_drag_point: tuple[int, int],
        land_coords: list[tuple[int, int]],
    ) -> None:
        """拖拽选中种子到全部待播种地块。"""
        dragging = False
        try:
            drag_x, drag_y = int(seed_drag_point[0]), int(seed_drag_point[1])
            self.engine.device.drag_down_point(drag_x, drag_y, duration=0.1)
            dragging = True
            self.ui.device.sleep(0.1)

            for land_x, land_y in land_coords:
                self.engine.device.drag_move_point(int(land_x), int(land_y), duration=0.1)
                self.ui.device.sleep(0.15)
        finally:
            if dragging:
                self.engine.device.drag_up()
                logger.info('自动播种: 播种完成')

    def _prepare_lands_and_open_seed_popup(
        self,
    ) -> tuple[str, list[tuple[int, int]], list[str], tuple[int, int] | None]:
        """回到主界面后收集空地并打开种子候选框。"""
        self.ui.ui_ensure(page_main)
        self.ui.device.click_button(GOTO_MAIN)
        self.align_view_by_background_tree(log_prefix='自动播种')

        land_coords, pending_plot_refs = self._collect_pending_plant_land_coords()
        if not land_coords:
            logger.info('自动播种: 未发现空土地，跳过播种')
            return 'no_land', [], [], None

        before_labor_anchor = self._get_labor_anchor_location()
        seed_popup_land = self._select_center_land_coord(land_coords) or land_coords[0]
        if not self._open_seed_popup(seed_popup_land):
            logger.warning('自动播种: 打开种子候选框失败')
            return 'no_seed_popup', land_coords, pending_plot_refs, None

        after_labor_anchor = self._wait_labor_anchor_stable()
        if before_labor_anchor is not None and after_labor_anchor is not None:
            dx = float(after_labor_anchor[0] - before_labor_anchor[0])
            dy = float(after_labor_anchor[1] - before_labor_anchor[1])
            drift = math.hypot(dx, dy)
            if drift > 3.0:
                logger.info('自动播种: 画面偏移 {:.1f}px，已修正播种坐标', drift)
            land_coords = self._shift_land_coords(land_coords, dx, dy)
            seed_popup_land = (int(round(seed_popup_land[0] + dx)), int(round(seed_popup_land[1] + dy)))
        else:
            logger.warning('自动播种: 背景树锚点识别失败，继续使用原始地块坐标')

        return 'ready', land_coords, pending_plot_refs, seed_popup_land

    def _plant_all(self, crop_name: str) -> list[str]:
        """执行整块农田播种流程。"""

        warehouse_first = bool(self.config.planting.warehouse_first)
        skip_event_crops = bool(self.config.planting.skip_event_crops)
        use_warehouse_first = warehouse_first and not skip_event_crops
        if warehouse_first and skip_event_crops:
            logger.info('自动播种: 仓库优先与排除活动作物同时开启，按关闭仓库优先处理')

        seed_index: int | None = None
        if not use_warehouse_first:
            seed_index = self._ensure_seed_index_in_warehouse(crop_name)
            if seed_index is None:
                logger.warning('自动播种: 仓库确认种子失败，结束本轮 | 作物={}', crop_name)
                return []

        prepare_status, land_coords, pending_plot_refs, seed_popup_land = self._prepare_lands_and_open_seed_popup()
        if prepare_status == 'no_land':
            return []
        if prepare_status == 'no_seed_popup':
            if not use_warehouse_first:
                logger.info('自动播种: 未发现种子候选框，尝试购买种子并重试 | 作物={}', crop_name)
                buy_result = self._buy_seeds(crop_name)
                if not buy_result:
                    logger.warning('自动播种: 购买种子失败或未完成，结束本轮播种 | 作物={}', crop_name)
                    return []
                return self._plant_all(crop_name)
            if use_warehouse_first:
                logger.info('自动播种: 未发现种子候选框，尝试购买种子并重试 | 作物={}', crop_name)
                buy_result = self._buy_seeds(crop_name)
                if not buy_result:
                    logger.warning('自动播种: 购买种子失败或未完成，结束本轮播种 | 作物={}', crop_name)
                    return []
                return self._plant_all(crop_name)
            return []
        if prepare_status != 'ready' or seed_popup_land is None:
            logger.warning('自动播种: 播种准备状态异常 | status={}', prepare_status)
            return []

        if use_warehouse_first:
            cv_img = self.ui.device.screenshot()
            number_items = self._detect_seed_number_items(cv_img, seed_popup_land)
            if not number_items:
                self.ui.device.click_button(GOTO_MAIN)
                self.ui.device.sleep(0.2)
                logger.info('自动播种: 种子候选框无数字块，尝试购买种子并重试 | 作物={}', crop_name)
                buy_result = self._buy_seeds(crop_name)
                if not buy_result:
                    logger.warning('自动播种: 购买种子失败或未完成，结束本轮播种 | 作物={}', crop_name)
                    return []
                return self._plant_all(crop_name)

            excluded_indexes = self._collect_excluded_seed_item_indexes(number_items)
            ordered_indexes = sorted(
                range(len(number_items)),
                key=lambda idx: float(number_items[idx].box[0] + number_items[idx].box[2] / 2.0),
            )
            available_indexes = [idx for idx in ordered_indexes if idx not in excluded_indexes]
            if not available_indexes:
                self.ui.device.click_button(GOTO_MAIN)
                self.ui.device.sleep(0.2)
                logger.info('自动播种: 候选框种子均被排除，尝试购买种子并重试 | 作物={}', crop_name)
                buy_result = self._buy_seeds(crop_name)
                if not buy_result:
                    logger.warning('自动播种: 购买种子失败或未完成，结束本轮播种 | 作物={}', crop_name)
                    return []
                return self._plant_all(crop_name)

            selected_index = int(available_indexes[0])
            selected_item = number_items[selected_index]
            box_x, box_y, box_w, box_h = selected_item.box
            seed_drag_point = (int(box_x + box_w / 2), int(box_y + box_h / 2))
            logger.info(
                '自动播种: 仓库优先选中最左可用数字块 | 序号={} 拖拽点={} 排除索引={}',
                selected_index + 1,
                seed_drag_point,
                sorted(excluded_indexes),
            )
        else:
            seed_drag_point = self._select_seed_from_popup_by_warehouse_index(seed_index or 0, seed_popup_land)
            if seed_drag_point is None:
                logger.warning('自动播种: 候选框中无法按仓库序号选择种子 | 仓库序号={}', seed_index)
                return []

        self._drag_seed_to_lands(seed_drag_point, land_coords)
        self.backfill_land_flag_false(pending_plot_refs, 'need_planting', log_prefix='自动播种')
        return []
