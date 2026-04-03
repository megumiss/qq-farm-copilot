"""P0 收益 — 一键收获"""
from models.farm_state import ActionType
from core.cv_detector import DetectResult
from core.strategies.base import BaseStrategy, StrategyResult


class HarvestStrategy(BaseStrategy):
    requires_page = {"main"}
    expected_page_after = {"main"}

    def try_harvest(self, detections: list[DetectResult]) -> str | None:
        """检测并点击一键收获按钮"""
        btn = self.find_by_name(detections, "btn_harvest")
        if btn:
            self.click(btn.x, btn.y, "一键收获", ActionType.HARVEST)
            return "一键收获"
        return None

    def run_once(self, detections: list[DetectResult], **_kwargs) -> StrategyResult:
        return StrategyResult.from_value(self.try_harvest(detections))
