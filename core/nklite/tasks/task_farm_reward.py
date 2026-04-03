"""任务奖励领取。"""

from __future__ import annotations

from core.nklite.base.step_result import StepResult
from core.nklite.ui.assets import TASK_CHECK


class TaskFarmReward:
    def __init__(self, engine, ui):
        self.engine = engine
        self.ui = ui

    def run(self, rect, features) -> StepResult:
        if not features.get('auto_task', True):
            return StepResult()
        if not self.ui.appear_then_click(TASK_CHECK, offset=(30, 30), interval=0.2, threshold=0.8, static=False):
            return StepResult()
        self.engine._sleep_interruptible(0.6)
        out = StepResult.from_value(self.engine.task._handle_task_result(rect))
        return out
