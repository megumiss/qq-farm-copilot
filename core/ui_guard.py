"""全局 UI Guard：统一处理可恢复弹窗与异常页面。"""
from __future__ import annotations

from core.scene_detector import Scene


class UIGuard:
    def __init__(self, popup_strategy, navigator=None, on_level_up=None):
        self.popup = popup_strategy
        self.navigator = navigator
        self.on_level_up = on_level_up

    def handle_global_popups(
        self,
        rect: tuple,
        scene: Scene,
        detections: list,
    ) -> str | None:
        """返回处理动作描述，未处理返回 None。"""
        if scene in (Scene.POPUP, Scene.BUY_CONFIRM):
            return self.popup.handle_popup(detections)

        if scene == Scene.LEVEL_UP:
            out = self.popup.handle_popup(detections)
            if callable(self.on_level_up):
                try:
                    self.on_level_up()
                except Exception:
                    pass
            return out

        if scene == Scene.SHOP_PAGE:
            self.popup.close_shop(rect)
            return "关闭商店"

        return None
