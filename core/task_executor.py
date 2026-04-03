"""统一任务执行器（pending/waiting 队列 + task_delay/task_call）。"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable

from loguru import logger

from core.task_registry import TaskContext, TaskItem, TaskResult, TaskSnapshot

TaskRunner = Callable[[TaskContext], TaskResult]
SnapshotHook = Callable[[TaskSnapshot], None]
TaskDoneHook = Callable[[str, TaskResult], None]
IdleHook = Callable[[], None]


class TaskExecutor:
    def __init__(
        self,
        tasks: dict[str, TaskItem],
        runners: dict[str, TaskRunner],
        *,
        empty_queue_policy: str = 'stay',
        on_snapshot: SnapshotHook | None = None,
        on_task_done: TaskDoneHook | None = None,
        on_idle: IdleHook | None = None,
    ):
        self._tasks = tasks
        self._runners = runners
        self._empty_queue_policy = str(empty_queue_policy or 'stay')
        self._on_snapshot = on_snapshot
        self._on_task_done = on_task_done
        self._on_idle = on_idle

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running_task: str | None = None
        self._last_idle_at = 0.0

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._pause_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name='TaskExecutorLoop',
                daemon=True,
            )
            self._thread.start()

    def stop(self, wait_timeout: float = 1.0):
        self._stop_event.set()
        self._pause_event.clear()
        th = self._thread
        if th and th.is_alive():
            th.join(timeout=max(0.1, float(wait_timeout)))

    def pause(self):
        self._pause_event.set()

    def resume(self):
        self._pause_event.clear()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def set_empty_queue_policy(self, policy: str):
        with self._lock:
            self._empty_queue_policy = str(policy or 'stay')

    def update_task(self, name: str, **kwargs):
        with self._lock:
            task = self._tasks.get(name)
            if not task:
                return
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)

    def snapshot(self, now: datetime | None = None) -> TaskSnapshot:
        with self._lock:
            return self._snapshot_locked(now or datetime.now())

    def task_delay(
        self,
        task: str,
        *,
        seconds: int | None = None,
        target_time: datetime | None = None,
    ) -> bool:
        with self._lock:
            item = self._tasks.get(task)
            if not item:
                return False
            run_candidates: list[datetime] = []
            if seconds is not None:
                run_candidates.append(datetime.now() + timedelta(seconds=max(0, int(seconds))))
            if target_time is not None:
                run_candidates.append(target_time)
            if not run_candidates:
                return False
            item.next_run = min(run_candidates)
            return True

    def task_call(self, task: str, force_call: bool = True) -> bool:
        with self._lock:
            item = self._tasks.get(task)
            if not item:
                return False
            if not item.enabled and not force_call:
                return False
            item.enabled = True
            item.next_run = datetime.now()
            return True

    def _snapshot_locked(self, now: datetime) -> TaskSnapshot:
        pending: list[TaskItem] = []
        waiting: list[TaskItem] = []
        for task in self._tasks.values():
            if not task.enabled:
                continue
            if task.next_run <= now:
                pending.append(task)
            else:
                waiting.append(task)
        pending.sort(key=lambda t: (t.priority, t.next_run))
        waiting.sort(key=lambda t: t.next_run)
        return TaskSnapshot(
            running_task=self._running_task,
            pending_tasks=[self._clone_item(t) for t in pending],
            waiting_tasks=[self._clone_item(t) for t in waiting],
        )

    @staticmethod
    def _clone_item(item: TaskItem) -> TaskItem:
        return TaskItem(
            name=item.name,
            enabled=item.enabled,
            priority=item.priority,
            next_run=item.next_run,
            success_interval=item.success_interval,
            failure_interval=item.failure_interval,
            max_failures=item.max_failures,
            failure_count=item.failure_count,
        )

    def _emit_snapshot(self):
        if not self._on_snapshot:
            return
        try:
            self._on_snapshot(self.snapshot())
        except Exception as exc:
            logger.debug(f'snapshot hook error: {exc}')

    def _apply_task_result(self, task: TaskItem, result: TaskResult):
        now = datetime.now()
        if result.success:
            task.failure_count = 0
            interval = (
                int(result.next_run_seconds) if result.next_run_seconds is not None else int(task.success_interval)
            )
        else:
            task.failure_count += 1
            interval = (
                int(result.next_run_seconds) if result.next_run_seconds is not None else int(task.failure_interval)
            )
            if task.failure_count >= max(1, int(task.max_failures)):
                interval = max(interval, int(task.failure_interval) * 3)

        task.next_run = now + timedelta(seconds=max(1, interval))

    def _loop(self):
        self._emit_snapshot()
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(0.08)
                continue

            now = datetime.now()
            with self._lock:
                snap = self._snapshot_locked(now)
                task = snap.pending_tasks[0] if snap.pending_tasks else None
                if task:
                    self._running_task = task.name
                else:
                    self._running_task = None

            self._emit_snapshot()

            if not task:
                if self._empty_queue_policy == 'goto_main' and self._on_idle and time.time() - self._last_idle_at > 2.0:
                    self._last_idle_at = time.time()
                    try:
                        self._on_idle()
                    except Exception as exc:
                        logger.debug(f'idle hook error: {exc}')
                time.sleep(0.12)
                continue

            runner = self._runners.get(task.name)
            if not runner:
                with self._lock:
                    item = self._tasks.get(task.name)
                    if item:
                        self._apply_task_result(
                            item,
                            TaskResult(
                                success=False,
                                error=f'missing runner: {task.name}',
                            ),
                        )
                        self._running_task = None
                self._emit_snapshot()
                continue

            try:
                result = runner(TaskContext(task_name=task.name, started_at=datetime.now()))
                if not isinstance(result, TaskResult):
                    result = TaskResult(
                        success=False,
                        error=f'runner returned invalid result: {type(result)}',
                    )
            except Exception as exc:
                logger.exception(f'task `{task.name}` crashed: {exc}')
                result = TaskResult(success=False, error=str(exc))

            with self._lock:
                item = self._tasks.get(task.name)
                if item:
                    self._apply_task_result(item, result)
                self._running_task = None

            if self._on_task_done:
                try:
                    self._on_task_done(task.name, result)
                except Exception as exc:
                    logger.debug(f'task done hook error: {exc}')

            self._emit_snapshot()
            time.sleep(0.03)
