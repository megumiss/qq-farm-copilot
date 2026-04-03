"""任务调度器 - 管理自动化任务的执行周期"""
import time
from datetime import datetime
from enum import Enum
from loguru import logger

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class BotState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ANALYZING = "analyzing"
    EXECUTING = "executing"
    WAITING = "waiting"
    ERROR = "error"


class TaskScheduler(QObject):
    """基于QTimer的任务调度器，与Qt事件循环集成"""

    state_changed = pyqtSignal(str)  # 状态变化信号
    farm_check_triggered = pyqtSignal()  # 农场检查触发
    friend_check_triggered = pyqtSignal()  # 好友检查触发
    stats_updated = pyqtSignal(dict)  # 统计数据更新

    def __init__(self):
        super().__init__()
        self._state = BotState.IDLE
        self._farm_timer = QTimer(self)
        self._friend_timer = QTimer(self)
        self._farm_timer.timeout.connect(self._on_farm_timer)
        self._friend_timer.timeout.connect(self._on_friend_timer)

        # 统计
        self._start_time: float = 0
        self._stats = {
            "harvest": 0, "plant": 0, "water": 0,
            "weed": 0, "bug": 0, "steal": 0,
            "sell": 0, "total_actions": 0,
        }
        self._next_farm_check: float = 0
        self._next_friend_check: float = 0
        self._runtime_metrics = {
            "current_page": "--",
            "current_task": "--",
            "failure_count": 0,
            "running_tasks": 0,
            "pending_tasks": 0,
            "waiting_tasks": 0,
            "last_result": "--",
            "last_tick_ms": "--",
        }

    @property
    def state(self) -> BotState:
        return self._state

    def _set_state(self, state: BotState):
        self._state = state
        self.state_changed.emit(state.value)

    def start(self, farm_interval_ms: int = 300000,
              friend_interval_ms: int = 1800000):
        """启动调度器"""
        if self._state == BotState.RUNNING:
            return
        self._start_time = time.time()
        self._set_state(BotState.RUNNING)

        # 立即执行一次农场检查
        self._farm_timer.start(farm_interval_ms)
        self._friend_timer.start(friend_interval_ms)
        self._next_farm_check = time.time()
        self._next_friend_check = time.time() + friend_interval_ms / 1000

        # 首次立即触发
        QTimer.singleShot(500, self._on_farm_timer)
        logger.info(f"调度器已启动 (农场:{farm_interval_ms//1000}s, 好友:{friend_interval_ms//1000}s)")

    def stop(self):
        """停止调度器"""
        self._farm_timer.stop()
        self._friend_timer.stop()
        self._set_state(BotState.IDLE)
        logger.info("调度器已停止")

    def pause(self):
        """暂停"""
        if self._state == BotState.RUNNING:
            self._farm_timer.stop()
            self._friend_timer.stop()
            self._set_state(BotState.PAUSED)
            logger.info("调度器已暂停")

    def resume(self):
        """恢复"""
        if self._state == BotState.PAUSED:
            self._farm_timer.start()
            self._friend_timer.start()
            self._set_state(BotState.RUNNING)
            logger.info("调度器已恢复")

    def run_once(self):
        """手动触发一次农场检查"""
        logger.info("手动触发农场检查")
        self.farm_check_triggered.emit()

    def set_farm_interval(self, seconds: int):
        """动态调整农场检查间隔（秒）"""
        ms = max(3000, seconds * 1000)
        self._farm_timer.setInterval(ms)
        self._next_farm_check = time.time() + seconds
        if seconds >= 60:
            logger.info(f"农场检查间隔调整为 {seconds // 60}分{seconds % 60}秒")
        else:
            logger.info(f"农场检查间隔调整为 {seconds}秒")

    def _on_farm_timer(self):
        if self._state not in (BotState.RUNNING,):
            return
        self._next_farm_check = time.time() + self._farm_timer.interval() / 1000
        self.farm_check_triggered.emit()

    def _on_friend_timer(self):
        if self._state not in (BotState.RUNNING,):
            return
        self._next_friend_check = time.time() + self._friend_timer.interval() / 1000
        self.friend_check_triggered.emit()

    def record_action(self, action_type: str, count: int = 1):
        """记录操作统计"""
        if action_type in self._stats:
            self._stats[action_type] += count
        self._stats["total_actions"] += count
        self.stats_updated.emit(self.get_stats())

    def get_stats(self) -> dict:
        """获取统计数据"""
        elapsed = time.time() - self._start_time if self._start_time else 0
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        return {
            **self._stats,
            **self._runtime_metrics,
            "elapsed": f"{hours}小时{minutes}分",
            "next_farm_check": datetime.fromtimestamp(self._next_farm_check).strftime("%H:%M:%S") if self._next_farm_check else "--",
            "next_friend_check": datetime.fromtimestamp(self._next_friend_check).strftime("%H:%M:%S") if self._next_friend_check else "--",
            "state": self._state.value,
        }

    def reset_stats(self):
        for key in self._stats:
            self._stats[key] = 0

    def force_state(self, state: BotState | str):
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
        changed = False
        for key in (
            "current_page", "current_task", "failure_count",
            "running_tasks", "pending_tasks", "waiting_tasks",
            "last_result", "last_tick_ms",
        ):
            if key in kwargs and self._runtime_metrics.get(key) != kwargs[key]:
                self._runtime_metrics[key] = kwargs[key]
                changed = True
        if changed:
            self.stats_updated.emit(self.get_stats())
