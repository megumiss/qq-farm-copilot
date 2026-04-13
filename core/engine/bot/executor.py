"""Bot 执行器与调度相关逻辑。"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Callable

from loguru import logger

from core.engine.task.executor import TaskExecutor
from core.engine.task.registry import (
    TaskContext,
    TaskItem,
    TaskResult,
    TaskSnapshot,
)
from core.exceptions import GamePageUnknownError, LoginRepeatError, TaskRetryCurrentError
from core.platform.device import DeviceStuckError, DeviceTooManyClickError
from models.config import (
    DEFAULT_TASK_ENABLED_TIME_RANGE,
    TaskTriggerType,
    normalize_task_enabled_time_range,
    resolve_task_min_interval_seconds,
)
from tasks.friend import TaskFriend
from tasks.gift import TaskGift
from tasks.main import TaskMain
from tasks.reward import TaskReward
from tasks.sell import TaskSell
from tasks.share import TaskShare
from utils.app_paths import load_config_json_object
from utils.feature_policy import get_forced_off_features


class BotExecutorMixin:
    """Bot 执行器与调度相关逻辑。"""

    _NEXT_RUN_PARSE_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M')

    @staticmethod
    @lru_cache(maxsize=1)
    def _task_title_map() -> dict[str, str]:
        """读取任务中文标题映射。"""
        data = load_config_json_object('ui_labels.json', prefer_user=False)
        panel = data.get('task_panel', {})
        if not isinstance(panel, dict):
            return {}
        titles = panel.get('task_titles', {})
        if not isinstance(titles, dict):
            return {}
        return {str(k): str(v) for k, v in titles.items()}

    def _task_display_name(self, task_name: str) -> str:
        """获取任务显示名称（优先中文标题）。"""
        return self._task_title_map().get(str(task_name), str(task_name))

    def _emit_stats_now(self):
        """立即推送一次完整统计，避免跨线程信号丢失导致 UI 不刷新。"""
        sender = getattr(self, 'emit_stats', None)
        stats = self.scheduler.get_stats()
        if callable(sender):
            try:
                sender(stats)
                return
            except Exception:
                pass
        self.stats_updated.emit(stats)

    def _emit_config_now(self):
        """立即推送一次配置快照，确保 UI 读取到最新持久化配置。"""
        payload = self.config.model_dump()
        sender = getattr(self, 'emit_config_event', None)
        if callable(sender):
            try:
                sender(payload)
                return
            except Exception:
                pass
        emitter = getattr(self, 'config_updated', None)
        if emitter is not None:
            try:
                emitter.emit(payload)
            except Exception:
                pass

    def _reset_device_runtime_guards(self):
        """任务开始前重置设备卡死/点击守卫记录。"""
        if not self.device:
            return
        self.device.stuck_record_clear()
        self.device.click_record_clear()

    def _get_task_cfg(self, task_name: str):
        """按任务名读取调度配置。"""
        tasks_cfg = getattr(self.config, 'tasks', None)
        if isinstance(tasks_cfg, dict):
            return tasks_cfg.get(task_name)
        if tasks_cfg is None:
            return None
        return getattr(tasks_cfg, task_name, None)

    def _iter_task_config_names(self) -> list[str]:
        """按配置声明顺序返回任务名列表。"""
        tasks_cfg = getattr(self.config, 'tasks', None)
        if tasks_cfg is None:
            return []
        if isinstance(tasks_cfg, dict):
            return [str(name) for name in tasks_cfg.keys()]
        try:
            return [str(name) for name in tasks_cfg.model_dump().keys()]
        except Exception:
            return []

    @classmethod
    def _parse_task_next_run_text(cls, text: str | None) -> datetime | None:
        """解析配置中的 `next_run` 文本。"""
        raw = str(text or '').strip().replace('T', ' ')
        if not raw:
            return None
        for fmt in cls._NEXT_RUN_PARSE_FORMATS:
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                continue
        return None

    @staticmethod
    def _serialize_task_next_run_text(next_run: datetime) -> str:
        """序列化 `next_run` 以写入配置。"""
        return next_run.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')

    def _persist_task_next_run(self, task_name: str) -> None:
        """将任务下次执行时间回写到配置文件。"""
        item = self._executor_tasks.get(task_name)
        if item is None:
            return
        cfg = self._get_task_cfg(task_name)
        if cfg is None:
            return
        next_run_text = self._serialize_task_next_run_text(item.next_run)
        if str(getattr(cfg, 'next_run', '') or '') == next_run_text:
            return
        cfg.next_run = next_run_text
        try:
            self.config.save()
            self._emit_config_now()
        except Exception as exc:
            logger.debug(f'persist next_run failed({task_name}): {exc}')

    def _collect_task_runners(self) -> dict[str, Callable[[TaskContext], TaskResult]]:
        """自动发现 `_run_task_*` 任务入口方法并构建 runner 映射。"""
        runners: dict[str, Callable[[TaskContext], TaskResult]] = {}
        for attr in dir(self):
            if not attr.startswith('_run_task_'):
                continue
            runner = getattr(self, attr, None)
            if not callable(runner):
                continue
            task_name = attr[len('_run_task_') :].strip()
            if not task_name:
                continue
            runners[task_name] = runner
        return runners

    def _build_executor_tasks(
        self,
        runners: dict[str, Callable[[TaskContext], TaskResult]],
    ) -> dict[str, TaskItem]:
        """按配置 + runner 自动生成初始任务表。"""
        now = datetime.now()
        min_interval = resolve_task_min_interval_seconds(self.config.executor)
        default_success = max(min_interval, int(self.config.executor.default_success_interval))
        default_failure = max(min_interval, int(self.config.executor.default_failure_interval))
        max_failures = max(1, int(self.config.executor.max_failures))

        task_names = self._iter_task_config_names()
        for name in sorted(runners.keys()):
            if name not in task_names:
                task_names.append(name)

        out: dict[str, TaskItem] = {}
        for index, task_name in enumerate(task_names, start=1):
            cfg = self._get_task_cfg(task_name)
            has_runner = task_name in runners
            enabled = bool(has_runner) if cfg is None else bool(cfg.enabled and has_runner)
            if cfg is None and has_runner:
                logger.info(f'任务 `{task_name}` 未在配置中声明，使用执行器默认调度参数')
            priority = int(getattr(cfg, 'priority', index * 10))

            success_interval = max(
                min_interval,
                int(getattr(cfg, 'interval_seconds', default_success)),
            )
            failure_interval = max(
                min_interval,
                int(getattr(cfg, 'failure_interval_seconds', default_failure)),
            )
            trigger_cfg = getattr(cfg, 'trigger', TaskTriggerType.INTERVAL)
            trigger_text = trigger_cfg.value if isinstance(trigger_cfg, TaskTriggerType) else str(trigger_cfg)

            next_run = now
            if cfg is not None:
                parsed_next_run = self._parse_task_next_run_text(getattr(cfg, 'next_run', ''))
                if parsed_next_run is not None:
                    next_run = parsed_next_run
                elif getattr(cfg, 'trigger', TaskTriggerType.INTERVAL) == TaskTriggerType.DAILY:
                    next_run = self._next_daily_target_time(cfg.daily_time, now)

            out[task_name] = TaskItem(
                name=task_name,
                enabled=enabled,
                priority=priority,
                next_run=next_run,
                success_interval=success_interval,
                failure_interval=failure_interval,
                trigger=trigger_text,
                enabled_time_range=normalize_task_enabled_time_range(
                    getattr(cfg, 'enabled_time_range', DEFAULT_TASK_ENABLED_TIME_RANGE)
                ),
                max_failures=max_failures,
            )
        return out

    def _executor_running(self) -> bool:
        """判断执行器线程是否仍在运行。"""
        return bool(self._task_executor and self._task_executor.is_running())

    def _prepare_task_scene(self, task_name: str) -> tuple[tuple[int, int, int, int] | None, TaskResult | None]:
        """统一准备任务执行场景：窗口与截图区域。"""
        if self.ui is None:
            return None, TaskResult(success=False, error='UI未初始化')

        rect = self._prepare_window()
        if not rect:
            return None, TaskResult(success=False, error='窗口未找到')
        if self.device:
            self.device.set_rect(rect)
        return rect, None

    @staticmethod
    def _next_daily_target_time(daily_time: str, now: datetime | None = None) -> datetime:
        """计算下一次每日触发的目标时间点（绝对时间）。"""
        current = now or datetime.now()
        text = str(daily_time or '00:01')
        try:
            hour = int(text[:2])
            minute = int(text[3:5])
        except Exception:
            hour, minute = 0, 1
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= current:
            target = target + timedelta(days=1)
        return target

    @staticmethod
    def _seconds_to_next_daily(daily_time: str, now: datetime | None = None) -> int:
        """计算距离下一次每日触发时间的秒数。"""
        current = now or datetime.now()
        target = BotExecutorMixin._next_daily_target_time(daily_time, current)
        # 避免 int 向下取整造成 1 秒偏差（例如 00:01 变成次日 00:00:59）。
        return max(1, int(math.ceil((target - current).total_seconds())))

    @staticmethod
    def _format_task_next_run(item: TaskItem | None) -> str:
        """格式化任务下一次执行时间。"""
        if not item or not item.enabled:
            return '--'
        return item.next_run.strftime('%H:%M:%S')

    def _snapshot_next_task_name(self, snapshot: TaskSnapshot) -> str:
        """读取快照内下一次将执行的任务名（无任务返回 `--`）。"""
        if snapshot.pending_tasks:
            return self._task_display_name(snapshot.pending_tasks[0].name)
        if snapshot.waiting_tasks:
            return self._task_display_name(snapshot.waiting_tasks[0].name)
        return '--'

    @staticmethod
    def _snapshot_next_run_text(snapshot: TaskSnapshot) -> str:
        """读取快照内下一次执行时间文本（无任务返回 `--`）。"""
        if snapshot.pending_tasks:
            return snapshot.pending_tasks[0].next_run.strftime('%m-%d %H:%M:%S')
        if snapshot.waiting_tasks:
            return snapshot.waiting_tasks[0].next_run.strftime('%m-%d %H:%M:%S')
        return '--'

    def _task_seconds_by_trigger(self, task_name: str, now: datetime | None = None) -> int:
        """按任务触发类型返回下次调度间隔秒数。"""
        current = now or datetime.now()
        min_interval = resolve_task_min_interval_seconds(self.config.executor)
        cfg = self._get_task_cfg(task_name)
        if cfg is None:
            return max(min_interval, int(self.config.executor.default_success_interval))
        if cfg.trigger == TaskTriggerType.DAILY:
            return self._seconds_to_next_daily(cfg.daily_time, current)
        return max(min_interval, int(cfg.interval_seconds))

    def get_task_features(self, task_name: str) -> dict[str, Any]:
        """获取 `task_features` 信息。"""
        cfg = self._get_task_cfg(task_name)
        if cfg is None:
            return {}
        raw = getattr(cfg, 'features', {}) or {}
        if not isinstance(raw, dict):
            return {}
        features: dict[str, Any] = {}
        for key, value in raw.items():
            name = str(key)
            if isinstance(value, list):
                cleaned: list[str] = []
                seen: set[str] = set()
                for item in value:
                    text = str(item or '').strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    cleaned.append(text)
                features[name] = cleaned
                continue
            features[name] = bool(value)
        for key in get_forced_off_features(str(task_name)):
            features[key] = False
        return features

    def _sync_executor_tasks_from_config(
        self,
        runners: dict[str, Callable[[TaskContext], TaskResult]] | None = None,
    ):
        """将当前配置同步到执行器任务项（启停、间隔、失败参数）。"""
        if not self._executor_tasks:
            return
        # 统一按当前配置计算每个任务的启停状态与执行间隔。
        min_interval = resolve_task_min_interval_seconds(self.config.executor)
        default_success = max(min_interval, int(self.config.executor.default_success_interval))
        default_failure = max(min_interval, int(self.config.executor.default_failure_interval))
        max_failures = max(1, int(self.config.executor.max_failures))
        now = datetime.now()
        runners = runners or self._collect_task_runners()

        if self._task_executor:
            # 执行器已启动：直接热更新运行中的任务参数。
            self._task_executor.set_empty_queue_policy(self.config.executor.empty_queue_policy)

        task_names = list(self._executor_tasks.keys())
        for index, task_name in enumerate(task_names, start=1):
            cfg = self._get_task_cfg(task_name)
            item = self._executor_tasks.get(task_name)
            has_runner = task_name in runners

            enabled = bool(has_runner) if cfg is None else bool(cfg.enabled and has_runner)
            priority = int(getattr(cfg, 'priority', index * 10))
            success_interval = max(
                min_interval,
                int(getattr(cfg, 'interval_seconds', default_success)),
            )
            failure_interval = max(
                min_interval,
                int(getattr(cfg, 'failure_interval_seconds', default_failure)),
            )
            trigger_cfg = getattr(cfg, 'trigger', TaskTriggerType.INTERVAL)
            trigger_text = trigger_cfg.value if isinstance(trigger_cfg, TaskTriggerType) else str(trigger_cfg)
            kwargs = {
                'enabled': enabled,
                'priority': priority,
                'success_interval': success_interval,
                'failure_interval': failure_interval,
                'trigger': trigger_text,
                'enabled_time_range': normalize_task_enabled_time_range(
                    getattr(cfg, 'enabled_time_range', DEFAULT_TASK_ENABLED_TIME_RANGE)
                ),
                'max_failures': max_failures,
            }

            parsed_next_run = self._parse_task_next_run_text(getattr(cfg, 'next_run', '')) if cfg is not None else None
            if parsed_next_run is not None:
                kwargs['next_run'] = parsed_next_run
            elif enabled and item and item.next_run < now:
                kwargs['next_run'] = now

            if self._task_executor:
                self._task_executor.update_task(task_name, **kwargs)
            elif item:
                item.enabled = bool(kwargs['enabled'])
                item.priority = int(kwargs['priority'])
                item.success_interval = int(kwargs['success_interval'])
                item.failure_interval = int(kwargs['failure_interval'])
                item.trigger = str(kwargs['trigger'])
                item.enabled_time_range = str(kwargs['enabled_time_range'])
                item.max_failures = int(kwargs['max_failures'])
                if 'next_run' in kwargs:
                    item.next_run = kwargs['next_run']

    def _init_executor(self):
        """创建并启动统一任务执行器。"""
        runners = self._collect_task_runners()
        self._executor_tasks = self._build_executor_tasks(runners)
        self._sync_executor_tasks_from_config(runners=runners)
        self._accept_executor_events = True
        self._task_executor = TaskExecutor(
            tasks=self._executor_tasks,
            runners=runners,
            empty_queue_policy=self.config.executor.empty_queue_policy,
            on_snapshot=self._on_executor_snapshot,
            on_task_done=self._on_executor_task_done,
            on_task_error=self._on_executor_task_error,
            on_idle=self._on_executor_idle,
        )
        self._task_executor.start()

    def _stop_executor(self):
        """停止执行器并清空执行器持有的任务快照。"""
        self._accept_executor_events = False
        executor = self._task_executor
        self._task_executor = None
        if executor:
            executor.stop(wait_timeout=1.5)
        self._executor_tasks = {}

    def _run_task_main(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_main` 子流程。"""
        rect, err = self._prepare_task_scene('main')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskMain(engine=self, ui=self.ui, ocr_tool=self._ocr_tool)
        return task.run(rect=rect)

    def _run_task_friend(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_friend` 子流程。"""
        rect, err = self._prepare_task_scene('friend')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskFriend(engine=self, ui=self.ui, ocr_tool=self._ocr_tool)
        return task.run(rect=rect)

    def _run_task_share(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_share` 子流程。"""
        rect, err = self._prepare_task_scene('share')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskShare(engine=self, ui=self.ui)
        return task.run(rect=rect)

    def _run_task_reward(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_reward` 子流程。"""
        rect, err = self._prepare_task_scene('reward')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskReward(engine=self, ui=self.ui)
        return task.run(rect=rect)

    def _run_task_sell(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_sell` 子流程。"""
        rect, err = self._prepare_task_scene('sell')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskSell(engine=self, ui=self.ui)
        return task.run(rect=rect)

    def _run_task_gift(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_gift` 子流程。"""
        rect, err = self._prepare_task_scene('gift')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskGift(engine=self, ui=self.ui)
        return task.run(rect=rect)

    def _on_executor_snapshot(self, snapshot: TaskSnapshot):
        """接收执行器快照并更新 GUI 统计面板。"""
        if not self._accept_executor_events:
            return
        self.scheduler.update_runtime_metrics(
            current_task=self._task_display_name(snapshot.running_task) if snapshot.running_task else '--',
            next_task=self._snapshot_next_task_name(snapshot),
            next_run=self._snapshot_next_run_text(snapshot),
            running_tasks=1 if snapshot.running_task else 0,
            pending_tasks=len(snapshot.pending_tasks),
            waiting_tasks=len(snapshot.waiting_tasks),
        )
        self._emit_stats_now()

    def _on_executor_task_done(self, task_name: str, result: TaskResult):
        """处理任务完成事件并更新运行统计。"""
        if not self._accept_executor_events:
            return
        # 对齐 NIKKE：daily 任务的下次执行时间由执行器统一按 daily_time 计算，
        # 任务实现层无需每次显式返回 next_run_seconds。
        cfg = self._get_task_cfg(task_name)
        if (
            result.success
            and result.next_run_seconds is None
            and cfg is not None
            and getattr(cfg, 'trigger', TaskTriggerType.INTERVAL) == TaskTriggerType.DAILY
            and self._task_executor is not None
        ):
            self._task_executor.task_delay(
                task_name,
                target_time=self._next_daily_target_time(cfg.daily_time),
            )

        if not result.success and task_name in self._task_error_delay_overrides and self._task_executor is not None:
            delay_seconds = max(1, int(self._task_error_delay_overrides.pop(task_name)))
            err_type = self._task_error_type_names.pop(task_name, '')
            self._task_executor.task_delay(task_name, seconds=delay_seconds)
            if err_type:
                logger.warning(f'[{self._task_display_name(task_name)}] 异常恢复: {err_type}，{delay_seconds}s后重试')
        elif result.success:
            self._task_error_delay_overrides.pop(task_name, None)
            self._task_error_type_names.pop(task_name, None)

        self._persist_task_next_run(task_name)

        status_text = '成功' if result.success else '失败'
        next_run_text = self._format_task_next_run(self._executor_tasks.get(task_name))
        display_name = self._task_display_name(task_name)
        msg = f'[{display_name}] 任务完成: {status_text} | 下次执行: {next_run_text}'
        if not result.success and result.error:
            msg = f'{msg} | 错误: {result.error}'
        logger.info(msg)

        self._emit_stats_now()

    def _on_executor_task_error(self, task_name: str, exc: Exception, tb_text: str):
        """任务异常回调：保存异常截图，并默认进入人工接管流程。"""
        if self.device:
            try:
                folder = self.device.save_error_screenshots(
                    task_name=task_name,
                    error_text=tb_text,
                    base_dir=getattr(self, '_error_dir', 'logs/error'),
                )
                logger.error(f'异常截图已保存: {folder}')
            except Exception as save_exc:
                logger.debug(f'save error screenshots failed: {save_exc}')

        if isinstance(exc, TaskRetryCurrentError):
            self._task_error_type_names[task_name] = type(exc).__name__
            # 点击修复类异常：1 秒后重跑当前任务，不进入人工接管。
            self._task_error_delay_overrides[task_name] = 1
            logger.warning(f'[{self._task_display_name(task_name)}] 触发重试: {type(exc).__name__}，1s后重跑当前任务')
            return

        self._task_error_type_names[task_name] = type(exc).__name__

        if isinstance(exc, GamePageUnknownError):
            self._request_manual_takeover(
                reason=f'检测到未知页面异常({task_name})，已停止任务',
            )
            return

        if isinstance(exc, LoginRepeatError):
            self._request_manual_takeover(
                reason=f'检测到重复登录异常({task_name})，已停止任务',
            )
            return

        if isinstance(exc, (DeviceStuckError, DeviceTooManyClickError)):
            self._request_manual_takeover(
                reason=f'检测到设备卡死异常({task_name})，已停止任务',
            )
            return

        self._request_manual_takeover(
            reason=f'任务异常({task_name}): {type(exc).__name__}，已停止任务',
        )

    def _request_manual_takeover(self, reason: str):
        """请求人工接管：异步停止引擎，避免执行器线程自停造成 join 冲突。"""
        if self._fatal_error_stop_requested:
            return
        self._fatal_error_stop_requested = True
        message = str(reason or '检测到致命异常，请手动处理')
        logger.critical(message)
        emitter = getattr(self, 'log_message', None)
        if emitter is not None:
            try:
                emitter.emit(message)
            except Exception:
                pass

        def _stop_engine():
            try:
                self.stop()
            except Exception as exc:
                logger.debug(f'fatal stop failed: {exc}')

        threading.Thread(target=_stop_engine, name='FatalErrorStopper', daemon=True).start()

    def _on_executor_idle(self):
        """执行器空闲时触发：按策略尝试回主界面。"""
        if not self._accept_executor_events:
            return
        if not self.ui:
            return
        rect = self.window_manager.get_capture_rect()
        if rect and self.device:
            self.device.set_rect(rect)
        try:
            self.ui.ui_goto_main()
        except Exception as exc:
            logger.debug(f'idle ensure main failed: {exc}')
