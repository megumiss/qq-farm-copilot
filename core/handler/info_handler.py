"""nklite 全局弹窗/异常处理。"""

from __future__ import annotations

import pyautogui

from core.base.module_base import ModuleBase
from core.ui.assets import ASSET_NAME_TO_CONST, BTN_CLAIM, BTN_CLOSE, BTN_CONFIRM

ICON_LEVELUP = ASSET_NAME_TO_CONST.get('icon_levelup')
BTN_SHARE = ASSET_NAME_TO_CONST.get('btn_share')
BTN_SHOP_CLOSE = ASSET_NAME_TO_CONST.get('btn_shop_close')


class InfoHandler(ModuleBase):
    """封装 `InfoHandler` 相关的数据与行为。"""

    @staticmethod
    def _available_buttons(buttons):
        """过滤 assets 中存在的按钮定义。"""
        return [button for button in buttons if button is not None]

    def handle_level_up(self):
        """执行 `handle level up` 相关处理。"""
        if ICON_LEVELUP is None:
            return False
        if not self.appear(ICON_LEVELUP, offset=(30, 30), threshold=0.76, static=False):
            return False
        buttons = self._available_buttons([BTN_SHARE, BTN_CLAIM, BTN_CONFIRM, BTN_CLOSE])
        if not buttons:
            return False
        return self.appear_then_click_any(
            buttons,
            offset=(30, 30),
            interval=1,
            threshold=0.8,
            static=False,
        )

    def handle_share_reward(self):
        """执行 `handle share reward` 相关处理。"""
        if BTN_SHARE is None:
            return False
        if not self.appear(BTN_SHARE, offset=(30, 30), threshold=0.8, static=False):
            return False
        if not self.device.click(BTN_SHARE):
            return False
        self.device.sleep(2.0)
        pyautogui.press('escape')
        self.device.sleep(1.0)
        return True

    def handle_reward(self, interval=1):
        """执行 `handle reward` 相关处理。"""
        if self.handle_share_reward():
            return True
        buttons = self._available_buttons([BTN_CLAIM, BTN_CONFIRM])
        if not buttons:
            return False
        return self.appear_then_click_any(
            buttons,
            offset=(30, 30),
            interval=interval,
            threshold=0.8,
            static=False,
        )

    def handle_announcement(self):
        """执行 `handle announcement` 相关处理。"""
        if BTN_CLOSE is None:
            return False
        return self.appear_then_click(BTN_CLOSE, offset=(30, 30), interval=1, threshold=0.8, static=False)

    def handle_login_reward(self):
        """执行 `handle login reward` 相关处理。"""
        return False

    def handle_system_error(self):
        """执行 `handle system error` 相关处理。"""
        return False

    def handle_shop_residual(self):
        """执行 `handle shop residual` 相关处理。"""
        if BTN_SHOP_CLOSE is None:
            return False
        return self.appear_then_click(BTN_SHOP_CLOSE, offset=(30, 30), interval=1, threshold=0.8, static=False)
