"""TaskMain 播种与买种逻辑。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from loguru import logger

from core.base.timer import Timer
from core.exceptions import BuySeedError
from core.ui.assets import *
from core.ui.page import GOTO_MAIN, page_main, page_shop
from models.config import PlantMode
from models.game_data import get_best_crop_for_level, get_latest_crop_for_level
from tasks.main import (
    ALWAYS_SKIP_SEED_BUTTONS,
    BACKGROUND_TREE_BASELINE_POINT,
    BACKGROUND_TREE_OFFSET_THRESHOLD,
    BACKGROUND_TREE_STABLE_CHECK_INTERVAL_SECONDS,
    BACKGROUND_TREE_SWIPE_H_P1,
    BACKGROUND_TREE_SWIPE_H_P2,
    BACKGROUND_TREE_SWIPE_V_P1,
    BACKGROUND_TREE_SWIPE_V_P2,
    LAND_MATCH_Y_RANGE,
    OPTIONAL_SKIP_SEED_BUTTONS,
    SEED_POPUP_NUMBER_REGION_X_MAX,
    SEED_POPUP_NUMBER_REGION_X_MIN,
    SEED_POPUP_NUMBER_REGION_Y_OFFSET_BOTTOM,
    SEED_POPUP_NUMBER_REGION_Y_OFFSET_TOP,
    SHOP_LIST_SWIPE_END,
    SHOP_LIST_SWIPE_START,
)
from utils.bg_patch_number_ocr import BgPatchNumberItem

if TYPE_CHECKING:
    from core.engine.bot.local_engine import LocalBotEngine
    from core.ui.ui import UI


class TaskMainPlantingMixin:
    """提供播种主链路与买种流程。"""

    engine: 'LocalBotEngine'
    ui: 'UI'

    def _run_feature_plant(self) -> str | None:
        """自动播种"""
        logger.info('自动播种流程: 开始')
        self.ui.ui_ensure(page_main)
        # self._buy_seeds(self.engine._resolve_crop_name())

        # 点击空白处
        self.ui.device.click_button(GOTO_MAIN)
        while 1:
            self.ui.device.screenshot()
            anchor = self._get_labor_anchor_location()
            if anchor is None:
                logger.warning('自动播种流程: 未识别到背景树锚点')
                break

            offset_x = int(anchor[0] - BACKGROUND_TREE_BASELINE_POINT[0])
            offset_y = int(anchor[1] - BACKGROUND_TREE_BASELINE_POINT[1])
            if abs(offset_x) > BACKGROUND_TREE_OFFSET_THRESHOLD:
                if offset_x > 0:
                    p1, p2, direction = BACKGROUND_TREE_SWIPE_H_P1, BACKGROUND_TREE_SWIPE_H_P2, '左'
                else:
                    p1, p2, direction = BACKGROUND_TREE_SWIPE_H_P2, BACKGROUND_TREE_SWIPE_H_P1, '右'
                self.ui.device.swipe(p1, p2, speed=30, delay=0.5, hold=0.1)
                logger.info('自动播种流程: 背景树横向偏移={}px，画面{}移', offset_x, direction)
                continue

            if abs(offset_y) > BACKGROUND_TREE_OFFSET_THRESHOLD:
                if offset_y > 0:
                    p1, p2, direction = BACKGROUND_TREE_SWIPE_V_P1, BACKGROUND_TREE_SWIPE_V_P2, '上'
                else:
                    p1, p2, direction = BACKGROUND_TREE_SWIPE_V_P2, BACKGROUND_TREE_SWIPE_V_P1, '下'
                self.ui.device.swipe(p1, p2, speed=30, delay=0.5, hold=0.1)
                logger.info('自动播种流程: 背景树纵向偏移={}px，画面{}移', offset_y, direction)
                continue

            break

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
    def _get_seed_buttons_for_exclusion(*, skip_event_crops: bool) -> list[Button]:
        """返回当前应参与排除的作物模板列表。"""
        buttons: list[Button] = [btn for btn in ALWAYS_SKIP_SEED_BUTTONS if btn is not None]
        if skip_event_crops:
            buttons.extend(btn for btn in OPTIONAL_SKIP_SEED_BUTTONS if btn is not None)
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
            logger.warning('自动播种流程: 未找到 icon_land 模板')
            return []

        priority = {
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
            '自动播种流程: 地块匹配完成 | 模板={} raw_total={} raw_in_range={} dedup={} coords={} y_range={}',
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
        stable_seconds = max(0.1, float(self.engine.config.planting.planting_stable_seconds))
        stable_timer = Timer(stable_seconds, count=3)
        timeout_seconds = max(0.1, float(self.engine.config.planting.planting_stable_timeout_seconds))
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
                    '自动播种流程: 背景树锚点稳定等待超时 | timeout={}s',
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
            '自动播种流程: 种子数量 | click_y={} region={} count={} nums={}',
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
        skip_event_crops: bool,
        threshold: float = 0.80,
        near_distance: float = 50.0,
    ) -> set[int]:
        """识别活动作物模板并返回需排除的数字块索引集合。"""
        if not number_items:
            return set()

        seed_buttons = self._get_seed_buttons_for_exclusion(skip_event_crops=skip_event_crops)
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

    def _plant_all(self, crop_name: str) -> list[str]:
        """执行整块农田播种流程（识别空地、拉种子、补种购买）。"""
        # 模板匹配到的空地
        detected_land_coords = self._collect_land_coords_for_plant(threshold=0.85, y_range=LAND_MATCH_Y_RANGE)

        # 检查地块巡查任务是否开启，若关闭则不使用历史记录
        use_land_scan_results = False
        task_config = self.engine.config.tasks.get('land_scan')
        if task_config and bool(getattr(task_config, 'enabled', False)):
            use_land_scan_results = True

        detail_land_coords = []
        pending_plot_refs = []
        if use_land_scan_results:
            detail_targets = self.collect_land_targets_by_flag(
                'need_planting', anchor_threshold=0.95, log_prefix='自动播种流程: 空地补充'
            )
            detail_land_coords = [point for _, point in detail_targets]
            pending_plot_refs = [ref for ref, _ in detail_targets]
        else:
            logger.info('自动播种流程: 地块巡查任务未开启，跳过历史空地补充')

        land_coords = self._merge_land_coords(detected_land_coords, detail_land_coords)
        logger.info('自动播种流程: 空地识别完成 | count={}', len(land_coords))
        if not land_coords:
            logger.info('自动播种流程: 未发现空土地，跳过播种')
            return

        before_labor_anchor = self._get_labor_anchor_location()
        seed_popup_land = self._select_center_land_coord(land_coords) or land_coords[0]
        use_warehouse_first = bool(getattr(self.engine.config.planting, 'warehouse_first', True))
        skip_event_crops = bool(getattr(self.engine.config.planting, 'skip_event_crops', False))
        seed_panel_items: list[BgPatchNumberItem] = []
        excluded_seed_item_indexes: set[int] = set()
        open_seed_clicks = 0
        while 1:
            land_x, land_y = seed_popup_land
            self.engine.device.click_point(int(land_x), int(land_y), desc='点击可播种地块')
            open_seed_clicks += 1
            self.ui.device.sleep(0.5)

            cv_img = self.ui.device.screenshot()
            number_items = self._detect_seed_number_items(cv_img, (int(land_x), int(land_y)))
            # 检查种子数字块是否出现
            if number_items:
                seed_panel_items = number_items
                if use_warehouse_first:
                    excluded_seed_item_indexes = self._collect_excluded_seed_item_indexes(
                        number_items,
                        skip_event_crops=skip_event_crops,
                    )
                    available_count = int(len(number_items) - len(excluded_seed_item_indexes))
                    logger.info(
                        '自动播种流程: 作物排除结果 | templates={} total={} excluded={} available={} skip_event_crops={}',
                        [btn.name for btn in self._get_seed_buttons_for_exclusion(skip_event_crops=skip_event_crops)],
                        len(number_items),
                        len(excluded_seed_item_indexes),
                        available_count,
                        skip_event_crops,
                    )
                    if available_count <= 0:
                        logger.info('自动播种流程: 仓库数字块全部命中排除模板，购买种子')
                        buy_result = self._buy_seeds(crop_name)
                        if buy_result:
                            return self._plant_all(crop_name)
                        logger.warning('自动播种流程: 购买种子失败或未完成，结束本轮播种')
                        return
                break
            if open_seed_clicks >= 2:
                logger.info('自动播种流程: 未识别到种子，购买种子')
                buy_result = self._buy_seeds(crop_name)
                if buy_result:
                    return self._plant_all(crop_name)
                logger.warning('自动播种流程: 购买种子失败或未完成，结束本轮播种')
                return

        after_labor_anchor = self._wait_labor_anchor_stable()
        if before_labor_anchor is not None and after_labor_anchor is not None:
            dx = float(after_labor_anchor[0] - before_labor_anchor[0])
            dy = float(after_labor_anchor[1] - before_labor_anchor[1])
            drift = math.hypot(dx, dy)
            if drift > 3.0:
                logger.info('自动播种流程: 画面偏移 {:.1f}px，已修正播种坐标', drift)
            land_coords = self._shift_land_coords(land_coords, dx, dy)
        else:
            logger.warning('自动播种流程: 背景树锚点识别失败，继续使用原始地块坐标')

        # 选择种子
        seed_det = None
        seed_drag_point: tuple[int, int] | None = None
        if use_warehouse_first:
            number_items = seed_panel_items
            active_excluded_indexes: set[int] = excluded_seed_item_indexes
            if not number_items:
                cv_img = self.ui.device.screenshot()
                number_items = self._detect_seed_number_items(cv_img, seed_popup_land)
                active_excluded_indexes = self._collect_excluded_seed_item_indexes(
                    number_items,
                    skip_event_crops=skip_event_crops,
                )
            available_items = [item for idx, item in enumerate(number_items) if int(idx) not in active_excluded_indexes]
            if available_items:
                left_seed = min(available_items, key=lambda item: float(item.box[0] + item.box[2] / 2.0))
                left_center_x = int(left_seed.box[0] + left_seed.box[2] / 2.0)
                left_center_y = int(left_seed.box[1] + left_seed.box[3] / 2.0)
                seed_drag_point = (left_center_x, left_center_y)
                logger.info(
                    '自动播种流程: 仓库优先已启用，使用最左数字块 | box={} text={} score={:.3f} drag_point={}',
                    left_seed.box,
                    left_seed.text,
                    left_seed.score,
                    seed_drag_point,
                )
            else:
                logger.warning(
                    '自动播种流程: 仓库优先已启用，但未识别到可用数字块 | total={} excluded={} skip_event_crops={}',
                    len(number_items),
                    len(active_excluded_indexes),
                    skip_event_crops,
                )

        if seed_drag_point is None:
            while 1:
                cv_img = self.ui.device.screenshot()
                # 使用原始模板图匹配种子
                seed_dets = self.engine.cv_detector.detect_seed_template(
                    cv_img, threshold=0.8, crop_name_or_template=crop_name
                )
                if seed_dets:
                    seed_det = seed_dets[0]
                    break
                if self.ui.appear_then_click(
                    BTN_SEED_SELECT_POPUP_RIGHT, offset=30, threshold=0.85, interval=1, static=False
                ):
                    self.ui.device.sleep(0.2)
                    continue
                # 种子选择框右侧按钮消失
                if not self.ui.appear(BTN_SEED_SELECT_POPUP_RIGHT, offset=30, threshold=0.85, static=False):
                    # logger.error('未匹配到种子，请联系作者调整模板')
                    break

        # 没有找到种子
        if seed_drag_point is None and seed_det is None:
            buy_result = self._buy_seeds(crop_name)
            if buy_result:
                return self._plant_all(crop_name)

        dragging = False
        try:
            if seed_drag_point is not None:
                drag_x, drag_y = int(seed_drag_point[0]), int(seed_drag_point[1])
            else:
                drag_x, drag_y = int(seed_det.x), int(seed_det.y)
            self.engine.device.drag_down_point(drag_x, drag_y, duration=0.1)
            dragging = True
            self.ui.device.sleep(0.1)

            for land_x, land_y in land_coords:
                self.engine.device.drag_move_point(int(land_x), int(land_y), duration=0.1)
                self.ui.device.sleep(0.15)
        finally:
            if dragging:
                self.engine.device.drag_up()
                logger.info('自动播种流程: 播种完成')
                self.backfill_land_flag_false(pending_plot_refs, 'need_planting', log_prefix='自动播种流程')

        return

    def _close_shop_and_buy(self, crop_name: str, actions_done: list[str]):
        """关闭商店后立刻执行一次补种购买。"""
        buy_result = self._buy_seeds(crop_name)
        if buy_result:
            actions_done.append(buy_result)

    def _is_crop_aligned_with_strategy(self, crop_name: str) -> bool:
        """校验当前作物是否与自动策略一致。"""
        planting = self.engine.config.planting
        expected_crop_name = None
        if planting.strategy == PlantMode.LATEST_LEVEL:
            latest_crop = get_latest_crop_for_level(planting.player_level)
            expected_crop_name = latest_crop[0] if latest_crop else None
        elif planting.strategy == PlantMode.BEST_EXP_RATE:
            best_crop = get_best_crop_for_level(planting.player_level)
            expected_crop_name = best_crop[0] if best_crop else None

        if expected_crop_name and crop_name != expected_crop_name:
            return False
        return True

    def _scan_shop_page_for_seed(self, crop_name: str):
        """识别当前商店页，返回 OCR 匹配与白萝卜出现标记。"""
        cv_img = self.ui.device.screenshot()
        ocr_match = self.shop_ocr.find_item(cv_img, crop_name, min_similarity=0.80)
        has_white_radish = any(
            ('白萝卜' in str(item.name)) or ('白萝卜' in str(item.raw_name)) for item in ocr_match.parsed_items
        )
        return ocr_match, has_white_radish

    def _locate_seed_in_shop(self, crop_name: str, swipe_list: bool = False):
        """按页识别并定位待购买种子；命中白萝卜仍未找到目标时抛异常。"""
        self.ui.device.screenshot()
        ocr_match, has_white_radish = self._scan_shop_page_for_seed(crop_name)
        swipe_list = bool(swipe_list) or not bool(ocr_match.target)
        if not swipe_list:
            logger.info('购买流程: 已定位目标 | 种子={}', crop_name)
            return ocr_match.target
        if ocr_match.target:
            logger.info('购买流程: 已定位目标 | 种子={}', crop_name)
            return ocr_match.target

        logger.info('购买流程: 需滑动列表 | 种子={}', crop_name)
        while swipe_list:
            if has_white_radish:
                logger.error("购买流程: 已到达商店首页且未找到种子 '{}'", crop_name)
                raise BuySeedError

            self.ui.device.swipe(SHOP_LIST_SWIPE_START, SHOP_LIST_SWIPE_END, speed=30, delay=1, hold=0.1)
            ocr_match, has_white_radish = self._scan_shop_page_for_seed(crop_name)
            if ocr_match.target:
                logger.info('购买流程: 已定位目标 | 商品={}', crop_name)
                return ocr_match.target

    def _confirm_buy_seed(self, crop_name: str, target_item) -> None:
        """点击目标种子并确认购买。"""
        click_buy = False
        while 1:
            self.ui.device.screenshot()

            # 购买完成
            if click_buy and not self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30):
                logger.info('购买流程: 购买成功 | 商品={}', crop_name)
                break
            # 购买
            if self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_SHOP_BUY_CONFIRM, offset=30, interval=1
            ):
                click_buy = True
                continue
            # 点击物品
            if (
                self.ui.appear(SHOP_CHECK, offset=30)
                and not self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30)
                and not self.ui.appear(BTN_SHOP_BUY_CONFIRM, offset=30)
            ):
                self.ui.device.click_point(
                    int(target_item.center_x), int(target_item.center_y), desc=f'选择{crop_name}'
                )
                self.ui.device.sleep(0.5)
                continue

    def _buy_seeds(self, crop_name: str) -> str | bool:
        """执行买种流程：开商店 -> OCR 定位 -> 选择并确认购买。"""
        logger.info('购买流程: 开始 | 商品={}', crop_name)
        self.ui.ui_ensure(page_shop, confirm_wait=0.5)

        swipe_list = not self._is_crop_aligned_with_strategy(crop_name)
        target_item = self._locate_seed_in_shop(crop_name, swipe_list=swipe_list)
        self._confirm_buy_seed(crop_name, target_item)

        self.ui.ui_ensure(page_main)
        return f'购买{crop_name}'
