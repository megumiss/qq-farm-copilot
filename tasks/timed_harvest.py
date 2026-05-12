"""定时收获任务。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from core.base.timer import Timer
from core.engine.task.registry import TaskResult
from core.ui.assets import BTN_HARVEST, BTN_HARVEST_POP, BTN_MATURE, BTN_WITHERED
from core.ui.page import GOTO_MAIN, page_main
from models.config import normalize_land_maturity_countdown
from models.farm_state import ActionType
from tasks.base import TaskBase

# 聚合窗口附加缓冲秒数：覆盖窗口尾部成熟地块。
TIMED_HARVEST_WINDOW_BUFFER_SECONDS = 3
TIMED_HARVEST_GOTO_MAIN_MIN_INTERVAL_SECONDS = 5.0


class TaskTimedHarvest(TaskBase):
    """按调度在聚合窗口内持续执行一键收获。"""

    @classmethod
    def _collect_maturity_points(cls, plots: list[dict[str, Any]]) -> list[datetime]:
        """收集所有地块成熟绝对时间点。"""
        if not isinstance(plots, list) or not plots:
            return []
        maturity_points: list[datetime] = []
        for item in plots:
            if not isinstance(item, dict):
                continue
            sync_time_text = str(item.get('countdown_sync_time') or '').strip().replace('T', ' ')
            if not sync_time_text:
                continue
            try:
                sync_time = datetime.strptime(sync_time_text, '%Y-%m-%d %H:%M:%S')
            except Exception:
                continue
            countdown = normalize_land_maturity_countdown(item.get('maturity_countdown'))
            if not countdown:
                continue
            hour_str, minute_str, second_str = countdown.split(':')
            seconds = int(hour_str) * 3600 + int(minute_str) * 60 + int(second_str)
            maturity_points.append(sync_time + timedelta(seconds=seconds))
        maturity_points.sort()
        return maturity_points

    @classmethod
    def build_schedule_groups(
        cls,
        plots: list[dict[str, Any]],
        *,
        aggregation_seconds: int,
    ) -> list[tuple[datetime, datetime]]:
        """按聚合时间构建执行分组（组起点, 组终点）。"""
        maturity_points = cls._collect_maturity_points(plots)
        if not maturity_points:
            return []

        window = timedelta(seconds=aggregation_seconds)
        groups: list[tuple[datetime, datetime]] = []
        group_start: datetime | None = None
        group_end: datetime | None = None
        window_end: datetime | None = None

        for point in maturity_points:
            if window_end is None or point > window_end:
                if group_start is not None and group_end is not None:
                    groups.append((group_start, group_end))
                group_start = point
                group_end = point
                window_end = point + window
                continue
            if group_end is None or point > group_end:
                group_end = point

        if group_start is not None and group_end is not None:
            groups.append((group_start, group_end))
        return groups

    @classmethod
    def build_schedule_points(cls, plots: list[dict[str, Any]], *, aggregation_seconds: int) -> list[datetime]:
        """按地块快照构建聚合后的执行时间点。"""
        groups = cls.build_schedule_groups(
            plots,
            aggregation_seconds=aggregation_seconds,
        )
        return [group_start for group_start, _ in groups]

    @staticmethod
    def pick_next_schedule_target(
        schedule_points: list[datetime], *, now: datetime, fallback_to_now_when_all_past: bool
    ) -> datetime | None:
        """从执行点列表中选择下一次目标时间。"""
        if not schedule_points:
            return None
        for point in schedule_points:
            if point >= now:
                return point
        if fallback_to_now_when_all_past:
            return now
        return None

    def _resolve_next_run_seconds(self) -> int | None:
        """计算定时收获任务下次执行秒数。"""
        now = datetime.now()
        aggregation_seconds = self.task.timed_harvest.feature.aggregation_seconds
        schedule_points = self.build_schedule_points(
            self.config.land.plots,
            aggregation_seconds=aggregation_seconds,
        )
        target_time = self.pick_next_schedule_target(
            schedule_points,
            now=now,
            fallback_to_now_when_all_past=False,
        )
        if target_time is None:
            target_time = self.engine._next_daily_target_time(self.task.timed_harvest.daily_times, now)
        if target_time is None:
            return None
        delta_seconds = (target_time - now).total_seconds()
        next_run_seconds = max(1, int(math.ceil(delta_seconds)))
        logger.info(
            '定时收获: 已计算下次执行 | 下次执行={} 执行点数量={} 聚合秒数={}',
            target_time.strftime('%Y-%m-%d %H:%M:%S'),
            len(schedule_points),
            aggregation_seconds,
        )
        return next_run_seconds

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        _ = rect
        if not self.is_task_enabled('land_scan'):
            logger.info('定时收获: 地块巡查未启用，跳过本轮')
            return self.ok()

        self.ui.ui_ensure(page_main)
        aggregation_seconds = self.task.timed_harvest.feature.aggregation_seconds
        now = datetime.now()
        groups = self.build_schedule_groups(
            self.config.land.plots,
            aggregation_seconds=aggregation_seconds,
        )
        active_group: tuple[datetime, datetime] | None = None
        for group_start, group_end in groups:
            if group_end >= now:
                active_group = (group_start, group_end)
                break

        if active_group is not None:
            group_start, group_end = active_group
            deadline = group_end + timedelta(seconds=TIMED_HARVEST_WINDOW_BUFFER_SECONDS)
        else:
            group_start = None
            group_end = None
            deadline = now + timedelta(seconds=TIMED_HARVEST_WINDOW_BUFFER_SECONDS)

        total_window_seconds = max(0, int(math.ceil((deadline - now).total_seconds())))
        action_count = 0
        goto_main_click_timer = Timer(TIMED_HARVEST_GOTO_MAIN_MIN_INTERVAL_SECONDS, count=0)
        withered_action_timer = Timer(TIMED_HARVEST_GOTO_MAIN_MIN_INTERVAL_SECONDS, count=0)
        land_cells = self.collect_land_cells(log_prefix='定时收获')
        land_1_1_center = next(
            ((int(cell.center[0]), int(cell.center[1])) for cell in land_cells if str(cell.label) == '1-1'),
            None,
        )

        logger.info(
            '定时收获: 开始持续收获 | 聚合秒数={} 缓冲秒数={} 窗口秒数={}',
            aggregation_seconds,
            TIMED_HARVEST_WINDOW_BUFFER_SECONDS,
            total_window_seconds,
        )

        while datetime.now() <= deadline:
            self.ui.device.screenshot()
            if self.ui.appear(BTN_HARVEST_POP, offset=100):
                if not goto_main_click_timer.started() or goto_main_click_timer.reached_and_reset():
                    self.ui.device.click_button(GOTO_MAIN)
                    goto_main_click_timer.start()
                continue
            if self.ui.appear(BTN_WITHERED, offset=30, threshold=0.9, static=False):
                if not withered_action_timer.started() or withered_action_timer.reached_and_reset():
                    self.ui.device.click_point(
                        int(land_1_1_center[0]), int(land_1_1_center[1]), desc='定时收获-枯萎处理'
                    )
                    self.ui.device.click_button(GOTO_MAIN)
                    withered_action_timer.start()
                continue
            if self.ui.appear_then_click(BTN_HARVEST, offset=30, interval=0.5, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                action_count += 1
                self.ui.device.click_record_clear()
                continue
            elif self.ui.appear_then_click(BTN_MATURE, offset=30, interval=0.5, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                action_count += 1
                self.ui.device.click_record_clear()
                continue

            now = datetime.now()
            if now >= deadline:
                break

        logger.info(
            '定时收获: 执行完成 | 动作次数={} 窗口秒数={}',
            action_count,
            total_window_seconds,
        )
        if action_count > 0:
            queued = bool(self.task.main.call(force_call=False))
            if queued:
                logger.info('定时收获: 已成功收获，发起一次主任务')
        return self.ok(next_run_seconds=self._resolve_next_run_seconds())
