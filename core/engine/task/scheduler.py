"""运行态统计与状态管理"""

from __future__ import annotations

import time
from datetime import datetime
from enum import Enum

from PyQt6.QtCore import QObject, pyqtSignal


class BotState(str, Enum):
    """封装 `BotState` 相关的数据与行为。"""

    IDLE = 'idle'
    RUNNING = 'running'
    PAUSED = 'paused'
    ANALYZING = 'analyzing'
    EXECUTING = 'executing'
    WAITING = 'waiting'
    ERROR = 'error'


class TaskScheduler(QObject):
    """只维护运行状态与统计展示，调度由 TaskExecutor 负责。"""

    state_changed = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)

    def __init__(self):
        """初始化对象并准备运行所需状态。"""
        super().__init__()
        self._state = BotState.IDLE
        self._start_time: float = 0.0
        self._stats = {
            'harvest': 0,
            'plant': 0,
            'water': 0,
            'weed': 0,
            'bug': 0,
            'steal': 0,
            'sell': 0,
            'total_actions': 0,
        }
        self._next_farm_check: float = 0.0
        self._next_friend_check: float = 0.0
        self._runtime_metrics = {
            'current_page': '--',
            'current_task': '--',
            'failure_count': 0,
            'running_tasks': 0,
            'pending_tasks': 0,
            'waiting_tasks': 0,
            'last_result': '--',
            'last_tick_ms': '--',
        }

    @property
    def state(self) -> BotState:
        """执行 `state` 相关处理。"""
        return self._state

    def _set_state(self, state: BotState):
        """设置 `state` 参数。"""
        self._state = state
        self.state_changed.emit(state.value)

    def stop(self):
        """停止当前模块并释放运行状态。"""
        self._set_state(BotState.IDLE)
        self.stats_updated.emit(self.get_stats())

    def record_action(self, action_type: str, count: int = 1):
        """执行 `record action` 相关处理。"""
        if action_type in self._stats:
            self._stats[action_type] += count
        self._stats['total_actions'] += count
        self.stats_updated.emit(self.get_stats())

    def get_stats(self) -> dict:
        """获取 `stats` 信息。"""
        elapsed = time.time() - self._start_time if self._start_time else 0
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        return {
            **self._stats,
            **self._runtime_metrics,
            'elapsed': f'{hours}小时{minutes}分',
            'next_farm_check': datetime.fromtimestamp(self._next_farm_check).strftime('%H:%M:%S')
            if self._next_farm_check
            else '--',
            'next_friend_check': datetime.fromtimestamp(self._next_friend_check).strftime('%H:%M:%S')
            if self._next_friend_check
            else '--',
            'state': self._state.value,
        }

    def reset_stats(self):
        """执行 `reset stats` 相关处理。"""
        for key in self._stats:
            self._stats[key] = 0
        self.stats_updated.emit(self.get_stats())

    def force_state(self, state: BotState | str):
        """执行 `force state` 相关处理。"""
        target = state
        if not isinstance(target, BotState):
            try:
                target = BotState(str(state))
            except Exception:
                target = BotState.IDLE
        if target == BotState.RUNNING and not self._start_time:
            self._start_time = time.time()
        self._set_state(target)
        self.stats_updated.emit(self.get_stats())

    def set_next_checks(self, *, farm_ts: float | None = None, friend_ts: float | None = None):
        """设置 `next_checks` 参数。"""
        changed = False
        if farm_ts is not None and self._next_farm_check != farm_ts:
            self._next_farm_check = float(farm_ts)
            changed = True
        if friend_ts is not None and self._next_friend_check != friend_ts:
            self._next_friend_check = float(friend_ts)
            changed = True
        if changed:
            self.stats_updated.emit(self.get_stats())

    def update_runtime_metrics(self, **kwargs):
        """更新 `runtime_metrics` 状态。"""
        changed = False
        for key in (
            'current_page',
            'current_task',
            'failure_count',
            'running_tasks',
            'pending_tasks',
            'waiting_tasks',
            'last_result',
            'last_tick_ms',
        ):
            if key in kwargs and self._runtime_metrics.get(key) != kwargs[key]:
                self._runtime_metrics[key] = kwargs[key]
                changed = True
        if changed:
            self.stats_updated.emit(self.get_stats())
