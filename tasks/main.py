"""nklite 农场主任务。"""

from __future__ import annotations

import math
import time

from loguru import logger

from core.base.timer import Timer
from core.engine.task.registry import TaskResult
from core.exceptions import BuySeedError
from core.ui.assets import *
from core.ui.page import GOTO_MAIN, page_main, page_shop
from models.config import PlantMode
from models.farm_state import ActionType
from models.game_data import get_best_crop_for_level, get_latest_crop_for_level
from tasks.base import TaskBase
from utils.level_ocr import LevelOCR
from utils.number_box_detector import NumberBoxDetector
from utils.shop_item_ocr import ShopItemOCR

SHOP_LIST_SWIPE_START = (270, 300)
SHOP_LIST_SWIPE_END = (270, 860)

LAND_LIST = [ICON_LAND_STAND, ICON_LAND_BLACK, ICON_LAND_RED, ICON_LAND_GOLD, ICON_LAND_GOLD_2]
LAND_MATCH_Y_RANGE = (350, 850)
FIRST_CLICK_LABOR_DELAY_DEFAULT_SECONDS = 0.5
FIRST_CLICK_LABOR_DELAY_SIDE_SECONDS = 1.0
FIRST_CLICK_SIDE_MARGIN_RATIO = 0.2
LEVEL_OCR_REGION_QQ = (130, 102, 160, 125)
LEVEL_OCR_REGION_WECHAT = (67, 102, 97, 125)


