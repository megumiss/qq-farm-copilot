"""独立分享任务。"""

from __future__ import annotations

from core.engine.task.registry import TaskResult
from core.ui.page import page_main
from tasks.base import TaskBase
from tasks.reward import TaskReward


class TaskShare(TaskBase):
    """封装 `TaskShare` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)
        self._reward = TaskReward(engine=engine, ui=ui)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行分享任务并返回调度结果。"""
        self.engine._clear_screen(rect)
        self.ui.ui_ensure(page_main, confirm_wait=0.5)

        self._reward.run(rect=rect, features=self.get_features('share'))
        return self.ok()
