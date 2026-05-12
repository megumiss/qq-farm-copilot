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
        # 成熟阈值
        threshold_seconds = max(1, int(self.task.fertilize.feature.maturity_threshold_seconds))
        # 自动购买肥料
        auto_buy = bool(self.task.fertilize.feature.auto_buy_fertilizer)
        # 购买阈值
        buy_threshold_seconds = max(1, int(self.task.fertilize.feature.fertilizer_purchase_threshold_seconds))
        buy_threshold_hours = self._seconds_to_hours_ceil(buy_threshold_seconds)
        logger.info(
            '自动施肥: 开始 | 成熟阈值={}s 自动买肥={} 购买阈值={}h',
            threshold_seconds,
            auto_buy,
            buy_threshold_hours,
        )

        self.ui.ui_ensure(page_main)
        self.ui.device.click_button(GOTO_MAIN)
        self.align_view_by_background_tree(log_prefix='自动施肥')

        # 筛选符合阈值的地块
        target_plot_refs = self._collect_target_plot_refs(threshold_seconds=threshold_seconds)
        if not target_plot_refs:
            logger.info('自动施肥: 没有命中成熟阈值的地块，结束本轮')
            return self.ok()

        # ---- 第三步：映射屏幕坐标，探测肥料库存 ----
        all_targets = self._collect_targets_for_refs(target_plot_refs)
        if not all_targets:
            logger.warning('自动施肥: 地块坐标映射失败，跳过本轮')
            return self.fail('未识别到可施肥地块坐标')

        # 点开第一个地块弹窗，OCR 读取当前肥料库存(小时数)
        first_ref, first_point = all_targets[0]
        available_hours = self._probe_fertilizer_hours(plot_ref=first_ref, point=first_point)
        if available_hours is None:
            available_hours = 0

        # ---- 第四步：库存不足阈值时自动购买补货 ----
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
            )

        # ---- 第五步：最终库存校验——不够则提前终止，避免执行一半 ----
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

        # ---- 第六步：点击地块打开弹窗，拖拽肥料到所有地块 ----
        first_ref, first_point = all_targets[0]
        if not self._open_plot_popup(plot_ref=first_ref, point=first_point):
            self.ui.device.click_button(GOTO_MAIN)
            self.ui.device.sleep(0.2)
            return self.fail('地块弹窗打开失败')

        fertilizer_loc = self.ui.appear_location(BTN_ORDINARY_FERTILIZER, offset=30, static=False)
        if fertilizer_loc is None:
            fertilizer_loc = self.ui.appear_location(BTN_ORGANIC_FERTILIZER, offset=30, static=False)
        if fertilizer_loc is None:
            self.ui.device.click_button(GOTO_MAIN)
            self.ui.device.sleep(0.2)
            return self.fail('未识别到肥料按钮')

        drag_x, drag_y = int(fertilizer_loc[0]), int(fertilizer_loc[1])
        dragging = False
        try:
            self.engine.device.drag_down_point(drag_x, drag_y, duration=0.1)
            dragging = True
            self.ui.device.sleep(0.1)
            for _, point in all_targets:
                self.engine.device.drag_move_point(int(point[0]), int(point[1]), duration=0.1)
                self.ui.device.sleep(0.15)
        finally:
            if dragging:
                self.engine.device.drag_up()

        self.ui.device.click_button(GOTO_MAIN)
        self.ui.device.sleep(0.2)

        # ---- 收尾：回到主页面并汇报结果 ----
        self.ui.ui_ensure(page_main)
        logger.info('自动施肥: 结束 | fertilized={}/{}', len(all_targets), required_hours)
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
        """点击地块坐标打开弹窗，等待识别：成功返回 True，空地/超时返回 False。"""
        # 点击地块坐标，触发弹窗弹出
        self.ui.device.click_point(int(point[0]), int(point[1]), desc=f'点击施肥地块 {plot_ref}')
        wait_timer = Timer(1.0, count=1).start()
        while 1:
            self.ui.device.screenshot()
            # 空地无作物 → 跳过该地块
            if self.ui.appear(BTN_LAND_POP_EMPTY, offset=(-160, -180, 280, 280), threshold=0.65):
                logger.info('自动施肥: 地块为空地，跳过 | plot={}', plot_ref)
                return False
            # 识别到"铲除"按钮 = 作物弹窗已打开 → 操作就绪
            if self.ui.appear(BTN_CROP_REMOVAL, offset=30, static=False):
                return True
            # 超时仍未识别到弹窗 → 放弃该地块
            if wait_timer.reached():
                logger.warning('自动施肥: 地块弹窗识别超时 | plot={}', plot_ref)
                return False
            self.ui.device.sleep(0.1)

    def _ensure_fertilizer_hours(
        self,
        *,
        target_hours: int,
        probe_ref: str,
    ) -> tuple[int, bool]:
        """自动购买并复检库存，直到达到目标阈值或达到上限。"""
        last_hours = 0
        for round_index in range(1, FERTILIZE_BUY_MAX_ROUNDS + 1):
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
        """执行一次肥料购买流程：进商店 → OCR 定位肥料 → 点击 → 确认购买。"""
        logger.info('自动施肥: 开始购买肥料')
        # 进入商店页面
        self.ui.ui_ensure(page_shop, confirm_wait=0.5)
        # OCR 定位肥料商品位置（必要时上滑翻页）
        target_item = self._locate_fertilizer_item()
        if target_item is None:
            logger.warning('自动施肥: 商店未识别到肥料商品')
            self.ui.ui_ensure(page_main)
            return False

        # 购买流程：点击商品 → 出现确认弹窗 → 点击确认 → 弹窗消失 = 成功
        click_buy = False  # 标记"确认按钮已点击"，后续检测弹窗消失即完成
        wait_timer = Timer(6.0, count=1).start()
        while 1:
            self.ui.device.screenshot()
            # 确认按钮已被点击，且确认弹窗已消失 → 购买完成
            if click_buy and not self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30):
                self.ui.ui_ensure(page_main)
                logger.info('自动施肥: 肥料购买成功')
                return True
            # 确认弹窗出现 → 点击"确认购买"
            if self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_SHOP_BUY_CONFIRM,
                offset=30,
                interval=1,
            ):
                click_buy = True
                continue
            # 商店列表页面（未弹出确认框）→ 点击肥料商品
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
            # 超时保护
            if wait_timer.reached():
                logger.warning('自动施肥: 购买流程超时')
                self.ui.ui_ensure(page_main)
                return False

    def _locate_fertilizer_item(self):
        """OCR 定位肥料商品，必要时上滑翻页（最多翻 8 页）。"""
        seen_items: set[str] = set()
        for _ in range(8):
            cv_img = self.ui.device.screenshot()
            if cv_img is None:
                return None
            best_item = None
            # 按候选名称列表逐个 OCR 匹配（普通化肥 > 有机化肥 > 化肥）
            for name in FERTILIZER_ITEM_CANDIDATES:
                match = self.shop_ocr.find_item(cv_img, name, min_similarity=0.75)
                # 精确命中 → 直接返回
                if match.target is not None:
                    return match.target
                # 记录最佳近似匹配
                if match.best is not None and (best_item is None or match.best_similarity > best_item[1]):
                    best_item = (match.best, match.best_similarity)
                for parsed in match.parsed_items:
                    seen_items.add(str(parsed.name))
            # 无精确命中但近似度 >= 0.85 → 作为兜底返回
            if best_item is not None and best_item[1] >= 0.85:
                return best_item[0]
            # 当前页未找到 → 上滑翻页
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
        # OCR 截图中肥料库存区域，增强对比度以提高识别率
        items = self.engine._get_ocr_tool().detect(  # type: ignore[attr-defined]
            image,
            region=FERTILIZE_HOURS_OCR_REGION,
            scale=1.3,
            alpha=1.15,
            beta=0.0,
        )
        # 合并所有 OCR 文本块，去除空格后统一匹配
        merged = ''.join(str(item.text or '').strip() for item in items if str(item.text or '').strip())
        merged = merged.replace(' ', '')
        # 优先匹配 "数字+小时/h" 格式（如 "10小时"、"10h"）
        matched_hours = [int(num) for num in FERTILIZE_HOURS_PATTERN.findall(merged)]
        if matched_hours:
            value = max(matched_hours)
            logger.info('自动施肥: 识别肥料库存={}h | raw={}', value, merged or '<empty>')
            return value
        # 兜底：提取所有数字取最大值
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
