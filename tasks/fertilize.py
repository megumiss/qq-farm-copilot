"""自动施肥任务。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from core.base.timer import Timer
from core.engine.task.registry import TaskResult
from core.ui.assets import (
    BTN_CROP_REMOVAL,
    BTN_LAND_LEFT,
    BTN_LAND_POP_EMPTY,
    BTN_LAND_RIGHT,
    BTN_ORDINARY_FERTILIZER,
    BTN_ORGANIC_FERTILIZER,
    BTN_SHOP_BUY_CHECK,
    BTN_SHOP_BUY_CONFIRM,
    SHOP_CHECK,
)
from core.ui.page import GOTO_MAIN, page_main, page_shop
from models.farm_state import ActionType
from tasks.base import TaskBase
from utils.land_grid import get_lands_from_land_anchor
from utils.shop_item_ocr import ShopItemOCR

if TYPE_CHECKING:
    from core.ui.ui import UI
    from models.config import AppConfig
    from utils.ocr_utils import OCRTool

# 商店列表上滑的起点坐标（用于翻页查找肥料）。
FERTILIZE_SHOP_LIST_SWIPE_START = (270, 300)
# 商店列表上滑的终点坐标（与起点配合形成上滑手势）。
FERTILIZE_SHOP_LIST_SWIPE_END = (270, 860)
# 肥料库存 OCR 区域（固定弹窗底部区域）。
FERTILIZE_HOURS_OCR_REGION = (60, 560, 320, 740)
# 肥料库存文本提取模式（优先匹配“数字+小时/h”）。
FERTILIZE_HOURS_PATTERN = re.compile(r'(\d+)\s*(?:小时|h|H)')
# 文本中的数字模式（兜底）。
FERTILIZE_NUMBER_PATTERN = re.compile(r'\d+')
# 成熟倒计时 `HH:MM:SS` 模式。
FERTILIZE_COUNTDOWN_PATTERN = re.compile(r'^(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})$')
# 肥料商品 OCR 候选名称（按优先级）。
FERTILIZER_ITEM_CANDIDATES = ('普通化肥', '有机化肥', '化肥')
# 自动补货最多尝试轮次（每轮=购买一次+复检一次）。
FERTILIZE_BUY_MAX_ROUNDS = 6


class TaskFertilize(TaskBase):
    """按土地巡查数据筛选地块并执行自动施肥。"""

    config: 'AppConfig'
    ui: 'UI'

    def __init__(self, engine, ui, *, ocr_tool: 'OCRTool | None' = None):
        super().__init__(engine, ui)
        self.shop_ocr = ShopItemOCR(
            vocab=[*FERTILIZER_ITEM_CANDIDATES],
            ocr_tool=ocr_tool,
        )

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        _ = rect
        threshold_seconds = max(1, int(self.task.fertilize.feature.maturity_threshold_seconds))
        auto_buy = bool(self.task.fertilize.feature.auto_buy_fertilizer)
        buy_threshold_seconds = max(1, int(self.task.fertilize.feature.fertilizer_purchase_threshold_seconds))
        buy_threshold_hours = self._seconds_to_hours_ceil(buy_threshold_seconds)

        logger.info(
            '自动施肥: 开始 | maturity_threshold={}s auto_buy={} buy_threshold={}h',
            threshold_seconds,
            auto_buy,
            buy_threshold_hours,
        )
        self.ui.ui_ensure(page_main)
        self.ui.device.click_button(GOTO_MAIN)
        self.align_view_by_background_tree(log_prefix='自动施肥')

        target_plot_refs = self._collect_target_plot_refs(threshold_seconds=threshold_seconds)
        if not target_plot_refs:
            logger.info('自动施肥: 没有命中成熟阈值的地块，结束本轮')
            return self.ok()

        refs_12345, refs_6789 = self._split_plot_refs_by_physical_group(target_plot_refs)
        group_pairs: list[tuple[str, list[str]]] = []
        if refs_12345:
            group_pairs.append(('12345', refs_12345))
        if refs_6789:
            group_pairs.append(('6789', refs_6789))
        if not group_pairs:
            logger.warning('自动施肥: 地块分组失败，跳过本轮')
            return self.fail('地块分组失败')

        first_group_name, first_group_refs = group_pairs[0]
        self._swipe_to_group(first_group_name)
        first_group_targets = self._collect_targets_for_refs(first_group_refs)
        if not first_group_targets:
            logger.warning('自动施肥: 地块坐标映射失败，跳过本轮')
            return self.fail('未识别到可施肥地块坐标')

        first_ref, first_point = first_group_targets[0]
        available_hours = self._probe_fertilizer_hours(plot_ref=first_ref, point=first_point)
        if available_hours is None:
            available_hours = 0

        required_hours = len(target_plot_refs)
        if auto_buy and available_hours < buy_threshold_hours:
            logger.info(
                '自动施肥: 当前库存低于购买阈值，触发补货 | available={}h threshold={}h',
                available_hours,
                buy_threshold_hours,
            )
            available_hours, _ = self._ensure_fertilizer_hours(
                target_hours=buy_threshold_hours,
                probe_ref=first_ref,
                probe_group_name=first_group_name,
            )

        if available_hours < required_hours:
            logger.warning('自动施肥: 肥料不足 | available={}h required={}h', available_hours, required_hours)
            if not auto_buy:
                logger.warning('自动施肥: 未开启自动购买肥料，结束本轮')
                return self.fail('肥料不足，且未开启自动购买')
            logger.warning(
                '自动施肥: 按阈值补货后仍不足本轮需求 | available={}h required={}h threshold={}h',
                available_hours,
                required_hours,
                buy_threshold_hours,
            )
            return self.fail('肥料不足，请提高肥料购买阈值')

        fertilized_count = 0
        for group_name, group_refs in group_pairs:
            self._swipe_to_group(group_name)
            group_targets = self._collect_targets_for_refs(group_refs)
            for plot_ref, point in group_targets:
                if available_hours <= 0:
                    logger.warning('自动施肥: 肥料已用尽，提前结束')
                    break
                if self._fertilize_single_plot(plot_ref=plot_ref, point=point):
                    fertilized_count += 1
                    available_hours = max(0, int(available_hours) - 1)
            if available_hours <= 0:
                break

        self.ui.ui_ensure(page_main)
        logger.info('自动施肥: 结束 | fertilized={}/{}', fertilized_count, required_hours)
        return self.ok()

    def _collect_target_plot_refs(self, *, threshold_seconds: int) -> list[str]:
        """从土地详情里筛选成熟倒计时小于阈值的地块。"""
        candidates: list[tuple[int, str]] = []
        for item in self.parse_land_detail_plots():
            plot_ref = str(item.get('plot_id', '') or '').strip()
            countdown_seconds = self._parse_countdown_seconds(item.get('maturity_countdown'))
            if not plot_ref or countdown_seconds is None:
                continue
            if countdown_seconds <= 0 or countdown_seconds > int(threshold_seconds):
                continue
            candidates.append((countdown_seconds, plot_ref))

        candidates.sort(key=lambda row: (row[0], row[1]))
        refs = [plot_ref for _, plot_ref in candidates]
        logger.info('自动施肥: 倒计时命中地块={}', refs)
        return refs

    @staticmethod
    def _parse_countdown_seconds(value: object) -> int | None:
        text = str(value or '').strip()
        if not text:
            return None
        match = FERTILIZE_COUNTDOWN_PATTERN.match(text)
        if not match:
            return None
        hour = int(match.group('h'))
        minute = int(match.group('m'))
        second = int(match.group('s'))
        if hour < 0 or minute < 0 or minute > 59 or second < 0 or second > 59:
            return None
        return hour * 3600 + minute * 60 + second

    @staticmethod
    def _physical_col_from_plot_ref(plot_ref: str) -> int | None:
        text = str(plot_ref or '').strip()
        left, sep, right = text.partition('-')
        if sep != '-':
            return None
        try:
            logical_col = int(left)
            logical_row = int(right)
        except Exception:
            return None
        idx = (4 - logical_row) + (logical_col - 1) + 1
        return max(1, min(9, idx))

    def _split_plot_refs_by_physical_group(self, plot_refs: list[str]) -> tuple[list[str], list[str]]:
        """按物理列将地块序号拆分为 `1-5` 与 `6-9` 两组。"""
        uniq_refs: list[str] = []
        seen_refs: set[str] = set()
        for ref in plot_refs:
            text = str(ref or '').strip()
            if not text or text in seen_refs:
                continue
            seen_refs.add(text)
            uniq_refs.append(text)

        ordered = sorted(
            uniq_refs,
            key=lambda ref: (
                int(self._physical_col_from_plot_ref(ref) or 9),
                ref,
            ),
        )
        refs_12345 = [ref for ref in ordered if int(self._physical_col_from_plot_ref(ref) or 9) <= 5]
        refs_6789 = [ref for ref in ordered if int(self._physical_col_from_plot_ref(ref) or 9) > 5]
        return refs_12345, refs_6789

    def _swipe_to_group(self, group_name: str) -> None:
        left_p1 = (350, 190)
        left_p2 = (200, 190)
        if group_name == '12345':
            for _ in range(2):
                self.ui.device.swipe(left_p1, left_p2, speed=30)
                self.ui.device.sleep(0.5)
            return
        for _ in range(2):
            self.ui.device.swipe(left_p2, left_p1, speed=30)
            self.ui.device.sleep(0.5)

    def _collect_targets_for_refs(self, refs: list[str]) -> list[tuple[str, tuple[int, int]]]:
        if not refs:
            return []
        self.ui.device.screenshot()
        land_right_anchor = self.ui.appear_location(BTN_LAND_RIGHT, offset=30, threshold=0.95, static=False)
        land_left_anchor = self.ui.appear_location(BTN_LAND_LEFT, offset=30, threshold=0.95, static=False)
        if land_right_anchor is None and land_left_anchor is None:
            logger.warning('自动施肥: 未识别到地块锚点，当前分组跳过 | refs={}', refs)
            return []
        all_lands = get_lands_from_land_anchor(
            (int(land_right_anchor[0]), int(land_right_anchor[1])) if land_right_anchor is not None else None,
            (int(land_left_anchor[0]), int(land_left_anchor[1])) if land_left_anchor is not None else None,
        )
        if not all_lands:
            logger.warning('自动施肥: 网格生成失败，当前分组跳过 | refs={}', refs)
            return []

        center_by_plot_id = {str(cell.label): (int(cell.center[0]), int(cell.center[1])) for cell in all_lands}
        targets: list[tuple[str, tuple[int, int]]] = []
        for ref in refs:
            point = center_by_plot_id.get(str(ref))
            if point is None:
                logger.warning('自动施肥: 当前画面缺失地块坐标 | plot={}', ref)
                continue
            targets.append((str(ref), point))
        return targets

    def _probe_fertilizer_hours(self, *, plot_ref: str, point: tuple[int, int]) -> int | None:
        """打开一个地块弹窗并识别当前肥料库存（小时）。"""
        opened = self._open_plot_popup(plot_ref=plot_ref, point=point)
        if not opened:
            self.ui.device.click_button(GOTO_MAIN)
            self.ui.device.sleep(0.2)
            return None
        hours = self._read_fertilizer_hours_from_popup()
        self.ui.device.click_button(GOTO_MAIN)
        self.ui.device.sleep(0.2)
        return hours

    def _open_plot_popup(self, *, plot_ref: str, point: tuple[int, int]) -> bool:
        self.ui.device.click_point(int(point[0]), int(point[1]), desc=f'点击施肥地块 {plot_ref}')
        wait_timer = Timer(1.0, count=1).start()
        while 1:
            self.ui.device.screenshot()
            if self.ui.appear(BTN_LAND_POP_EMPTY, offset=(-160, -180, 280, 280), threshold=0.65):
                logger.info('自动施肥: 地块为空地，跳过 | plot={}', plot_ref)
                return False
            if self.ui.appear(BTN_CROP_REMOVAL, offset=30, static=False):
                return True
            if wait_timer.reached():
                logger.warning('自动施肥: 地块弹窗识别超时 | plot={}', plot_ref)
                return False
            self.ui.device.sleep(0.1)

    def _fertilize_single_plot(self, *, plot_ref: str, point: tuple[int, int]) -> bool:
        if not self._open_plot_popup(plot_ref=plot_ref, point=point):
            self.ui.device.click_button(GOTO_MAIN)
            self.ui.device.sleep(0.2)
            return False

        applied = False
        stable_timer = Timer(0.5, count=2)
        timeout_timer = Timer(3.0, count=1).start()
        while 1:
            self.ui.device.screenshot()
            if self.ui.appear_then_click_any(
                [BTN_ORDINARY_FERTILIZER, BTN_ORGANIC_FERTILIZER],
                offset=30,
                interval=1,
                static=False,
            ):
                applied = True
                self.engine._record_stat(ActionType.FERTILIZE)
                continue
            if not self.ui.appear(BTN_CROP_REMOVAL, offset=30, static=False):
                if not stable_timer.started():
                    stable_timer.start()
                if stable_timer.reached():
                    break
            else:
                stable_timer.clear()
                if applied:
                    break
                # 仍在弹窗内但未命中肥料按钮，避免死循环。
                if not self.ui.appear(BTN_ORDINARY_FERTILIZER, offset=30, static=False) and not self.ui.appear(
                    BTN_ORGANIC_FERTILIZER, offset=30, static=False
                ):
                    logger.warning('自动施肥: 弹窗未发现肥料按钮 | plot={}', plot_ref)
                    break
            if timeout_timer.reached():
                logger.warning('自动施肥: 施肥流程超时 | plot={}', plot_ref)
                break

        self.ui.device.click_button(GOTO_MAIN)
        self.ui.device.sleep(0.2)
        if applied:
            logger.info('自动施肥: 地块施肥成功 | plot={}', plot_ref)
        return applied

    def _ensure_fertilizer_hours(
        self,
        *,
        target_hours: int,
        probe_ref: str,
        probe_group_name: str,
    ) -> tuple[int, bool]:
        """自动购买并复检库存，直到达到目标阈值或达到上限。"""
        last_hours = 0
        for round_index in range(1, FERTILIZE_BUY_MAX_ROUNDS + 1):
            self._swipe_to_group(probe_group_name)
            probe_targets = self._collect_targets_for_refs([probe_ref])
            if not probe_targets:
                logger.warning('自动施肥: 补货复检缺失地块坐标 | plot={}', probe_ref)
                break
            _, probe_point = probe_targets[0]
            probed = self._probe_fertilizer_hours(plot_ref=probe_ref, point=probe_point)
            if probed is not None:
                last_hours = max(0, int(probed))
            if last_hours >= int(target_hours):
                return last_hours, True
            logger.info(
                '自动施肥: 自动补货第{}轮 | current={}h target={}h',
                round_index,
                last_hours,
                target_hours,
            )
            if not self._buy_fertilizer_once():
                break
        return last_hours, last_hours >= int(target_hours)

    def _buy_fertilizer_once(self) -> bool:
        """执行一次肥料购买流程。"""
        logger.info('自动施肥: 开始购买肥料')
        self.ui.ui_ensure(page_shop, confirm_wait=0.5)
        target_item = self._locate_fertilizer_item()
        if target_item is None:
            logger.warning('自动施肥: 商店未识别到肥料商品')
            self.ui.ui_ensure(page_main)
            return False

        click_buy = False
        wait_timer = Timer(6.0, count=1).start()
        while 1:
            self.ui.device.screenshot()
            if click_buy and not self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30):
                self.ui.ui_ensure(page_main)
                logger.info('自动施肥: 肥料购买成功')
                return True
            if self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_SHOP_BUY_CONFIRM,
                offset=30,
                interval=1,
            ):
                click_buy = True
                continue
            if (
                self.ui.appear(SHOP_CHECK, offset=30)
                and not self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30)
                and not self.ui.appear(BTN_SHOP_BUY_CONFIRM, offset=30)
            ):
                self.ui.device.click_point(
                    int(target_item.center_x),
                    int(target_item.center_y),
                    desc=f'选择{target_item.name}',
                )
                self.ui.device.sleep(0.5)
                continue
            if wait_timer.reached():
                logger.warning('自动施肥: 购买流程超时')
                self.ui.ui_ensure(page_main)
                return False

    def _locate_fertilizer_item(self):
        """OCR 定位肥料商品，必要时上滑翻页。"""
        seen_items: set[str] = set()
        for _ in range(8):
            cv_img = self.ui.device.screenshot()
            if cv_img is None:
                return None
            best_item = None
            for name in FERTILIZER_ITEM_CANDIDATES:
                match = self.shop_ocr.find_item(cv_img, name, min_similarity=0.75)
                if match.target is not None:
                    return match.target
                if match.best is not None and (best_item is None or match.best_similarity > best_item[1]):
                    best_item = (match.best, match.best_similarity)
                for parsed in match.parsed_items:
                    seen_items.add(str(parsed.name))
            if best_item is not None and best_item[1] >= 0.85:
                return best_item[0]
            self.ui.device.swipe(
                FERTILIZE_SHOP_LIST_SWIPE_START,
                FERTILIZE_SHOP_LIST_SWIPE_END,
                speed=30,
                delay=1,
                hold=0.1,
            )
        logger.debug('自动施肥: 肥料 OCR 候选={}', sorted(seen_items))
        return None

    def _read_fertilizer_hours_from_popup(self) -> int:
        """从地块弹窗 OCR 提取肥料库存小时数。"""
        image = getattr(self.ui.device, 'image', None)
        if image is None:
            return 0
        items = self.engine._get_ocr_tool().detect(  # type: ignore[attr-defined]
            image,
            region=FERTILIZE_HOURS_OCR_REGION,
            scale=1.3,
            alpha=1.15,
            beta=0.0,
        )
        merged = ''.join(str(item.text or '').strip() for item in items if str(item.text or '').strip())
        merged = merged.replace(' ', '')
        matched_hours = [int(num) for num in FERTILIZE_HOURS_PATTERN.findall(merged)]
        if matched_hours:
            value = max(matched_hours)
            logger.info('自动施肥: 识别肥料库存={}h | raw={}', value, merged or '<empty>')
            return value
        raw_numbers = [int(num) for num in FERTILIZE_NUMBER_PATTERN.findall(merged)]
        if raw_numbers:
            value = max(raw_numbers)
            logger.info('自动施肥: 识别肥料库存(兜底)={}h | raw={}', value, merged or '<empty>')
            return value
        logger.warning('自动施肥: 未识别到肥料库存数字 | raw={}', merged or '<empty>')
        return 0

    @staticmethod
    def _seconds_to_hours_ceil(seconds: int) -> int:
        value = max(0, int(seconds))
        if value <= 0:
            return 0
        return (value + 3600 - 1) // 3600
