"""收获与维护任务。"""

from __future__ import annotations

from core.base.step_result import StepResult
from core.ui.assets import (
    BTN_BUG,
    BTN_HARVEST,
    BTN_WATER,
    BTN_WEED,
)
from models.farm_state import ActionType


class TaskFarmHarvest:
    """封装 `TaskFarmHarvest` 任务的执行入口与步骤。"""
    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui

    def run(self, features) -> StepResult:
        """执行当前模块主流程并返回结果。"""
        if features.get('auto_harvest', False):
            if self.ui.appear_then_click(BTN_HARVEST, offset=(30, 30), interval=0.2, threshold=0.8, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                return StepResult.from_value('一键收获')

        if features.get('auto_weed', False):
            if self.ui.appear_then_click(BTN_WEED, offset=(30, 30), interval=0.2, threshold=0.8, static=False):
                self.engine._record_stat(ActionType.WEED)
                return StepResult.from_value('一键除草')

        if features.get('auto_bug', False):
            if self.ui.appear_then_click(BTN_BUG, offset=(30, 30), interval=0.2, threshold=0.8, static=False):
                self.engine._record_stat(ActionType.BUG)
                return StepResult.from_value('一键除虫')

        if features.get('auto_water', False):
            if self.ui.appear_then_click(BTN_WATER, offset=(30, 30), interval=0.2, threshold=0.8, static=False):
                self.engine._record_stat(ActionType.WATER)
                return StepResult.from_value('一键浇水')

        return StepResult()


