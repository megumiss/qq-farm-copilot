"""P1 维护 — 一键除草/除虫/浇水"""
from models.farm_state import ActionType
from core.cv_detector import DetectResult
from core.strategies.base import BaseStrategy, StrategyResult


class MaintainStrategy(BaseStrategy):
    requires_page = {"main"}
    expected_page_after = {"main"}

    def try_maintain(self, detections: list[DetectResult],
                     features: dict) -> str | None:
        """按优先级检测并点击一键维护按钮：除草 > 除虫 > 浇水"""
        buttons = [
            ("btn_weed", "一键除草", "auto_weed", ActionType.WEED),
            ("btn_bug", "一键除虫", "auto_bug", ActionType.BUG),
            ("btn_water", "一键浇水", "auto_water", ActionType.WATER),
        ]
        for btn_name, desc, feature_key, action_type in buttons:
            if not features.get(feature_key, True):
                continue
            btn = self.find_by_name(detections, btn_name)
            if btn:
                self.click(btn.x, btn.y, desc, action_type)
                return desc
        return None

    def run_once(self, detections: list[DetectResult], features: dict, **_kwargs) -> StrategyResult:
        return StrategyResult.from_value(self.try_maintain(detections, features))
