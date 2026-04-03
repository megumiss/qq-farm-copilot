"""nklite 全局弹窗/异常处理。"""

from __future__ import annotations

import pyautogui

from core.nklite.base.button import Button
from core.nklite.base.module_base import ModuleBase


def _btn(name: str, area: tuple[int, int, int, int]):
    return Button(
        area=area,
        color=(128, 128, 128),
        button=area,
        file=f'templates/btn/{name}.png',
        name=name,
    )


ICON_LEVELUP = Button(
    area=(81, 96, 459, 576),
    color=(128, 128, 128),
    button=(260, 840, 300, 900),
    file='templates/icon/icon_levelup.png',
    name='icon_levelup',
)
BTN_SHARE = _btn('btn_share', (43, 173, 497, 941))
BTN_CLAIM = _btn('btn_claim', (43, 173, 497, 941))
BTN_CONFIRM = _btn('btn_confirm', (43, 173, 497, 941))
BTN_CLOSE = _btn('btn_close', (43, 173, 497, 941))
BTN_SHOP_CLOSE = _btn('btn_shop_close', (297, 0, 540, 336))


class InfoHandler(ModuleBase):
    def handle_level_up(self):
        if not self.appear(ICON_LEVELUP, offset=(30, 30), threshold=0.76, static=False):
            return False
        return self.appear_then_click_any(
            [BTN_SHARE, BTN_CLAIM, BTN_CONFIRM, BTN_CLOSE],
            offset=(30, 30),
            interval=0.2,
            threshold=0.8,
            static=False,
        )

    def handle_share_reward(self):
        if not self.appear(BTN_SHARE, offset=(30, 30), threshold=0.8, static=False):
            return False
        if not self.device.click(BTN_SHARE):
            return False
        self.device.sleep(2.0)
        pyautogui.press('escape')
        self.device.sleep(1.0)
        return True

    def handle_reward(self, interval=0.2):
        if self.handle_share_reward():
            return True
        return self.appear_then_click_any(
            [BTN_CLAIM, BTN_CONFIRM],
            offset=(30, 30),
            interval=interval,
            threshold=0.8,
            static=False,
        )

    def handle_announcement(self):
        return self.appear_then_click(BTN_CLOSE, offset=(30, 30), interval=0.2, threshold=0.8, static=False)

    def handle_login_reward(self):
        return False

    def handle_system_error(self):
        return False

    def handle_shop_residual(self):
        return self.appear_then_click(BTN_SHOP_CLOSE, offset=(30, 30), interval=0.2, threshold=0.8, static=False)
