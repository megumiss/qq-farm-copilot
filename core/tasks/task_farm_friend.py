"""好友求助任务。"""

from __future__ import annotations

from core.base.step_result import StepResult
from core.ui.assets import BTN_FRIEND_HELP


class TaskFarmFriend:
    """封装 `TaskFarmFriend` 任务的执行入口与步骤。"""
    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui

    def run(self, rect, features) -> StepResult:
        """执行当前模块主流程并返回结果。"""
        if not features.get('auto_help', False):
            return StepResult()
        if not self.ui.appear_then_click(BTN_FRIEND_HELP, offset=(30, 30), interval=0.2, threshold=0.8, static=False):
            return StepResult()
        self.engine._sleep_interruptible(0.4)
        out = StepResult.from_value(self.engine.friend._help_in_friend_farm(rect))
        return out


