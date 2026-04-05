"""独立好友任务。"""

from __future__ import annotations

from core.engine.task.registry import TaskResult
from core.tasks.farm_friend import TaskFarmFriend
from core.ui.page import page_main


class TaskFriend:
    """封装 `TaskFriend` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui
        self._friend = TaskFarmFriend(engine=engine, ui=ui)

    def run(self, session_id: int | None = None) -> TaskResult:
        """执行好友任务并返回调度结果。"""
        next_seconds = max(1, int(self.engine._task_seconds_by_trigger('friend')))
        if self.engine._is_cancel_requested(session_id):
            return TaskResult(success=False, actions=[], next_run_seconds=next_seconds, error='停止中')
        if not self.ui:
            return TaskResult(success=False, actions=[], next_run_seconds=next_seconds, error='UI未初始化')

        rect = self.engine._prepare_window()
        if not rect:
            return TaskResult(success=False, actions=[], next_run_seconds=next_seconds, error='窗口未找到')
        if self.engine.nk_device:
            self.engine.nk_device.set_rect(rect)

        self.engine._clear_screen(rect, session_id)
        self.ui.ui_ensure(page_main, confirm_wait=0.5)

        out = self._friend.run(rect=rect, features=self.engine.get_task_features('friend'))
        return TaskResult(success=True, actions=list(out.actions), next_run_seconds=next_seconds, error='')
