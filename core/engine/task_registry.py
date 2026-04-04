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
    default_success = max(1, int(config.executor.default_success_interval))
    default_failure = max(1, int(config.executor.default_failure_interval))
    max_failures = max(1, int(config.executor.max_failures))
    farm_cfg = config.tasks.farm_main
    friend_cfg = config.tasks.friend
    share_cfg = config.tasks.share

    farm_enabled = bool(farm_cfg.enabled)
    friend_enabled = bool(friend_cfg.enabled)
    share_enabled = bool(share_cfg.enabled)

    farm_success = max(default_success, int(farm_cfg.interval_seconds))
    friend_success = max(default_success, int(friend_cfg.interval_seconds))
    share_success = max(default_success, int(share_cfg.interval_seconds))
    return {
        'farm_main': TaskItem(
            name='farm_main',
            enabled=farm_enabled,
            priority=10,
            next_run=now,
            success_interval=farm_success,
            failure_interval=max(default_failure, int(farm_cfg.failure_interval_seconds)),
            max_failures=max_failures,
        ),
        'friend': TaskItem(
            name='friend',
            enabled=friend_enabled,
            priority=50,
            next_run=now + timedelta(seconds=max(1, int(friend_cfg.interval_seconds))),
            success_interval=friend_success,
            failure_interval=max(default_failure, int(friend_cfg.failure_interval_seconds)),
            max_failures=max_failures,
        ),
        'share': TaskItem(
            name='share',
            enabled=share_enabled,
            priority=80,
            next_run=now,
            success_interval=share_success,
            failure_interval=max(default_failure, int(share_cfg.failure_interval_seconds)),
            max_failures=max_failures,
        ),
    }
