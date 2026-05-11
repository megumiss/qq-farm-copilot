"""定时收获任务。"""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger

from core.engine.task.registry import TaskResult
from core.ui.assets import BTN_HARVEST, BTN_MATURE
from core.ui.page import page_main
from models.farm_state import ActionType
from tasks.base import TaskBase

# 聚合窗口附加缓冲秒数：覆盖窗口尾部成熟地块。
TIMED_HARVEST_WINDOW_BUFFER_SECONDS = 3
# 持续收获循环轮询间隔（秒）。
TIMED_HARVEST_LOOP_IDLE_SLEEP_SECONDS = 0.25
TIMED_HARVEST_LOOP_ACTIVE_SLEEP_SECONDS = 0.12


class TaskTimedHarvest(TaskBase):
    """按调度在聚合窗口内持续执行一键收获。"""

    def _aggregation_seconds(self) -> int:
        """读取定时收获聚合时间。"""
        try:
            seconds = int(self.task.timed_harvest.feature.aggregation_seconds)
        except Exception:
            seconds = 60
        return max(1, seconds)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        _ = rect
        if not self.is_task_enabled('land_scan'):
            logger.info('定时收获: 地块巡查未启用，跳过本轮')
            return self.ok()

        self.ui.ui_ensure(page_main)
        aggregation_seconds = self._aggregation_seconds()
        total_window_seconds = aggregation_seconds + int(TIMED_HARVEST_WINDOW_BUFFER_SECONDS)
        deadline = datetime.now() + timedelta(seconds=total_window_seconds)
        action_count = 0

        logger.info(
            '定时收获: 开始持续收获 | aggregation_seconds={} buffer_seconds={} window_seconds={}',
            aggregation_seconds,
            TIMED_HARVEST_WINDOW_BUFFER_SECONDS,
            total_window_seconds,
        )

        while datetime.now() <= deadline:
            self.ui.device.screenshot()
            clicked = False
            if self.ui.appear_then_click(BTN_HARVEST, offset=30, interval=1, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                action_count += 1
                clicked = True
            elif self.ui.appear_then_click(BTN_MATURE, offset=30, interval=1, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                action_count += 1
                clicked = True

            now = datetime.now()
            if now >= deadline:
                break
            idle_sleep_seconds = (
                TIMED_HARVEST_LOOP_ACTIVE_SLEEP_SECONDS if clicked else TIMED_HARVEST_LOOP_IDLE_SLEEP_SECONDS
            )
            sleep_seconds = min(float(idle_sleep_seconds), max(0.0, (deadline - now).total_seconds()))
            if sleep_seconds > 0:
                self.ui.device.sleep(sleep_seconds)

        logger.info(
            '定时收获: 执行完成 | action_count={} window_seconds={}',
            action_count,
            total_window_seconds,
        )
        return self.ok()
