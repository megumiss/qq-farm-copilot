"""TaskMain 买种流程。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np
from loguru import logger

from core.exceptions import BuySeedError
from core.ui.assets import *
from core.ui.page import page_main, page_shop, page_warehouse_seed
from core.vision.cv_detector import SeedWarehouseSlot
from models.config import PlantMode
from models.game_data import get_best_crop_for_level, get_crop_by_name, get_crop_seed_price, get_latest_crop_for_level
from utils.app_paths import load_config_json_array
from utils.warehouse_seed_vision import (
    WAREHOUSE_SEED_GRID_ROI,
    detect_warehouse_seed_slot_boxes,
    group_warehouse_seed_rows,
    warehouse_seed_row_image_similarity,
)
from utils.warehouse_seed_vision import (
    clip_bbox as clip_warehouse_seed_bbox,
)

if TYPE_CHECKING:
    from core.engine.bot.local_engine import LocalBotEngine
    from core.ui.ui import UI
    from models.config import AppConfig


# 商店列表上滑的起点坐标（用于翻页查找种子）。
SHOP_LIST_SWIPE_START = (270, 300)
# 商店列表上滑的终点坐标（与起点配合形成上滑手势）。
SHOP_LIST_SWIPE_END = (270, 860)
# 仓库种子详情弹窗标题 OCR 区域，用于点击候选种子格后的作物名二次确认。
WAREHOUSE_SEED_DETAIL_NAME_ROI = (120, 655, 520, 800)
# seed 模板在仓库格内显示时的缩放比例，用于匹配游戏内缩小后的种子图标。
WAREHOUSE_SEED_MATCH_SCALE = 0.6
# 仓库 seed 模板匹配最低置信度，低于该值的候选不返回给播种流程。
WAREHOUSE_SEED_MATCH_THRESHOLD = 0.74
# 仓库种子页向下滚动手势起点，用于继续查看后续种子格。
WAREHOUSE_SEED_SCROLL_START = (320, 510)
# 仓库种子页向下滚动手势终点；反向使用时用于回滚到顶部。
WAREHOUSE_SEED_SCROLL_END = (320, 190)
# 仓库种子页最多滚动次数，避免结束标志或页面不变判定失效时无限循环。
WAREHOUSE_SEED_MAX_SCROLLS = 5
# 仓库种子区域滚动前后平均灰度差异阈值；低于该值视为页面不再变化。
WAREHOUSE_SEED_PAGE_UNCHANGED_DIFF_THRESHOLD = 1.5
# 多页仓库种子截图拼接时，判定相邻页面重复行的相似度阈值。
WAREHOUSE_SEED_STITCH_OVERLAP_SIMILARITY = 0.94


@dataclass(slots=True)
class WarehouseSeedCandidate:
    """播种流程内的仓库种子候选，包含滚动来源页信息。"""

    index: int
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    template_name: str
    confidence: float
    page_index: int = 0
    local_index: int = 0
    page_center: tuple[int, int] | None = None
    stitch_bbox: tuple[int, int, int, int] | None = None


class TaskMainBuySeedMixin:
    """提供商店买种与仓库种子定位流程。"""

    config: 'AppConfig'
    engine: 'LocalBotEngine'
    ui: 'UI'

    def _ocr_warehouse_seed_detail_name(self) -> tuple[str, float]:
        """OCR 识别仓库种子详情标题。"""
        cv_img = self.ui.device.screenshot()
        text, score = self.seed_number_ocr.ocr.detect_text(
            cv_img,
            region=WAREHOUSE_SEED_DETAIL_NAME_ROI,
            scale=1.8,
            alpha=1.15,
            beta=0.0,
        )
        return str(text or '').strip(), float(score or 0.0)

    @staticmethod
    def _normalize_warehouse_seed_detail_text(value: str) -> str:
        """归一化仓库详情 OCR 文本。"""
        text = str(value or '').strip()
        text = re.sub(r'[\s·，,。.:：;；!！?？_\-]+', '', text)
        return text.lower()

    def _is_warehouse_seed_detail_match(self, crop_name: str, text: str) -> bool:
        """判断仓库种子详情是否匹配目标作物。"""
        expected = self._normalize_warehouse_seed_detail_text(crop_name)
        actual = self._normalize_warehouse_seed_detail_text(text)
        if not expected or not actual:
            return False
        return expected in actual or f'{expected}种子' in actual

    @staticmethod
    def _to_warehouse_seed_candidate(slot: SeedWarehouseSlot) -> WarehouseSeedCandidate:
        """将视觉层种子格识别结果转换为播种流程候选。"""
        return WarehouseSeedCandidate(
            index=int(slot.index),
            bbox=slot.bbox,
            center=slot.center,
            template_name=str(slot.template_name),
            confidence=float(slot.confidence),
            page_center=slot.center,
        )

    def _confirm_warehouse_seed_slot(self, crop_name: str, candidate: WarehouseSeedCandidate) -> bool:
        """点击仓库候选种子格并通过详情标题 OCR 二次确认。"""
        cx, cy = candidate.page_center or candidate.center
        self.engine.device.click_point(int(cx), int(cy), desc=f'确认仓库种子格{candidate.index}')
        self.ui.device.sleep(0.35)
        text, score = self._ocr_warehouse_seed_detail_name()
        matched = self._is_warehouse_seed_detail_match(crop_name, text)
        logger.info(
            (
                '自动播种: 仓库种子确认 | 作物={} 序号={} 页码={} 页内序号={} '
                '模板={} 置信度={:.4f} 识别文本={} 识别分数={:.3f} 匹配={}'
            ),
            crop_name,
            candidate.index,
            int(candidate.page_index) + 1,
            candidate.local_index or candidate.index,
            candidate.template_name,
            candidate.confidence,
            text,
            score,
            matched,
        )
        return bool(matched)

    @staticmethod
    def _resolve_seed_id_by_crop_name(crop_name: str) -> int | None:
        """从作物名解析 seed_id，覆盖策略作物和额外作物。"""
        crop = get_crop_by_name(crop_name)
        if crop is not None:
            return int(crop[1])
        target = str(crop_name or '').strip()
        if not target:
            return None
        for item in load_config_json_array('plants.json', prefer_user=False):
            if str(item.get('name') or '').strip() != target:
                continue
            try:
                seed_id = int(item.get('seed_id') or 0)
            except (TypeError, ValueError):
                return None
            return seed_id if seed_id > 0 else None
        return None

    def _is_warehouse_seed_less_than_20_page(self) -> bool:
        """判断当前仓库种子页是否出现“种子数量不足 20”的结束标志。"""
        matched = self.ui.appear(BTN_WAREHOUSE_SEED_20_EMPTY, offset=30, threshold=0.82, static=False)
        if matched:
            logger.info('自动播种: 仓库种子不足 20 标志出现 | 按钮={}', BTN_WAREHOUSE_SEED_20_EMPTY.name)
        return bool(matched)

    def _warehouse_seed_roi_changed(self, before, after) -> bool:
        """判断仓库种子区域滚动后是否发生变化。"""
        if before is None or after is None:
            return False
        if before.size == 0 or after.size == 0:
            return False
        roi = WAREHOUSE_SEED_GRID_ROI
        bx1, by1, bx2, by2 = roi
        ah, aw = before.shape[:2]
        bh, bw = after.shape[:2]
        x1 = max(0, min(int(bx1), aw - 1, bw - 1))
        y1 = max(0, min(int(by1), ah - 1, bh - 1))
        x2 = min(int(bx2), aw, bw)
        y2 = min(int(by2), ah, bh)
        if x2 <= x1 or y2 <= y1:
            return False
        before_roi = before[y1:y2, x1:x2]
        after_roi = after[y1:y2, x1:x2]
        before_gray = cv2.cvtColor(before_roi, cv2.COLOR_BGR2GRAY)
        after_gray = cv2.cvtColor(after_roi, cv2.COLOR_BGR2GRAY)
        diff = float(np.mean(cv2.absdiff(before_gray, after_gray)))
        logger.debug('自动播种: 仓库种子页滚动差异 | 差异={:.3f}', diff)
        return diff >= WAREHOUSE_SEED_PAGE_UNCHANGED_DIFF_THRESHOLD

    def _build_warehouse_seed_stitched_slots(
        self, screenshots: list[np.ndarray]
    ) -> tuple[np.ndarray | None, list[dict]]:
        """按截图顺序拼接仓库种子行，返回拼接图和每个种子格的来源信息。"""
        appended_rows: list[dict] = []
        rx1, ry1, rx2, ry2 = WAREHOUSE_SEED_GRID_ROI

        for page_index, screenshot in enumerate(screenshots):
            if screenshot is None or screenshot.size == 0:
                continue
            sh, sw = screenshot.shape[:2]
            cx1, cy1, cx2, cy2 = clip_warehouse_seed_bbox((rx1, ry1, rx2, ry2), width=sw, height=sh)
            boxes = detect_warehouse_seed_slot_boxes(screenshot)
            rows = group_warehouse_seed_rows(boxes)
            page_rows: list[dict] = []
            for row_index, row_boxes in enumerate(rows):
                row_y1 = max(cy1, min(box[1] for box in row_boxes))
                row_y2 = min(cy2, max(box[3] for box in row_boxes))
                if row_y2 <= row_y1:
                    continue
                row_image = screenshot[row_y1:row_y2, cx1:cx2].copy()
                page_rows.append(
                    {
                        'page_index': int(page_index),
                        'row_index': int(row_index),
                        'image': row_image,
                        'y1': int(row_y1),
                        'x1': int(cx1),
                        'boxes': row_boxes,
                    }
                )

            if not page_rows:
                continue

            start_row = 0
            if appended_rows:
                prev_image = appended_rows[-1]['image']
                best_index = -1
                best_similarity = 0.0
                for idx, row in enumerate(page_rows):
                    similarity = warehouse_seed_row_image_similarity(prev_image, row['image'])
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_index = idx
                if best_index >= 0 and best_similarity >= WAREHOUSE_SEED_STITCH_OVERLAP_SIMILARITY:
                    start_row = best_index + 1
                    logger.debug(
                        '仓库种子拼接: 去除重叠行 | 页码={} 重叠行={} 相似度={:.4f}',
                        page_index,
                        best_index + 1,
                        best_similarity,
                    )

            appended_rows.extend(page_rows[start_row:])

        if not appended_rows:
            return None, []

        width = max(int(row['image'].shape[1]) for row in appended_rows)
        normalized_images: list[np.ndarray] = []
        slot_metas: list[dict] = []
        stitched_y = 0
        global_row_index = 0
        for row in appended_rows:
            image = row['image']
            if int(image.shape[1]) < width:
                pad_w = width - int(image.shape[1])
                image = cv2.copyMakeBorder(image, 0, 0, 0, pad_w, cv2.BORDER_REPLICATE)
            normalized_images.append(image)

            row_h = int(image.shape[0])
            row_y1 = int(row['y1'])
            row_x1 = int(row['x1'])
            for col_index, (x1, y1, x2, y2) in enumerate(row['boxes'][:5]):
                slot_y1 = stitched_y + max(0, int(y1) - row_y1)
                slot_y2 = stitched_y + min(row_h, int(y2) - row_y1)
                slot_x1 = max(0, int(x1) - row_x1)
                slot_x2 = min(width, int(x2) - row_x1)
                if slot_x2 <= slot_x1 or slot_y2 <= slot_y1:
                    continue
                page_center = ((int(x1) + int(x2)) // 2, (int(y1) + int(y2)) // 2)
                slot_metas.append(
                    {
                        'global_index': global_row_index * 5 + int(col_index) + 1,
                        'page_index': int(row['page_index']),
                        'local_index': int(row['row_index']) * 5 + int(col_index) + 1,
                        'page_bbox': (int(x1), int(y1), int(x2), int(y2)),
                        'page_center': page_center,
                        'stitch_bbox': (int(slot_x1), int(slot_y1), int(slot_x2), int(slot_y2)),
                    }
                )
            stitched_y += row_h
            global_row_index += 1

        if not normalized_images or not slot_metas:
            return None, []
        return cv2.vconcat(normalized_images), slot_metas

    def _detect_seed_template_in_stitched_warehouse_pages(
        self,
        screenshots: list[np.ndarray],
        seed_id: int,
        *,
        threshold: float = WAREHOUSE_SEED_MATCH_THRESHOLD,
        scale: float = WAREHOUSE_SEED_MATCH_SCALE,
    ) -> list[WarehouseSeedCandidate]:
        """在多页仓库截图拼接图中查找目标种子，并映射回来源页坐标。"""
        stitched, slot_metas = self._build_warehouse_seed_stitched_slots(screenshots)
        if stitched is None or not slot_metas:
            return []

        stitch_boxes = [meta['stitch_bbox'] for meta in slot_metas]
        raw_candidates = self.engine.cv_detector.detect_seed_template_in_warehouse(
            stitched,
            seed_id,
            boxes=stitch_boxes,
            threshold=float(threshold),
            scale=float(scale),
        )
        results: list[WarehouseSeedCandidate] = []
        for candidate in raw_candidates:
            meta_index = int(candidate.index) - 1
            if meta_index < 0 or meta_index >= len(slot_metas):
                continue
            meta = slot_metas[meta_index]
            results.append(
                WarehouseSeedCandidate(
                    index=int(meta['global_index']),
                    bbox=meta['page_bbox'],
                    center=meta['page_center'],
                    template_name=candidate.template_name,
                    confidence=float(candidate.confidence),
                    page_index=int(meta['page_index']),
                    local_index=int(meta['local_index']),
                    page_center=meta['page_center'],
                    stitch_bbox=meta['stitch_bbox'],
                )
            )

        results.sort(key=lambda item: item.confidence, reverse=True)
        logger.info(
            '仓库种子拼接匹配完成 | 页数={} 格数={} 候选={}',
            len(screenshots),
            len(slot_metas),
            [(item.index, item.page_index, item.local_index, round(float(item.confidence), 4)) for item in results],
        )
        return results

    def _swipe_warehouse_seed_page_down(self) -> bool:
        """仓库种子列表向下翻一段固定距离。"""
        return bool(
            self.ui.device.swipe(WAREHOUSE_SEED_SCROLL_START, WAREHOUSE_SEED_SCROLL_END, speed=30, delay=1, hold=0.1)
        )

    def _swipe_warehouse_seed_page_up(self) -> bool:
        """仓库种子列表向上回滚一段固定距离。"""
        return bool(
            self.ui.device.swipe(WAREHOUSE_SEED_SCROLL_END, WAREHOUSE_SEED_SCROLL_START, speed=30, delay=1, hold=0.1)
        )

    def _collect_warehouse_seed_page_screenshots(self, first_screenshot) -> list[np.ndarray]:
        """从当前仓库种子页开始滚动采集所有种子区域页面截图。"""
        screenshots = []
        current = first_screenshot
        if current is None:
            current = self.ui.device.screenshot()
        if current is None:
            return screenshots

        for page_index in range(WAREHOUSE_SEED_MAX_SCROLLS + 1):
            screenshots.append(current)
            if self._is_warehouse_seed_less_than_20_page():
                logger.info('自动播种: 仓库种子滚动采集结束 | 原因=不足20格 页数={}', len(screenshots))
                break

            if page_index >= WAREHOUSE_SEED_MAX_SCROLLS:
                logger.warning('自动播种: 仓库种子滚动达到上限 | 页数={}', len(screenshots))
                break

            if not self._swipe_warehouse_seed_page_down():
                logger.warning('自动播种: 仓库种子页滚动失败 | 页码={}', page_index + 1)
                break

            next_screenshot = self.ui.device.screenshot()
            if next_screenshot is None:
                break
            if not self._warehouse_seed_roi_changed(current, next_screenshot):
                logger.info('自动播种: 仓库种子滚动采集结束 | 原因=页面未变化 页数={}', len(screenshots))
                break
            current = next_screenshot

        logger.info('自动播种: 仓库种子页面采集完成 | 页数={}', len(screenshots))
        return screenshots

    def _reset_warehouse_seed_scroll_to_top(self, *, max_swipes: int = WAREHOUSE_SEED_MAX_SCROLLS + 2) -> None:
        """将仓库种子页回滚到最上方。"""
        current = self.ui.device.screenshot()
        for _ in range(max(1, int(max_swipes))):
            if not self._swipe_warehouse_seed_page_up():
                break
            next_screenshot = self.ui.device.screenshot()
            if next_screenshot is None:
                break
            if not self._warehouse_seed_roi_changed(current, next_screenshot):
                break
            current = next_screenshot

    def _scroll_warehouse_seed_to_page(self, page_index: int) -> None:
        """从仓库种子页顶部滚动到指定采集页。"""
        for _ in range(max(0, int(page_index))):
            if not self._swipe_warehouse_seed_page_down():
                break

    def _confirm_scrolled_warehouse_seed_slot(self, crop_name: str, candidate: WarehouseSeedCandidate) -> bool:
        """回到仓库种子页顶部后滚动到候选来源页，再执行 OCR 确认。"""
        page_index = max(0, int(candidate.page_index))
        self._reset_warehouse_seed_scroll_to_top()
        self._scroll_warehouse_seed_to_page(page_index)
        self.ui.device.screenshot()
        return self._confirm_warehouse_seed_slot(crop_name, candidate)

    def _locate_seed_index_in_warehouse(self, crop_name: str) -> int | None:
        """进入仓库种子页，定位目标种子的仓库序号。"""
        seed_id = self._resolve_seed_id_by_crop_name(crop_name)
        if seed_id is None:
            logger.warning('自动播种: 无法解析作物种子编号 | 作物={}', crop_name)
            return None

        self.ui.ui_ensure(page_warehouse_seed, confirm_wait=0.5)
        cv_img = self.ui.device.screenshot()
        candidates = self.engine.cv_detector.detect_seed_template_in_warehouse(
            cv_img,
            seed_id,
            threshold=WAREHOUSE_SEED_MATCH_THRESHOLD,
            scale=WAREHOUSE_SEED_MATCH_SCALE,
        )
        logger.info(
            '自动播种: 仓库种子匹配 | 作物={} 种子编号={} 候选={}',
            crop_name,
            seed_id,
            [(item.index, round(float(item.confidence), 4)) for item in candidates],
        )
        for candidate in candidates:
            flow_candidate = self._to_warehouse_seed_candidate(candidate)
            if self._confirm_warehouse_seed_slot(crop_name, flow_candidate):
                return int(flow_candidate.index)

        if self._is_warehouse_seed_less_than_20_page():
            logger.info('自动播种: 仓库种子少于 20 且未找到目标 | 作物={}', crop_name)
            return None

        screenshots = self._collect_warehouse_seed_page_screenshots(cv_img)
        if len(screenshots) <= 1:
            return None

        candidates = self._detect_seed_template_in_stitched_warehouse_pages(
            screenshots,
            seed_id,
            threshold=WAREHOUSE_SEED_MATCH_THRESHOLD,
            scale=WAREHOUSE_SEED_MATCH_SCALE,
        )
        logger.info(
            '自动播种: 仓库种子拼接匹配 | 作物={} 种子编号={} 候选={}',
            crop_name,
            seed_id,
            [
                (item.index, int(item.page_index) + 1, item.local_index, round(float(item.confidence), 4))
                for item in candidates
            ],
        )
        for candidate in candidates:
            if self._confirm_scrolled_warehouse_seed_slot(crop_name, candidate):
                return int(candidate.index)
        return None

    def _ensure_seed_index_in_warehouse(self, crop_name: str) -> int | None:
        """确保仓库中有目标种子，并返回其仓库序号。"""
        seed_index = self._locate_seed_index_in_warehouse(crop_name)
        if seed_index is not None:
            return seed_index

        logger.info('自动播种: 仓库未确认目标种子，开始购买 | 作物={}', crop_name)
        buy_result = self._buy_seeds(crop_name)
        if not buy_result:
            logger.warning('自动播种: 购买种子失败或未完成 | 作物={}', crop_name)
            return None

        seed_index = self._locate_seed_index_in_warehouse(crop_name)
        if seed_index is None:
            logger.warning('自动播种: 购买后仍未在仓库确认目标种子 | 作物={}', crop_name)
        return seed_index

    def _is_crop_aligned_with_strategy(self, crop_name: str) -> bool:
        """校验当前作物是否与自动策略一致。"""
        planting = self.config.planting
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
        if not ocr_match.target:
            target_price = get_crop_seed_price(crop_name)
            if target_price is not None:
                price_match = self.shop_ocr.find_item_by_price(cv_img, target_price)
                if price_match.target:
                    logger.info(
                        '购买流程: 名称未命中，价格匹配成功 | 种子={} 价格={}',
                        crop_name,
                        target_price,
                    )
                    ocr_match = price_match
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
