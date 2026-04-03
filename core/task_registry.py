"""任务模型与默认任务注册。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.config import AppConfig


@dataclass
class TaskItem:
    name: str
    enabled: bool
    priority: int
    next_run: datetime
    success_interval: int
    failure_interval: int
    max_failures: int = 3
    failure_count: int = 0


@dataclass
class TaskResult:
    success: bool
    actions: list[str] = field(default_factory=list)
    next_run_seconds: int | None = None
    need_recover: bool = False
    error: str = ''

    @classmethod
    def from_legacy_dict(cls, payload: dict) -> 'TaskResult':
        return cls(
            success=bool(payload.get('success', False)),
            actions=list(payload.get('actions_done', [])),
            next_run_seconds=payload.get('next_check_seconds'),
            need_recover=bool(payload.get('need_recover', False)),
            error=str(payload.get('message', '')),
        )


@dataclass
class TaskSnapshot:
    running_task: str | None
    pending_tasks: list[TaskItem]
    waiting_tasks: list[TaskItem]


@dataclass
class TaskContext:
    task_name: str
    started_at: datetime


def build_default_tasks(config: 'AppConfig') -> dict[str, TaskItem]:
    now = datetime.now()
    friend_enabled = bool(config.features.auto_help or config.features.auto_steal)
    default_success = max(1, int(config.executor.default_success_interval))
    default_failure = max(1, int(config.executor.default_failure_interval))
    max_failures = max(1, int(config.executor.max_failures))
    return {
        'farm_main': TaskItem(
            name='farm_main',
            enabled=True,
            priority=10,
            next_run=now,
            success_interval=max(default_success, int(config.schedule.farm_check_minutes) * 60),
            failure_interval=default_failure,
            max_failures=max_failures,
        ),
        'friend': TaskItem(
            name='friend',
            enabled=friend_enabled,
            priority=50,
            next_run=now + timedelta(minutes=max(1, int(config.schedule.friend_check_minutes))),
            success_interval=max(default_success, int(config.schedule.friend_check_minutes) * 60),
            failure_interval=max(default_failure, 60),
            max_failures=max_failures,
        ),
    }
