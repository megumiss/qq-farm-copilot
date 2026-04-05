"""独立分享任务。"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.engine.task.registry import TaskResult
from core.tasks.farm_reward import TaskFarmReward
from core.ui.page import page_main


class TaskShare:
    """封装 `TaskShare` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui
        self._reward = TaskFarmReward(engine=engine, ui=ui)

    @staticmethod
    def _seconds_to_next_daily(daily_time: str, now: datetime | None = None) -> int:
        """计算距离下一次每日触发时间的秒数。"""
        current = now or datetime.now()
        text = str(daily_time or '04:00')
        try:
            hour = int(text[:2])
            minute = int(text[3:5])
        except Exception:
            hour, minute = 4, 0
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= current:
            target = target + timedelta(days=1)
        return max(1, int((target - current).total_seconds()))

    def run(self, session_id: int | None = None) -> TaskResult:
        """执行分享任务并返回调度结果。"""
        next_seconds = max(1, int(self.engine._task_seconds_by_trigger('share')))

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

        out = self._reward.run(rect=rect, features=self.engine.get_task_features('share'))
        return TaskResult(success=True, actions=list(out.actions), next_run_seconds=next_seconds, error='')
