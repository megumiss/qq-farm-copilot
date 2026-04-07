"""nklite 农场主任务。"""

from __future__ import annotations

from loguru import logger

from core.base.timer import Timer
from core.engine.task.registry import TaskResult
from core.exceptions import BuySeedError
from core.ui.assets import *
from core.ui.page import page_main, page_shop
from models.farm_state import ActionType
from tasks.base import TaskBase
from utils.shop_item_ocr import ShopItemOCR


class TaskMain(TaskBase):
    """封装 `TaskMain` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)
        self._expand_failed = False
        self.shop_ocr = ShopItemOCR()

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行主流程：在 run 内按 feature 显式控制每个子方法。"""
        features = self.get_features('main')
        actions: list[str] = []

        self.ui.ui_ensure(page_main)

        # 一键收获
        if self.has_feature(features, 'auto_harvest'):
            action = self._run_feature_harvest()
            if action:
                actions.append(action)

        # 一键除草
        if self.has_feature(features, 'auto_weed'):
            action = self._run_feature_weed()
            if action:
                actions.append(action)

        # 一键除虫
        if self.has_feature(features, 'auto_bug'):
            action = self._run_feature_bug()
            if action:
                actions.append(action)

        # 一键浇水
        if self.has_feature(features, 'auto_water'):
            action = self._run_feature_water()
            if action:
                actions.append(action)

        # 自动播种
        if self.has_feature(features, 'auto_plant'):
            action = self._run_feature_plant()
            if action:
                actions.append(action)

        # TODO 自动施肥
        if self.has_feature(features, 'auto_fertilize'):
            action = self._run_feature_fertilize()
            if action:
                actions.append(action)

        # TODO 自动扩建
        if self.has_feature(features, 'auto_upgrade'):
            action = self._run_feature_upgrade()
            if action:
                actions.append(action)

        return self.ok(actions=actions)

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

    def _run_feature_single_action(self, button, stat_action: str, done_text: str) -> str | None:
        """通用单按钮循环动作：首检未命中直接返回，命中后点击到消失。"""
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
        self._buy_seeds(self.engine._resolve_crop_name())

        while 1:
            has_land = self.ui.appear_any(
                [LAND_EMPTY, LAND_EMPTY_2, LAND_EMPTY_3], offset=30, threshold=0.89, static=False
            )
            if not has_land:
                return None

            actions = self._plant_all(self.engine._resolve_crop_name())
            if not actions:
                return None
            return actions[-1]

    def _plant_all(self, crop_name: str) -> list[str]:
        """执行整块农田播种流程（识别空地、拉种子、补种购买）。"""
        all_actions: list[str] = []

        cv_img = self.ui.device.screenshot()
        if cv_img is None:
            return all_actions
        dets = self.engine.cv_detector.detect_templates(
            cv_img,
            template_names=['land_empty', 'land_empty_2', 'land_empty_3'],
            default_threshold=0.89,
            thresholds={'land_empty': 0.89, 'land_empty_2': 0.89, 'land_empty_3': 0.89},
        )
        lands = [d for d in dets if d.name.startswith('land_empty')]
        if not lands:
            return all_actions

        self.ui.device.click_point(int(lands[0].x), int(lands[0].y), desc='点击空地')
        self.ui.device.sleep(0.3)

        seed_det = None
        for _ in range(2):
            cv_img = self.ui.device.screenshot()
            if cv_img is None:
                return all_actions
            seed_dets = self.engine.cv_detector.detect_seed_template(cv_img, crop_name_or_template=crop_name)
            if seed_dets:
                seed_det = seed_dets[0]
                break
            self.ui.device.sleep(0.3)

        if not seed_det:
            buy_result = self._buy_seeds(crop_name)
            if buy_result:
                all_actions.append(buy_result)
                return all_actions + self._plant_all(crop_name)
            return all_actions

        if not self.engine.action_executor or not self.engine.device:
            return all_actions

        planted_count = 0
        dragging = False
        try:
            if not self.engine.device.drag_down_point(int(seed_det.x), int(seed_det.y), duration=0.05):
                return all_actions
            dragging = True
            if not self.ui.device.sleep(0.1):
                return all_actions

            for land in lands:
                if not self.engine.device.drag_move_point(int(land.x), int(land.y), duration=0.1):
                    break
                if not self.ui.device.sleep(0.15):
                    break
                planted_count += 1
        finally:
            if dragging:
                self.engine.device.drag_up()

        if planted_count > 0:
            all_actions.append(f'播种{crop_name}×{planted_count}')

        self.ui.device.sleep(0.5)
        cv_check = self.ui.device.screenshot()
        if cv_check is not None:
            if BTN_SHOP_CLOSE is not None and self.ui.appear(BTN_SHOP_CLOSE, offset=30, threshold=0.8, static=False):
                self._close_shop_and_buy(crop_name, all_actions)

            if BTN_FERTILIZE_POPUP is not None and self.ui.appear(
                BTN_FERTILIZE_POPUP, offset=30, threshold=0.8, static=False
            ):
                x, y = self.engine._resolve_goto_main_point()
                self.engine.device.click_point(x, y, desc='点击回主按钮')

        return all_actions

    def _close_shop_and_buy(self, crop_name: str, actions_done: list[str]):
        """关闭商店后立刻执行一次补种购买。"""
        buy_result = self._buy_seeds(crop_name)
        if buy_result:
            actions_done.append(buy_result)

    def _buy_seeds(self, crop_name: str) -> str | None:
        """执行买种流程：开商店 -> OCR 定位 -> 选择并确认购买。"""
        logger.info('购买流程: 开始 | 商品={}', crop_name)
        self.ui.ui_ensure(page_shop, confirm_wait=0.5)

        cv_img = self.ui.device.screenshot()
        ocr_match = self.shop_ocr.find_item(cv_img, crop_name, min_similarity=0.70)
        if not ocr_match.target:
            logger.error(f"购买流程: OCR未找到 '{crop_name}'")
            raise BuySeedError

        click_buy = False
        while 1:
            self.ui.device.screenshot()

            # 点击物品
            if not click_buy and self.ui.appear(SHOP_CHECK, offset=30):
                self.ui.device.click_point(
                    int(ocr_match.target.center_x), int(ocr_match.target.center_y), desc=f'选择{crop_name}'
                )
                self.ui.device.sleep(0.5)
                click_buy = True
                continue
            # 购买
            if self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_SHOP_BUY_CONFIRM, offset=30, interval=1
            ):
                continue
            if click_buy and not self.ui.appear(BTN_SHOP_BUY_CHECK, offset=30):
                logger.info('购买流程: 购买成功 | 商品={}', crop_name)
                break

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
