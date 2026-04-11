"""任务模型与默认任务注册。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.config import AppConfig


@dataclass
class TaskItem:
    """封装 `TaskItem` 任务的执行入口与步骤。"""

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


def build_default_tasks(config: 'AppConfig') -> dict[str, TaskItem]:
    """构建 `default tasks` 结构。"""
    now = datetime.now()
    default_success = max(1, int(config.executor.default_success_interval))
    default_failure = max(1, int(config.executor.default_failure_interval))
    max_failures = max(1, int(config.executor.max_failures))
    tasks_cfg = getattr(config, 'tasks', None)
    if tasks_cfg is None:
        return {}

    if isinstance(tasks_cfg, dict):
        task_names = [str(name) for name in tasks_cfg.keys()]
    else:
        try:
            task_names = [str(name) for name in tasks_cfg.model_dump().keys()]
        except Exception:
            return {}

    out: dict[str, TaskItem] = {}
    for index, task_name in enumerate(task_names, start=1):
        cfg = tasks_cfg.get(task_name) if isinstance(tasks_cfg, dict) else getattr(tasks_cfg, task_name, None)
        if cfg is None:
            continue
        out[task_name] = TaskItem(
            name=task_name,
            enabled=bool(getattr(cfg, 'enabled', True)),
            priority=max(1, int(getattr(cfg, 'priority', index * 10))),
            next_run=now,
            success_interval=max(default_success, int(getattr(cfg, 'interval_seconds', default_success))),
            failure_interval=max(default_failure, int(getattr(cfg, 'failure_interval_seconds', default_failure))),
            max_failures=max_failures,
        )
    return out
