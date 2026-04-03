"""P3.2 出售 — 独立仓库批量出售"""
from loguru import logger

from models.farm_state import ActionType
from core.strategies.base import BaseStrategy, StrategyResult


class SellStrategy(BaseStrategy):
    requires_page = {"main"}
    expected_page_after = {"main", "popup", "shop"}

    def try_sell(self, rect: tuple, detections: list) -> list[str]:
        """在农场主页尝试进入仓库并批量出售。"""
        warehouse = self.find_by_name(detections, "btn_warehouse")
        if not warehouse:
            return []

        if not self.click(warehouse.x, warehouse.y, "打开仓库"):
            return []
        self.sleep(0.8)
        return self._batch_sell(rect)

    def _batch_sell(self, rect: tuple) -> list[str]:
        """批量出售：点击批量出售，随后确认出售。"""
        for _ in range(5):
            if self.stopped:
                return []
            cv_img, _, _ = self.capture(rect)
            if cv_img is None:
                return []

            batch_btn = self.cv_detector.detect_single_template(
                cv_img, "btn_batch_sell", threshold=0.8
            )
            if batch_btn:
                self.click(batch_btn[0].x, batch_btn[0].y, "批量出售")
                self.sleep(0.5)
                break
            self.sleep(0.3)
        else:
            self._close_page(rect)
            return []

        for _ in range(3):
            if self.stopped:
                return []
            cv_img, _, _ = self.capture(rect)
            if cv_img is None:
                return []

            confirm = self.cv_detector.detect_single_template(
                cv_img, "btn_confirm", threshold=0.8
            )
            if confirm:
                self.click(confirm[0].x, confirm[0].y, "确认出售", ActionType.SELL)
                logger.info("出售: 批量出售完成")
                self.sleep(0.5)
                self._close_page(rect)
                return ["批量出售果实"]
            self.sleep(0.3)

        self._close_page(rect)
        return []

    def _close_page(self, rect: tuple):
        cv_img, dets, _ = self.capture(rect)
        if cv_img is None:
            return
        close = self.find_any(dets, ["btn_close", "btn_shop_close"])
        if close:
            self.click(close.x, close.y, "关闭页面", ActionType.CLOSE_POPUP)
            self.sleep(0.3)

    def run_once(self, rect: tuple, detections: list, **_kwargs) -> StrategyResult:
        return StrategyResult.from_value(self.try_sell(rect, detections))

