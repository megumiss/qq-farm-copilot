"""任务模型与默认任务注册。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from models.config import (
    DEFAULT_TASK_ENABLED_TIME_RANGE,
    TaskTriggerType,
)


@dataclass
class TaskItem:
    """封装 `TaskItem` 任务的执行入口与步骤。"""

    name: str
    enabled: bool
    order_index: int
    next_run: datetime
    success_interval: int
    failure_interval: int
    trigger: str = TaskTriggerType.INTERVAL.value
    enabled_time_range: str = DEFAULT_TASK_ENABLED_TIME_RANGE
    failure_count: int = 0


@dataclass
class TaskResult:
    """封装 `TaskResult` 任务的执行入口与步骤。"""

    success: bool
    next_run_seconds: int | None = None
    need_recover: bool = False
    error: str = ''


@dataclass
class TaskSnapshot:
    """封装 `TaskSnapshot` 任务的执行入口与步骤。"""

    running_task: str | None
    pending_tasks: list[TaskItem]
    waiting_tasks: list[TaskItem]


@dataclass
class TaskContext:
    """封装 `TaskContext` 任务的执行入口与步骤。"""

    task_name: str
    started_at: datetime
