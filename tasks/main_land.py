"""TaskMain 土地相关逻辑（扩建/升级）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from core.base.timer import Timer
from core.ui.assets import *
from core.ui.page import GOTO_MAIN, page_main

if TYPE_CHECKING:
    from core.engine.bot.local_engine import LocalBotEngine
    from core.ui.ui import UI

# 固定截图宽高（宽x高）。
LAND_SCAN_FRAME_WIDTH = 540
LAND_SCAN_FRAME_HEIGHT = 960
# 空地弹窗升级图标 ROI：相对 BTN_CROP_REMOVAL 中心 (dx1, dy1, dx2, dy2)。
LAND_UPGRADE_REGION_OFFSET = (-100, -50, 0, -0)


class TaskMainLandMixin:
    """提供自动扩建与自动升级流程。"""

    engine: 'LocalBotEngine'
    ui: 'UI'

    def _run_feature_expand(self) -> str | None:
        """自动扩建"""
        return self._try_expand()

    def _run_feature_upgrade(self) -> str | None:
        """自动升级"""
        return self._try_upgrade()

    def _run_upgrade_steps_for_selected_land(self, *, plot_ref: str) -> None:
        """在已选中地块弹窗上执行升级步骤。"""
        while 1:
            self.ui.device.screenshot()
            if self.ui.appear(BTN_LAND_UPGRADE_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_LAND_UPGRADE_CONFIRM, offset=30, interval=1
            ):
                continue
            if not self.ui.appear(BTN_LAND_UPGRADE_CHECK, offset=30):
                logger.info('自动升级流程: 地块升级完成 | 序号={}', plot_ref)
                break

    @staticmethod
    def _physical_col_from_plot_ref(plot_ref: str) -> int | None:
        """由地块序号（如 `1-1`）计算物理列索引（1..9）。"""
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

        group_12345 = [ref for ref in ordered if int(self._physical_col_from_plot_ref(ref) or 9) <= 5]
        group_6789 = [ref for ref in ordered if int(self._physical_col_from_plot_ref(ref) or 9) > 5]
        return group_12345, group_6789

    def _swipe_to_upgrade_group(self, group_name: str) -> None:
        """根据分组执行升级前画面滑动。"""
        # 参考土地巡查任务手势：LAND_SCAN_SWIPE_H_P1=(350,190), LAND_SCAN_SWIPE_H_P2=(200,190)
        left_p1 = (350, 190)
        left_p2 = (200, 190)
        if group_name == '12345':
            for _ in range(2):
                self.ui.device.swipe(left_p1, left_p2, speed=30)
                self.ui.device.sleep(0.5)
            return
        if group_name == '6789':
            for _ in range(2):
                self.ui.device.swipe(left_p2, left_p1, speed=30)
                self.ui.device.sleep(0.5)

    @staticmethod
    def _build_upgrade_icon_region(center: tuple[int, int]) -> tuple[int, int, int, int]:
        """按锚点与偏移构造升级图标检测 ROI。"""
        dx1, dy1, dx2, dy2 = LAND_UPGRADE_REGION_OFFSET
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

    def _collect_group_targets_after_swipe(self, group_refs: list[str]) -> list[tuple[str, tuple[int, int]]]:
        """滑动后重新采集当前组的实时地块坐标。"""
        if not group_refs:
            return []
        live_targets = self.collect_land_targets_by_flag(
            'need_upgrade', anchor_threshold=0.95, log_prefix='自动升级流程'
        )
        if not live_targets:
            return []
        live_map = {ref: point for ref, point in live_targets}
        targets = [(ref, live_map[ref]) for ref in group_refs if ref in live_map]
        missing_refs = [ref for ref in group_refs if ref not in live_map]
        if missing_refs:
            logger.warning('自动升级流程: 当前画面未找到地块 | 序号={}', missing_refs)
        return targets

    def _upgrade_targets(self, targets: list[tuple[str, tuple[int, int]]]) -> bool:
        """执行一组地块升级。"""
        for plot_ref, point in targets:
            logger.info('自动升级流程: 开始升级地块 | 序号={}', plot_ref)

            need_upgrade = False
            upgrade_button = None
            click_timer = Timer(1, count=3).start()
            self.engine.device.click_point(int(point[0]), int(point[1]), desc=f'点击待升级地块 {plot_ref}')
            while 1:
                self.ui.device.screenshot()
                removal_location = None
                if self.ui.appear(BTN_CROP_REMOVAL, offset=30, static=False):
                    removal_location = self.ui.appear_location(BTN_CROP_REMOVAL, offset=30, static=False)
                elif self.ui.appear(BTN_LAND_POP_EMPTY, offset=(-160, -180, 280, 280), threshold=0.65):
                    removal_location = self.ui.appear_location(
                        BTN_LAND_POP_EMPTY, offset=(-160, -180, 280, 280), threshold=0.65
                    )

                if removal_location is not None:
                    matched = self.ui.match_gif_multi(
                        ICON_LAND_UPGRADE,
                        roi=self._build_upgrade_icon_region(removal_location),
                    )
                    if matched:
                        need_upgrade = True
                        upgrade_button = matched[0]
                    else:
                        logger.warning('自动升级流程: 地块不需要升级 | 序号={}', plot_ref)
                    break
                if click_timer.reached():
                    logger.warning('自动升级流程: 地块点击出错 | 序号={}', plot_ref)
                    break
                self.ui.device.sleep(0.1)

            if need_upgrade and upgrade_button is not None:
                # 点击升级图标
                self.engine.device.click_point(
                    int(upgrade_button.location[0]), int(upgrade_button.location[1]), desc='点击升级'
                )
                while 1:
                    self.ui.device.screenshot()
                    if self.ui.appear(BTN_LAND_UPGRADE_CHECK, offset=30):
                        break
                self._run_upgrade_steps_for_selected_land(plot_ref=plot_ref)
                self.backfill_land_flag_false([plot_ref], 'need_upgrade', log_prefix='自动升级')

            self.ui.device.click_button(GOTO_MAIN)
            self.ui.device.sleep(0.2)
        return

    def _try_expand(self) -> str | None:
        """执行一次土地扩建流程"""
        logger.info('自动扩建: 开始')
        self.ui.ui_ensure(page_main)
        # 点击空白处
        self.ui.device.click_button(GOTO_MAIN)
        self.ui.device.screenshot()
        if not self.ui.appear(BTN_EXPAND, offset=30, static=False):
            logger.info('自动扩建: 未发现待扩建土地')
            return None

        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(BTN_EXPAND, offset=30, interval=1, static=False):
                continue
            if self.ui.appear(BTN_EXPAND_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_EXPAND_DIRECT_CONFIRM, offset=30, interval=1
            ):
                continue
            if self.ui.appear(BTN_EXPAND_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_EXPAND_CONFIRM, offset=30, interval=1
            ):
                continue
            if not self.ui.appear(BTN_EXPAND, offset=30, static=False):
                logger.info('自动扩建: 已完成')
                break

        return None

    def _try_upgrade(self) -> str | None:
        """按土地详情待升级列表逐地块执行升级流程。"""
        logger.info('自动升级流程: 开始')
        self.ui.ui_ensure(page_main)
        self.ui.device.click_button(GOTO_MAIN)

        initial_targets = self.collect_land_targets_by_flag(
            'need_upgrade', anchor_threshold=0.95, log_prefix='自动升级流程'
        )
        if not initial_targets:
            logger.info('自动升级流程: 无待升级地块')
            return None

        initial_refs = [ref for ref, _ in initial_targets]
        refs_12345, refs_6789 = self._split_plot_refs_by_physical_group(initial_refs)
        if refs_12345:
            logger.info('自动升级流程: 分组 1-5 | 序号={}', refs_12345)
            self._swipe_to_upgrade_group('12345')
            targets_12345 = self._collect_group_targets_after_swipe(refs_12345)
            self._upgrade_targets(targets_12345)

        if refs_6789:
            logger.info('自动升级流程: 分组 6-9 | 序号={}', refs_6789)
            self._swipe_to_upgrade_group('6789')
            targets_6789 = self._collect_group_targets_after_swipe(refs_6789)
            self._upgrade_targets(targets_6789)

        logger.info('自动升级流程: 结束')
        return
