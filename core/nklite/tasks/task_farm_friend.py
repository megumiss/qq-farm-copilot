"""好友求助任务。"""

from __future__ import annotations

from core.nklite.base.step_result import StepResult
from core.nklite.ui.assets import BTN_FRIEND_HELP


class TaskFarmFriend:
    def __init__(self, engine, ui):
        self.engine = engine
        self.ui = ui

    def run(self, rect, features) -> StepResult:
        if not features.get('auto_help', True):
            return StepResult()
        if not self.ui.appear_then_click(BTN_FRIEND_HELP, offset=(30, 30), interval=0.2, threshold=0.8, static=False):
            return StepResult()
        self.engine._sleep_interruptible(0.4)
        out = StepResult.from_value(self.engine.friend._help_in_friend_farm(rect))
        return out
