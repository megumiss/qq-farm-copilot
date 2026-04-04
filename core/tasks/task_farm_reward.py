"""任务奖励领取。"""

from __future__ import annotations

from core.base.step_result import StepResult
from core.ui.assets import TASK_CHECK


class TaskFarmReward:
    """封装 `TaskFarmReward` 任务的执行入口与步骤。"""
    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui

    def run(self, rect, features) -> StepResult:
        """执行当前模块主流程并返回结果。"""
        if not features.get('auto_task', False):
            return StepResult()
        if not self.ui.appear_then_click(TASK_CHECK, offset=(30, 30), interval=0.2, threshold=0.8, static=False):
            return StepResult()
        self.engine._sleep_interruptible(0.6)
        out = StepResult.from_value(self.engine.task._handle_task_result(rect))
        return out


