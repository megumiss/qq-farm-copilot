"""播种任务。"""

from __future__ import annotations

import pyautogui
from loguru import logger

from core.base.step_result import StepResult
from core.ui.assets import (
    ASSET_NAME_TO_CONST,
    BTN_BUY_CONFIRM,
    BTN_CLAIM,
    BTN_CLOSE,
    BTN_CONFIRM,
    BTN_FERTILIZE_POPUP,
    LAND_EMPTY,
    LAND_EMPTY_2,
    LAND_EMPTY_3,
)
from models.farm_state import Action, ActionType
from utils.shop_item_ocr import ShopItemOCR

BTN_SHOP = ASSET_NAME_TO_CONST.get('btn_shop')
BTN_SHOP_CLOSE = ASSET_NAME_TO_CONST.get('btn_shop_close')


class TaskFarmPlant:
    """封装 `TaskFarmPlant` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui
        self.shop_ocr = ShopItemOCR()

    def run(self, rect, features) -> StepResult:
        """执行当前模块主流程并返回结果。"""
        if not features.get('auto_plant', False):
            return StepResult()

        has_land = self.ui.appear_any(
            [LAND_EMPTY, LAND_EMPTY_2, LAND_EMPTY_3],
            offset=(30, 30),
            threshold=0.89,
            static=False,
        )
        if not has_land:
            return StepResult()
        out = StepResult.from_value(self._plant_all(rect, self.engine._resolve_crop_name()))
        return out

    def _capture(self, rect: tuple[int, int, int, int]):
        """执行截图流程并返回图像结果。"""
        cv_img, _dets, _image = self.engine._capture_and_detect(rect, save=False, template_names=[])
        if cv_img is not None and self.ui and getattr(self.ui, 'device', None):
            self.ui.device.set_image(cv_img)
        return cv_img

    def _sleep(self, seconds: float) -> bool:
        """可中断休眠。"""
        return self.engine._sleep_interruptible(seconds)

    def _click(self, x: int, y: int, desc: str = '', action_type: str = ActionType.NAVIGATE) -> bool:
        """执行一次通用点击。"""
        if not self.engine.action_executor:
            return False
        rel_x, rel_y = self.engine.resolve_live_click_point(int(x), int(y))
        action = Action(
            type=action_type,
            click_position={'x': int(rel_x), 'y': int(rel_y)},
            priority=0,
            description=str(desc or 'click'),
        )
        result = self.engine.action_executor.execute_action(action)
        return bool(result.success)

    def _click_goto_main(self, rect: tuple[int, int, int, int]):
        """点击回主位置。"""
        x, y = self.engine._resolve_goto_main_point(rect)
        self.engine._nklite_click(x, y, '点击回主按钮')

    def _plant_all(self, rect: tuple[int, int, int, int], crop_name: str) -> list[str]:
        """执行整块农田播种流程（识别空地、拉种子、补种购买）。"""
        all_actions: list[str] = []

        cv_img = self._capture(rect)
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

        self._click(lands[0].x, lands[0].y, '点击空地')
        self._sleep(0.3)

        seed_det = None
        for _ in range(2):
            if self.engine._is_cancel_requested():
                return all_actions
            cv_img = self._capture(rect)
            if cv_img is None:
                return all_actions
            seed_dets = self.engine.cv_detector.detect_seed_template(cv_img, crop_name_or_template=crop_name)
            if seed_dets:
                seed_det = seed_dets[0]
                break
            self._sleep(0.3)

        if not seed_det:
            buy_result = self._buy_seeds(rect, crop_name)
            if buy_result:
                all_actions.append(buy_result)
                return all_actions + self._plant_all(rect, crop_name)
            return all_actions

        if not self.engine.action_executor:
            return all_actions

        seed_x, seed_y = self.engine.resolve_live_click_point(int(seed_det.x), int(seed_det.y))
        seed_abs_x, seed_abs_y = self.engine.action_executor.relative_to_absolute(seed_x, seed_y)
        planted_count = 0
        dragging = False
        try:
            if self.engine._is_cancel_requested():
                return all_actions
            pyautogui.moveTo(seed_abs_x, seed_abs_y, duration=0.05)
            if not self._sleep(0.1):
                return all_actions
            pyautogui.mouseDown()
            dragging = True
            if not self._sleep(0.1):
                return all_actions

            for land in lands:
                if self.engine._is_cancel_requested():
                    break
                land_x, land_y = self.engine.resolve_live_click_point(int(land.x), int(land.y))
                abs_x, abs_y = self.engine.action_executor.relative_to_absolute(land_x, land_y)
                pyautogui.moveTo(abs_x, abs_y, duration=0.1)
                if not self._sleep(0.15):
                    break
                planted_count += 1
        finally:
            if dragging:
                try:
                    pyautogui.mouseUp()
                except Exception:
                    pass

        if planted_count > 0:
            all_actions.append(f'播种{crop_name}×{planted_count}')

        self._sleep(0.5)
        cv_check = self._capture(rect)
        if cv_check is not None:
            if BTN_SHOP_CLOSE is not None and self.ui.appear(BTN_SHOP_CLOSE, offset=(30, 30), threshold=0.8, static=False):
                self._close_shop_and_buy(rect, crop_name, all_actions)

            if self.ui.appear(BTN_FERTILIZE_POPUP, offset=(30, 30), threshold=0.8, static=False):
                self._click_goto_main(rect)

        return all_actions

    def _close_shop_and_buy(self, rect: tuple[int, int, int, int], crop_name: str, actions_done: list[str]):
        """关闭商店后立刻执行一次补种购买。"""
        self._close_shop(rect)
        buy_result = self._buy_seeds(rect, crop_name)
        if buy_result:
            actions_done.append(buy_result)

    def _buy_seeds(self, rect: tuple[int, int, int, int], crop_name: str) -> str | None:
        """执行买种流程：开商店 -> OCR 定位 -> 选择并确认购买。"""
        if self.engine._is_cancel_requested():
            return None
        cv_img = self._capture(rect)
        if cv_img is None:
            return None

        if BTN_SHOP is None:
            logger.warning('购买流程: 未配置商店按钮模板')
            return None
        if not self.ui.appear_then_click(BTN_SHOP, offset=(30, 30), interval=1, threshold=0.8, static=False):
            logger.warning('购买流程: 未找到商店按钮')
            return None
        self._sleep(1.0)

        shop_cv = None
        for _ in range(5):
            if self.engine._is_cancel_requested():
                return None
            cv_img = self._capture(rect)
            if cv_img is None:
                return None
            if BTN_SHOP_CLOSE is not None and self.ui.appear(BTN_SHOP_CLOSE, offset=(30, 30), threshold=0.8, static=False):
                shop_cv = cv_img
                break
            self._sleep(0.5)
        if shop_cv is None:
            self._close_shop(rect)
            return None

        matched_item = None
        for _ in range(3):
            if self.engine._is_cancel_requested():
                return None
            ocr_match = self.shop_ocr.find_item(shop_cv, crop_name, min_similarity=0.70)
            if ocr_match.target:
                matched_item = ocr_match.target
                break
            self._sleep(0.3)
            cv_img = self._capture(rect)
            if cv_img is None:
                return None
            shop_cv = cv_img

        if not matched_item:
            logger.warning(f"购买流程: OCR未找到 '{crop_name}'")
            self._close_shop(rect)
            return None

        self._click(matched_item.center_x, matched_item.center_y, f'选择{crop_name}')
        self._sleep(1.0)
        return self._confirm_purchase(rect, crop_name)

    def _confirm_purchase(self, rect: tuple[int, int, int, int], crop_name: str) -> str | None:
        """在购买弹窗中执行确认并处理伴随弹窗。"""
        for _ in range(5):
            if self.engine._is_cancel_requested():
                return None
            cv_img = self._capture(rect)
            if cv_img is None:
                return None

            if self.ui.appear_then_click(BTN_BUY_CONFIRM, offset=(30, 30), interval=1, threshold=0.8, static=False):
                self._sleep(0.3)
                self._close_shop(rect)
                return f'购买{crop_name}'

            if self.ui.appear_then_click_any(
                [BTN_CLOSE, BTN_CONFIRM, BTN_CLAIM], offset=(30, 30), interval=1, threshold=0.8, static=False
            ):
                self._sleep(0.2)
                continue

            self._sleep(0.3)

        self._close_shop(rect)
        return None

    def _close_shop(self, rect: tuple[int, int, int, int]):
        """尽可能关闭商店页残留弹窗，回到主流程页面。"""
        for _ in range(3):
            cv_img = self._capture(rect)
            if cv_img is None:
                return
            buttons = [BTN_CLOSE] if BTN_SHOP_CLOSE is None else [BTN_SHOP_CLOSE, BTN_CLOSE]
            if not self.ui.appear_then_click_any(buttons, offset=(30, 30), interval=1, threshold=0.8, static=False):
                return
            self._sleep(0.3)