class TaskMain(TaskBase):
    """封装 `TaskMain` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)
        self._expand_failed = False
        self.shop_ocr = ShopItemOCR()
        self.number_box_detector = NumberBoxDetector(ui=self.ui)
        self.level_ocr = LevelOCR()

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行主流程：在 run 内按 feature 显式控制每个子方法。"""
        features = self.get_features('main')

        self.ui.ui_ensure(page_main)

        # 一键收获
        if self.has_feature(features, 'auto_harvest'):
            self._run_feature_harvest()

        # 一键除草
        if self.has_feature(features, 'auto_weed'):
            self._run_feature_weed()

        # 一键除虫
        if self.has_feature(features, 'auto_bug'):
            self._run_feature_bug()

        # 一键浇水
        if self.has_feature(features, 'auto_water'):
            self._run_feature_water()

        # 自动播种
        if self.has_feature(features, 'auto_plant'):
            self._sync_player_level_before_plant()
            self._run_feature_plant()

        # TODO 自动施肥
        if self.has_feature(features, 'auto_fertilize'):
            self._run_feature_fertilize()

        # TODO 自动扩建
        if self.has_feature(features, 'auto_upgrade'):
            self._run_feature_upgrade()

        return self.ok()

    def _get_level_ocr_region(self, frame_shape: tuple[int, ...]) -> tuple[int, int, int, int] | None:
        """按平台读取等级 OCR 常量区域并裁剪到截图范围内。"""
        planting = self.engine.config.planting
        platform = getattr(planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        if platform_value == 'wechat':
            raw_region = LEVEL_OCR_REGION_WECHAT
        else:
            raw_region = LEVEL_OCR_REGION_QQ

        try:
            x1, y1, x2, y2 = [int(v) for v in raw_region]
        except Exception:
            return None
        if x2 <= x1 or y2 <= y1:
            return None

        frame_h = int(frame_shape[0]) if len(frame_shape) >= 1 else 0
        frame_w = int(frame_shape[1]) if len(frame_shape) >= 2 else 0
        if frame_w <= 1 or frame_h <= 1:
            return None

        x1 = max(0, min(x1, frame_w - 1))
        y1 = max(0, min(y1, frame_h - 1))
        x2 = max(x1 + 1, min(x2, frame_w))
        y2 = max(y1 + 1, min(y2, frame_h))
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2

    def _sync_player_level_before_plant(self) -> int | None:
        """播种前识别主界面等级并回写配置。"""
        planting = self.engine.config.planting
        if not bool(getattr(planting, 'level_ocr_enabled', True)):
            return None

        cv_img = self.ui.device.screenshot()
        if cv_img is None:
            return None

        roi = self._get_level_ocr_region(cv_img.shape)
        if roi is None:
            logger.warning('等级识别: ROI 无效，跳过本轮识别')
            return None

        level, score, raw_text = self.level_ocr.detect_level(
            cv_img,
            region=roi,
        )
        if level is None:
            logger.debug('等级识别: 未匹配等级 | roi={} raw={}', roi, raw_text)
            return None

        old_level = int(getattr(planting, 'player_level', 1))
        if level == old_level:
            logger.debug('等级识别: 等级未变化 | Lv{} score={:.3f}', level, score)
            return level

        planting.player_level = int(level)
        try:
            self.engine.config.save()
        except Exception as exc:
            logger.warning('等级识别: 等级已更新但保存配置失败 | Lv{} -> Lv{} | error={}', old_level, level, exc)
        else:
            config_path = str(getattr(self.engine.config, '_config_path', '') or '')
            logger.info(
                '等级识别: 等级已更新 | Lv{} -> Lv{} | roi={} score={:.3f} raw={} config={}',
                old_level,
                level,
                roi,
                score,
                raw_text,
                config_path or 'default-config-path',
            )
            self._emit_config_updated()
        return level

    def _emit_config_updated(self) -> None:
        """向主进程广播配置已更新，触发设置面板刷新。"""
        payload = dict(self.engine.config.model_dump())
        direct_sender = getattr(self.engine, 'emit_config_event', None)
        if callable(direct_sender):
            try:
                direct_sender(payload)
                return
            except Exception as exc:
                logger.debug('等级识别: 直连广播配置更新失败: {}', exc)

        signal = getattr(self.engine, 'config_updated', None)
        if signal is None or not hasattr(signal, 'emit'):
            return
        try:
            signal.emit(payload)
        except Exception as exc:
            logger.debug('等级识别: 广播配置更新失败: {}', exc)

    def _run_feature_harvest(self) -> str | None:
        """一键收获"""
        self.ui.device.screenshot()
        if not self.ui.appear(BTN_HARVEST, offset=30, static=False) and not self.ui.appear(
            BTN_MATURE, offset=30, static=False
        ):
            return None

        confirm_timer = Timer(1, count=3)
        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(BTN_HARVEST, offset=30, interval=1, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                continue
            if self.ui.appear_then_click(BTN_MATURE, offset=30, interval=1, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                continue
            if not self.ui.appear(BTN_HARVEST, offset=30, static=False) and not self.ui.appear(
                BTN_MATURE, offset=30, static=False
            ):
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    result = '一键收获'
                    break
            else:
                confirm_timer.clear()

        return result

    def _run_feature_weed(self) -> str | None:
        """一键除草"""
        return self._run_feature_single_action(BTN_WEED, ActionType.WEED, '一键除草')

    def _run_feature_bug(self) -> str | None:
        """一键除虫"""
        return self._run_feature_single_action(BTN_BUG, ActionType.BUG, '一键除虫')

    def _run_feature_water(self) -> str | None:
        """一键浇水"""
        return self._run_feature_single_action(BTN_WATER, ActionType.WATER, '一键浇水')

    # TODO 优化操作速度
    def _run_feature_single_action(self, button, stat_action: str, done_text: str) -> str | None:
        """通用单按钮循环动作：首检未命中直接返回，命中后点击到消失。"""
        logger.info('一键{}流程: 开始', done_text)
        self.ui.device.screenshot()
        if not self.ui.appear(button, offset=30, static=False):
            return None

        confirm_timer = Timer(1, count=3)
        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(button, offset=30, interval=1, static=False):
                self.engine._record_stat(stat_action)
                continue
            if not self.ui.appear(button, offset=30, static=False):
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    result = done_text
                    break
            else:
                confirm_timer.clear()

        return result

    # TODO
    def _run_feature_fertilize(self) -> str | None:
        """自动施肥"""
        return None

    def _run_feature_plant(self) -> str | None:
        """自动播种"""
        logger.info('自动播种流程: 开始')
        self.ui.ui_ensure(page_main)
        # self._buy_seeds(self.engine._resolve_crop_name())

        # 点击空白处
        self.ui.device.click_button(GOTO_MAIN)
        while 1:
            self.ui.device.screenshot()
            if self.ui.appear(BTN_LAND_RIGHT, offset=30, threshold=0.9, static=False) and self.ui.appear(
                BTN_LAND_LEFT, offset=30, threshold=0.9, static=False
            ):
                break
            # 检查土地位置
            if not self.ui.appear(BTN_LAND_RIGHT, offset=30, threshold=0.9, static=False):
                self.ui.device.swipe((270, 220), (240, 220), speed=30, delay=1, hold=0.1)
                logger.error('土地存在遮挡，画面左移')
                continue
            if not self.ui.appear(BTN_LAND_LEFT, offset=30, threshold=0.9, static=False):
                self.ui.device.swipe((240, 220), (270, 220), speed=30, delay=1, hold=0.1)
                logger.error('土地存在遮挡，画面右移')
                continue

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
    def _get_seed_btn_buttons() -> list[Button]:
        """返回 assets 中所有 `seed_btn_` 按钮定义。"""
        buttons = [btn for name, btn in ASSET_NAME_TO_CONST.items() if str(name).startswith('seed_btn_')]
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
    def _select_center_land_coord(coords: list[tuple[int, int]]) -> tuple[int, int] | None:
        """优先选最上方地块，再选 x 最靠近中心的地块。"""
        if not coords:
            return None
        avg_x = sum(x for x, _ in coords) / float(len(coords))
        min_y = min(y for _, y in coords)
        top_row = [point for point in coords if point[1] == min_y]
        return min(top_row, key=lambda p: abs(p[0] - avg_x))

    @staticmethod
    def _get_first_click_labor_delay_seconds(land_x: int, frame_width: int) -> float:
        """按首次点击坐标估算识别劳动最光荣前的等待时间。"""
        if frame_width <= 0:
            return FIRST_CLICK_LABOR_DELAY_DEFAULT_SECONDS
        side_margin = int(frame_width * FIRST_CLICK_SIDE_MARGIN_RATIO)
        if land_x <= side_margin or land_x >= (frame_width - side_margin):
            return FIRST_CLICK_LABOR_DELAY_SIDE_SECONDS
        return FIRST_CLICK_LABOR_DELAY_DEFAULT_SECONDS

    def _get_labor_anchor_location(self) -> tuple[int, int] | None:
        """识别劳动最光荣锚点位置，用于估计画面平移。"""
        self.ui.device.screenshot()
        return self.ui.appear_location(BTN_LABOR_IS_GLORIOUS, offset=30, threshold=0.7, static=False)

    @staticmethod
    def _shift_land_coords(coords: list[tuple[int, int]], dx: float, dy: float) -> list[tuple[int, int]]:
        """按平移量修正地块坐标。"""
        return [(int(round(x + dx)), int(round(y + dy))) for x, y in coords]

    def _collect_excluded_seed_box_orders(
        self,
        number_boxes: list,
        *,
        threshold: float = 0.80,
        near_distance: float = 50.0,
    ) -> set[int]:
        """识别 seed_btn 模板并返回需排除的数字框序号集合。"""
        if not number_boxes:
            return set()

        seed_buttons = self._get_seed_btn_buttons()
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

        excluded_orders: set[int] = set()
        for box in number_boxes:
            box_cx, box_cy = box.center
            dynamic_near = max(float(near_distance), float(max(box.size)) * 0.75)
            for sx, sy in seed_points:
                if math.hypot(float(box_cx - sx), float(box_cy - sy)) <= dynamic_near:
                    excluded_orders.add(int(box.order))
                    break
        return excluded_orders

    def _plant_all(self, crop_name: str) -> list[str]:
        """执行整块农田播种流程（识别空地、拉种子、补种购买）。"""
        # get_lands_from_land_anchor()
        land_coords = self._collect_land_coords_for_plant(threshold=0.85, y_range=LAND_MATCH_Y_RANGE)
        logger.info('自动播种流程: 空地识别完成 | count={}', len(land_coords))
        if not land_coords:
            logger.info('自动播种流程: 未发现空土地，跳过播种')
            return

        before_labor_anchor = self._get_labor_anchor_location()
        seed_popup_land = self._select_center_land_coord(land_coords) or land_coords[0]
        use_warehouse_first = bool(getattr(self.engine.config.planting, 'warehouse_first', True))
        seed_panel_boxes = []
        excluded_seed_box_orders: set[int] = set()
        open_seed_clicks = 0
        first_land_click_at: float | None = None
        first_click_labor_delay_seconds = 0.0
        while 1:
            land_x, land_y = seed_popup_land
            self.engine.device.click_point(int(land_x), int(land_y), desc='点击可播种地块')
            if open_seed_clicks == 0:
                first_land_click_at = time.monotonic()
            open_seed_clicks += 1
            self.ui.device.sleep(0.5)

            cv_img = self.ui.device.screenshot()
            if open_seed_clicks == 1:
                frame_width = int(cv_img.shape[1]) if cv_img is not None and len(cv_img.shape) >= 2 else 0
                first_click_labor_delay_seconds = self._get_first_click_labor_delay_seconds(int(land_x), frame_width)
            popup_visible = self.ui.appear(BTN_SEED_SELECT_POPUP_RIGHT, offset=30, threshold=0.85, static=False)
            number_boxes = self.number_box_detector.detect_boxes(cv_img)
            # 检查种子选择框/数字框出现
            if popup_visible or number_boxes:
                seed_panel_boxes = number_boxes
                if use_warehouse_first and number_boxes:
                    excluded_seed_box_orders = self._collect_excluded_seed_box_orders(number_boxes)
                    if len(excluded_seed_box_orders) >= len(number_boxes):
                        logger.info('自动播种流程: 未识别到种子，购买种子')
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

        if first_land_click_at is not None and first_click_labor_delay_seconds > 0:
            elapsed = time.monotonic() - first_land_click_at
            remain = first_click_labor_delay_seconds - elapsed
            if remain > 0:
                self.ui.device.sleep(remain)

        after_labor_anchor = self._get_labor_anchor_location()
        if before_labor_anchor is not None and after_labor_anchor is not None:
            dx = float(after_labor_anchor[0] - before_labor_anchor[0])
            dy = float(after_labor_anchor[1] - before_labor_anchor[1])
            drift = math.hypot(dx, dy)
            if drift > 3.0:
                logger.info('自动播种流程: 画面偏移 {:.1f}px，已修正播种坐标', drift)
            land_coords = self._shift_land_coords(land_coords, dx, dy)
        else:
            logger.warning('自动播种流程: 劳动最光荣锚点识别失败，继续使用原始地块坐标')

        # 选择种子
        seed_det = None
        seed_drag_point: tuple[int, int] | None = None
        if use_warehouse_first:
            number_boxes = seed_panel_boxes
            active_excluded_orders = excluded_seed_box_orders
            if not number_boxes:
                cv_img = self.ui.device.screenshot()
                number_boxes = self.number_box_detector.detect_boxes(cv_img)
                active_excluded_orders = self._collect_excluded_seed_box_orders(number_boxes)
            available_boxes = [box for box in number_boxes if int(box.order) not in active_excluded_orders]
            if available_boxes:
                left_seed = min(available_boxes, key=lambda box: box.center[0])
                seed_drag_point = (int(left_seed.center[0]), int(left_seed.center[1]))
                logger.info(
                    '自动播种流程: 仓库优先已启用，使用最左种子 | box={} drag_point={}',
                    left_seed.bbox,
                    seed_drag_point,
                )
            else:
                logger.warning('自动播种流程: 仓库优先已启用，但未识别种子')

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
                continue
            # 点击物品
            if self.ui.appear(SHOP_CHECK, offset=30) and not self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30):
                self.ui.device.click_point(
                    int(target_item.center_x), int(target_item.center_y), desc=f'选择{crop_name}'
                )
                self.ui.device.sleep(0.5)
                click_buy = True
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

    # TODO
    def _run_feature_upgrade(self) -> str | None:
        """自动扩建"""
        return self._try_expand()

    def _try_expand(self) -> str | None:
        """尝试执行一次扩建流程；失败后短路避免重复触发。"""
        if self._expand_failed:
            return None

        # 第一步：点击扩建入口。
        if not self.ui.appear_then_click(BTN_EXPAND, offset=30, interval=1, threshold=0.8, static=False):
            return None

        # 第二步：确认扩建（普通确认/直接确认）并处理残留弹窗。
        for _ in range(5):
            if self.ui.device.screenshot() is None:
                return None

            action_name = None
            if self.ui.appear_then_click(BTN_EXPAND_DIRECT_CONFIRM, offset=30, interval=1, threshold=0.8, static=False):
                action_name = '直接扩建'
            elif self.ui.appear_then_click(BTN_EXPAND_CONFIRM, offset=30, interval=1, threshold=0.8, static=False):
                action_name = '扩建确认'

            if action_name:
                self._expand_failed = False
                if self.ui.device.screenshot() is not None:
                    self.ui.appear_then_click_any(
                        [BTN_CLOSE, BTN_CONFIRM, BTN_CLAIM], offset=30, interval=1, threshold=0.8, static=False
                    )
                return action_name

            if self.ui.appear_then_click_any(
                [BTN_CLOSE, BTN_CONFIRM, BTN_CLAIM], offset=30, interval=1, threshold=0.8, static=False
            ):
                continue

        # 多轮都未完成时进入短路，避免每轮重复尝试导致噪音点击。
        self._expand_failed = True
        return None
