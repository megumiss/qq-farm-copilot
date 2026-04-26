"""任务模型与默认任务注册。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from models.config import (
    DEFAULT_TASK_ENABLED_TIME_RANGE,
    TaskTriggerType,
    normalize_task_enabled_time_range,
    parse_executor_task_order,
    resolve_task_min_interval_seconds,
)

if TYPE_CHECKING:
    from models.config import AppConfig


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


def build_default_tasks(config: 'AppConfig') -> dict[str, TaskItem]:
    """构建 `default tasks` 结构。"""
    now = datetime.now()
    min_interval = resolve_task_min_interval_seconds(config.executor)
    default_success = max(min_interval, int(config.executor.default_success_interval))
    default_failure = max(min_interval, int(config.executor.default_failure_interval))
    tasks_cfg = getattr(config, 'tasks', None)
    if tasks_cfg is None:
        return {}

    if isinstance(tasks_cfg, dict):
        config_names = [str(name) for name in tasks_cfg.keys()]
    else:
        try:
            config_names = [str(name) for name in tasks_cfg.model_dump().keys()]
        except Exception:
            return {}

    known_names = set(config_names)
    task_names: list[str] = []
    seen: set[str] = set()
    for task_name in parse_executor_task_order(getattr(config.executor, 'task_order', '')):
        name = str(task_name)
        if not name or name in seen or name not in known_names:
            continue
        seen.add(name)
        task_names.append(name)
    for task_name in config_names:
        name = str(task_name)
        if not name or name in seen:
            continue
        seen.add(name)
        task_names.append(name)

    out: dict[str, TaskItem] = {}
    for index, task_name in enumerate(task_names, start=1):
        cfg = tasks_cfg.get(task_name) if isinstance(tasks_cfg, dict) else getattr(tasks_cfg, task_name, None)
        if cfg is None:
            continue
        trigger_cfg = getattr(cfg, 'trigger', TaskTriggerType.INTERVAL)
        trigger_text = trigger_cfg.value if isinstance(trigger_cfg, TaskTriggerType) else str(trigger_cfg)
        out[task_name] = TaskItem(
            name=task_name,
            enabled=bool(getattr(cfg, 'enabled', True)),
            order_index=index,
            next_run=now,
            success_interval=max(
                min_interval,
                int(getattr(cfg, 'interval_seconds', default_success)),
            ),
            failure_interval=max(
                min_interval,
                int(getattr(cfg, 'failure_interval_seconds', default_failure)),
            ),
            trigger=trigger_text,
            enabled_time_range=normalize_task_enabled_time_range(
                getattr(cfg, 'enabled_time_range', DEFAULT_TASK_ENABLED_TIME_RANGE)
            ),
        )
    return out
