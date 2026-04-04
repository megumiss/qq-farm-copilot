"""统一任务执行器（pending/waiting 队列 + task_delay/task_call）。"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable

from loguru import logger

from core.engine.task_registry import TaskContext, TaskItem, TaskResult, TaskSnapshot

TaskRunner = Callable[[TaskContext], TaskResult]
SnapshotHook = Callable[[TaskSnapshot], None]
TaskDoneHook = Callable[[str, TaskResult], None]
IdleHook = Callable[[], None]


class TaskExecutor:
    """通用任务执行器：维护任务队列并在后台线程中按优先级调度。"""
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
        """注入任务定义、执行回调和事件钩子，准备调度线程状态。"""
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
        """启动执行线程；若已在运行则忽略重复启动。"""
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
        """请求停止执行线程，并在超时时间内等待线程退出。"""
        self._stop_event.set()
        self._pause_event.clear()
        th = self._thread
        if th and th.is_alive():
            th.join(timeout=max(0.1, float(wait_timeout)))

    def pause(self):
        """暂停调度循环（线程仍存活，仅停止取任务）。"""
        self._pause_event.set()

    def resume(self):
        """恢复调度循环。"""
        self._pause_event.clear()

    def is_running(self) -> bool:
        """返回执行线程是否仍然存活。"""
        return bool(self._thread and self._thread.is_alive())

    def is_stop_requested(self) -> bool:
        """返回是否已收到停止请求。"""
        return self._stop_event.is_set()

    def set_empty_queue_policy(self, policy: str):
        """设置空队列时策略（如 `stay` 或 `goto_main`）。"""
        with self._lock:
            self._empty_queue_policy = str(policy or 'stay')

    def update_task(self, name: str, **kwargs):
        """按字段增量更新某个任务配置。"""
        with self._lock:
            task = self._tasks.get(name)
            if not task:
                return
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)

    def snapshot(self, now: datetime | None = None) -> TaskSnapshot:
        """生成当前调度快照（运行中、待执行、等待中）。"""
        with self._lock:
            return self._snapshot_locked(now or datetime.now())

    def task_delay(
        self,
        task: str,
        *,
        seconds: int | None = None,
        target_time: datetime | None = None,
    ) -> bool:
        """延后任务执行时间，支持相对秒数或绝对时间。"""
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
        """将任务立即放入可执行队列（可选强制启用任务）。"""
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
        """在持锁状态下构建任务快照，避免并发读写不一致。"""
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
        """拷贝任务对象，用于快照输出避免外部改写内部状态。"""
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
        """触发快照回调，向上层同步调度状态。"""
        if not self._on_snapshot:
            return
        try:
            self._on_snapshot(self.snapshot())
        except Exception as exc:
            logger.debug(f'snapshot hook error: {exc}')

    def _apply_task_result(self, task: TaskItem, result: TaskResult):
        """根据任务结果更新失败次数与下一次执行时间。"""
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
            # 连续失败超过阈值时主动放大重试间隔，避免高频失败刷屏。
            if task.failure_count >= max(1, int(task.max_failures)):
                interval = max(interval, int(task.failure_interval) * 3)

        task.next_run = now + timedelta(seconds=max(1, interval))

    def _loop(self):
        """执行器主循环：挑选任务、执行任务、回写结果并推送快照。"""
        self._emit_snapshot()
        while not self._stop_event.is_set():
            # 暂停态只保活线程，不调度任务。
            if self._pause_event.is_set():
                time.sleep(0.08)
                continue

            now = datetime.now()
            with self._lock:
                # 每轮重新计算 pending/waiting，并选出一个可执行任务。
                snap = self._snapshot_locked(now)
                task = snap.pending_tasks[0] if snap.pending_tasks else None
                if task:
                    self._running_task = task.name
                else:
                    self._running_task = None

            self._emit_snapshot()

            if not task:
                # 空队列时可执行 idle hook（例如回主界面），并短暂休眠。
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
                # 缺少 runner 视为失败任务，写回失败间隔后继续循环。
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
                # 调用任务回调；异常统一转为失败结果，避免线程退出。
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

