"""Bot 执行器与调度相关逻辑。"""

from __future__ import annotations

import math
import threading
import traceback
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
from core.exceptions import (
    GamePageUnknownError,
    LoginRecoveryRequiredError,
    LoginRepeatError,
    WindowCaptureError,
)
from core.platform.device import DeviceStuckError, DeviceTooManyClickError
from models.config import (
    DEFAULT_TASK_ENABLED_TIME_RANGE,
    TaskScheduleItemConfig,
    TaskTriggerType,
    normalize_task_enabled_time_range,
    parse_executor_task_order,
)
from models.task_views import (
    TASK_FEATURE_CLASS_MAP,
    TASK_VIEW_CLASS_MAP,
    TaskViewBase,
)
from tasks.friend import TaskFriend
from tasks.gift import TaskGift
from tasks.land_scan import TaskLandScan
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

    def _task_recovery_policy(self) -> tuple[int, int]:
        """读取任务异常恢复策略（重启次数、重试延迟）。"""
        recovery_cfg = self.config.recovery
        restart_limit = int(recovery_cfg.task_restart_attempts)
        retry_delay = int(recovery_cfg.task_retry_delay_seconds)
        return max(1, restart_limit), max(1, retry_delay)

    def _sync_recovery_policy_from_config(self) -> None:
        """保留接口：恢复策略按需从配置读取，无需额外同步。"""
        return None

    def _record_recovery_event(
        self,
        *,
        task_name: str,
        error_key: str,
        action: str,
        outcome: str,
    ) -> None:
        """记录恢复事件并写入运行态指标。"""
        self._recovery_total_count += 1
        self._recovery_last_error = str(error_key or '--')
        self._recovery_last_action = str(action or '--')
        self._recovery_last_outcome = str(outcome or '--')
        self._recovery_last_task = str(task_name or '--')
        self.scheduler.update_runtime_metrics(
            recovery_total=self._recovery_total_count,
            recovery_last_error=self._recovery_last_error,
            recovery_last_action=self._recovery_last_action,
            recovery_last_outcome=self._recovery_last_outcome,
            recovery_last_task=self._recovery_last_task,
        )

    def _reset_recovery_metrics(self) -> None:
        """重置恢复指标。"""
        self._recovery_total_count = 0
        self._recovery_last_error = '--'
        self._recovery_last_action = '--'
        self._recovery_last_outcome = '--'
        self._recovery_last_task = '--'
        self.scheduler.update_runtime_metrics(
            recovery_total=0,
            recovery_last_error='--',
            recovery_last_action='--',
            recovery_last_outcome='--',
            recovery_last_task='--',
        )

    def _reset_device_runtime_guards(self):
        """任务开始前重置设备卡死/点击守卫记录。"""
        if not self.device:
            return
        self.device.stuck_record_clear()
        self.device.click_record_clear()

    def _get_task_cfg(self, task_name: str) -> TaskScheduleItemConfig | None:
        """按任务名读取调度配置。"""
        return self.config.tasks.get(str(task_name))

    def _iter_task_config_names(self) -> list[str]:
        """按配置声明顺序返回任务名列表。"""
        return [str(name) for name in self.config.tasks.keys()]

    def _ordered_task_names(self, runners: dict[str, Callable[[TaskContext], TaskResult]] | None = None) -> list[str]:
        """按 `executor.task_order` + 配置声明顺序产出任务名列表。"""
        ordered = parse_executor_task_order(self.config.executor.task_order)
        known_names: set[str] = set(self._iter_task_config_names())
        if runners:
            known_names.update(str(name) for name in runners.keys())

        out: list[str] = []
        seen: set[str] = set()

        for name in ordered:
            task_name = str(name)
            if not task_name or task_name in seen or task_name not in known_names:
                continue
            seen.add(task_name)
            out.append(task_name)

        for name in self._iter_task_config_names():
            task_name = str(name)
            if not task_name or task_name in seen:
                continue
            seen.add(task_name)
            out.append(task_name)

        if runners:
            for name in sorted(runners.keys()):
                task_name = str(name)
                if not task_name or task_name in seen:
                    continue
                seen.add(task_name)
                out.append(task_name)

        return out

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

    def _resolve_task_schedule_fields(
        self,
        cfg: TaskScheduleItemConfig | None,
        *,
        min_interval: int,
        default_success: int,
        default_failure: int,
    ) -> tuple[int, int, str, str, datetime | None]:
        """解析任务调度字段（间隔/触发器/时段/next_run）。"""
        success_interval = max(
            min_interval,
            int(cfg.interval_seconds) if cfg is not None else int(default_success),
        )
        failure_interval = max(
            min_interval,
            int(cfg.failure_interval_seconds) if cfg is not None else int(default_failure),
        )
        trigger_cfg = cfg.trigger if cfg is not None else TaskTriggerType.INTERVAL
        trigger_text = trigger_cfg.value if isinstance(trigger_cfg, TaskTriggerType) else str(trigger_cfg)
        enabled_time_range = normalize_task_enabled_time_range(
            cfg.enabled_time_range if cfg is not None else DEFAULT_TASK_ENABLED_TIME_RANGE
        )
        parsed_next_run = self._parse_task_next_run_text(cfg.next_run) if cfg is not None else None
        return success_interval, failure_interval, trigger_text, enabled_time_range, parsed_next_run

    def _persist_task_next_run(self, task_name: str) -> None:
        """将任务下次执行时间回写到配置文件。"""
        item = self._executor_tasks.get(task_name)
        if item is None:
            return
        cfg = self._get_task_cfg(task_name)
        if cfg is None:
            return
        next_run_text = self._serialize_task_next_run_text(item.next_run)
        if str(cfg.next_run or '') == next_run_text:
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

    @classmethod
    def _is_restart_exception(cls, exc: Exception) -> bool:
        """判断异常是否应走重启任务恢复。"""
        return isinstance(
            exc,
            (
                GamePageUnknownError,
                DeviceStuckError,
                DeviceTooManyClickError,
                WindowCaptureError,
            ),
        )

    @classmethod
    def _error_key_for_exception(cls, exc: Exception) -> str:
        """将异常归一化为稳定错误键。"""
        if isinstance(exc, LoginRecoveryRequiredError):
            return 'login_recovery_required'
        if isinstance(exc, LoginRepeatError):
            return 'login_repeat'
        if isinstance(exc, GamePageUnknownError):
            return 'page_unknown'
        if isinstance(exc, DeviceStuckError):
            return 'device_stuck'
        if isinstance(exc, DeviceTooManyClickError):
            return 'too_many_click'
        if isinstance(exc, WindowCaptureError):
            return 'print_window_failure'
        return 'task_exception'

    @classmethod
    def _build_restart_stop_reason(cls, *, task_name: str, exc: Exception, restart_limit: int) -> str:
        """按异常类型生成“重启次数已达上限”原因。"""
        err_type = type(exc).__name__
        if isinstance(exc, GamePageUnknownError):
            return f'检测到未知页面异常({task_name})，重启任务已达{restart_limit}次，已停止任务'
        if isinstance(exc, (DeviceStuckError, DeviceTooManyClickError)):
            return f'检测到设备卡死异常({task_name})，重启任务已达{restart_limit}次，已停止任务'
        if isinstance(exc, WindowCaptureError):
            return f'检测到截图异常({task_name})，重启任务已达{restart_limit}次，已停止任务'
        return f'任务异常({task_name}): {err_type}，重启任务已达{restart_limit}次，已停止任务'

    def _handle_startup_exception(self, *, exc: Exception) -> tuple[bool, str]:
        """启动阶段异常单入口：返回 `(continue_loop, last_error)`。"""
        if isinstance(exc, LoginRepeatError):
            self._record_recovery_event(
                task_name='startup',
                error_key='login_repeat',
                action='fail_startup',
                outcome='abort_startup',
            )
            logger.error('检测到重复登录，请先手动处理后再启动')
            return False, 'login_repeat'

        error_key = self._error_key_for_exception(exc)
        if isinstance(exc, LoginRecoveryRequiredError):
            self._record_recovery_event(
                task_name='startup',
                error_key=error_key,
                action='retry_startup_loop',
                outcome='continue_startup',
            )
            return True, str(exc or type(exc).__name__)

        # 启动阶段统一继续重试（由启动总超时兜底），避免单次截图/页面抖动直接终止启动流程。
        self._record_recovery_event(
            task_name='startup',
            error_key=error_key,
            action='retry_startup_loop',
            outcome='continue_startup',
        )
        return True, str(exc or type(exc).__name__)

    def _save_task_exception_snapshot(self, *, task_name: str, tb_text: str) -> None:
        """保存任务异常截图与 traceback。"""
        if not self.device:
            return
        try:
            folder = self.device.save_error_screenshots(
                task_name=task_name,
                error_text=tb_text,
                base_dir=getattr(self, '_error_dir', 'logs/error'),
            )
            logger.error(f'异常截图已保存: {folder}')
        except Exception as save_exc:
            logger.debug(f'save error screenshots failed: {save_exc}')

    def _handle_task_exception(self, *, task_name: str, exc: Exception, tb_text: str) -> TaskResult:
        """任务异常单入口（NIKKE 风格）：直接在一处完成分流与恢复动作。"""
        self._save_task_exception_snapshot(task_name=task_name, tb_text=tb_text)
        display_name = self._task_display_name(task_name)
        err_type = type(exc).__name__
        error_key = self._error_key_for_exception(exc)

        if isinstance(exc, LoginRecoveryRequiredError):
            recovered = False
            try:
                recovered = bool(self.recover_after_login_again(task_name=task_name))
            except Exception as recover_exc:
                logger.exception(f'[{display_name}] 登录恢复执行异常: {recover_exc}')
                recovered = False

            self._task_exception_retry_counts.pop(task_name, None)
            if recovered:
                delay_seconds = max(1, int(self._task_seconds_by_trigger(task_name)))
                self._record_recovery_event(
                    task_name=task_name,
                    error_key=error_key,
                    action='recover_login_flow',
                    outcome='skip_task',
                )
                logger.warning(f'[{display_name}] 登录恢复成功，本轮任务结束，按调度间隔延后 {delay_seconds}s')
                return TaskResult(success=True, next_run_seconds=delay_seconds)

            self._record_recovery_event(
                task_name=task_name,
                error_key=error_key,
                action='recover_login_flow',
                outcome='stop',
            )
            reason = f'检测到重新登录异常({task_name})，登录恢复失败，已停止任务'
            self._request_manual_takeover(reason=reason)
            return TaskResult(success=False, error=reason)

        if isinstance(exc, LoginRepeatError):
            self._task_exception_retry_counts.pop(task_name, None)
            reason = f'检测到重复登录异常({task_name})，需人工接管，已停止任务'
            self._record_recovery_event(
                task_name=task_name,
                error_key=error_key,
                action='manual_takeover',
                outcome='stop',
            )
            self._request_manual_takeover(reason=reason)
            return TaskResult(success=False, error=reason)

        if self._is_restart_exception(exc):
            restart_limit, retry_delay = self._task_recovery_policy()
            current_attempt = int(self._task_exception_retry_counts.get(task_name, 0)) + 1
            self._task_exception_retry_counts[task_name] = current_attempt
            logger.warning(
                f'[{display_name}] 异常自动恢复 {current_attempt}/{restart_limit}: {err_type}，准备入队重启任务'
            )

            if current_attempt > restart_limit:
                self._task_exception_retry_counts.pop(task_name, None)
                reason = self._build_restart_stop_reason(
                    task_name=task_name,
                    exc=exc,
                    restart_limit=restart_limit,
                )
                self._record_recovery_event(
                    task_name=task_name,
                    error_key=error_key,
                    action='restart_task',
                    outcome='stop',
                )
                self._request_manual_takeover(reason=reason)
                return TaskResult(success=False, error=reason)

            valid_shortcut, shortcut_error = self._validate_window_shortcut_for_recovery()
            if not valid_shortcut:
                self._task_exception_retry_counts.pop(task_name, None)
                reason = f'任务异常({task_name}): {err_type}，无法重启窗口（{shortcut_error}），已停止任务'
                self._record_recovery_event(
                    task_name=task_name,
                    error_key=error_key,
                    action='restart_task',
                    outcome='stop',
                )
                self._request_manual_takeover(reason=reason)
                return TaskResult(success=False, error=reason)

            queued = self._queue_restart_task(
                source_task=task_name,
                err_type=err_type,
                attempt=current_attempt,
                limit=restart_limit,
            )
            if not queued:
                self._task_exception_retry_counts.pop(task_name, None)
                reason = f'任务异常({task_name})：重启任务入队失败，已停止任务'
                self._record_recovery_event(
                    task_name=task_name,
                    error_key=error_key,
                    action='restart_task',
                    outcome='stop',
                )
                self._request_manual_takeover(reason=reason)
                return TaskResult(success=False, error=reason)

            self._record_recovery_event(
                task_name=task_name,
                error_key=error_key,
                action='restart_task',
                outcome='restart_task_queued',
            )
            logger.warning(
                f'[{display_name}] 异常恢复 {current_attempt}/{restart_limit}: {err_type}，'
                f'已入队重启任务，{retry_delay}s后重试当前任务'
            )
            return TaskResult(
                success=False, error=f'{err_type}，已入队重启任务', next_run_seconds=max(1, int(retry_delay))
            )

        self._task_exception_retry_counts.pop(task_name, None)
        reason = f'任务异常({task_name}): {err_type}，需人工接管，已停止任务'
        self._record_recovery_event(
            task_name=task_name,
            error_key=error_key,
            action='manual_takeover',
            outcome='stop',
        )
        self._request_manual_takeover(reason=reason)
        return TaskResult(success=False, error=reason)

    def _wrap_runner_with_recovery(
        self,
        *,
        task_name: str,
        runner: Callable[[TaskContext], TaskResult],
    ) -> Callable[[TaskContext], TaskResult]:
        """为任务入口包装统一异常处理（restart 任务除外）。"""
        if task_name == 'restart':
            return runner

        def _wrapped(ctx: TaskContext) -> TaskResult:
            try:
                return runner(ctx)
            except Exception as exc:
                logger.exception(f'task `{task_name}` crashed: {exc}')
                return self._handle_task_exception(
                    task_name=task_name,
                    exc=exc,
                    tb_text=traceback.format_exc(),
                )

        return _wrapped

    def _collect_task_runners_with_recovery(self) -> dict[str, Callable[[TaskContext], TaskResult]]:
        """收集任务 runner，并注入统一异常恢复包装。"""
        raw = self._collect_task_runners()
        return {name: self._wrap_runner_with_recovery(task_name=name, runner=runner) for name, runner in raw.items()}

    def _build_executor_tasks(
        self,
        runners: dict[str, Callable[[TaskContext], TaskResult]],
    ) -> dict[str, TaskItem]:
        """按配置 + runner 自动生成初始任务表。"""
        now = datetime.now()
        min_interval = int(self.config.executor.min_task_interval_seconds)
        default_success = max(min_interval, int(self.config.executor.default_success_interval))
        default_failure = max(min_interval, int(self.config.executor.default_failure_interval))

        task_names = self._ordered_task_names(runners)

        out: dict[str, TaskItem] = {}
        for index, task_name in enumerate(task_names, start=1):
            cfg = self._get_task_cfg(task_name)
            has_runner = task_name in runners
            enabled = bool(has_runner) if cfg is None else bool(cfg.enabled and has_runner)
            if cfg is None and has_runner:
                logger.info(f'任务 `{task_name}` 未在配置中声明，使用执行器默认调度参数')
            order_index = index

            (
                success_interval,
                failure_interval,
                trigger_text,
                enabled_time_range,
                parsed_next_run,
            ) = self._resolve_task_schedule_fields(
                cfg,
                min_interval=min_interval,
                default_success=default_success,
                default_failure=default_failure,
            )

            next_run = now
            if parsed_next_run is not None:
                next_run = parsed_next_run
            elif cfg is not None and cfg.trigger == TaskTriggerType.DAILY:
                next_run = self._next_daily_target_time(cfg.daily_time, now)

            out[task_name] = TaskItem(
                name=task_name,
                enabled=enabled,
                order_index=order_index,
                next_run=next_run,
                success_interval=success_interval,
                failure_interval=failure_interval,
                trigger=trigger_text,
                enabled_time_range=enabled_time_range,
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
        min_interval = int(self.config.executor.min_task_interval_seconds)
        cfg = self._get_task_cfg(task_name)
        if cfg is None:
            return max(min_interval, int(self.config.executor.default_success_interval))
        if cfg.trigger == TaskTriggerType.DAILY:
            return self._seconds_to_next_daily(cfg.daily_time, current)
        return max(min_interval, int(cfg.interval_seconds))

    def is_task_enabled(self, task_name: str, *, runtime: bool = True) -> bool:
        """读取任务启用状态（可选返回运行时执行器状态）。"""
        name = str(task_name or '').strip()
        if not name:
            return False
        if runtime:
            item = self._executor_tasks.get(name)
            if item is not None:
                return bool(item.enabled)
        cfg = self._get_task_cfg(name)
        return bool(cfg and cfg.enabled)

    def _feature_value(self, raw: dict[str, Any], key: str, default: Any) -> Any:
        """按默认值类型读取 feature（配置层已完成基础归一化）。"""
        value = raw.get(str(key), default)
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, list):
            return list(value) if isinstance(value, list) else list(default)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(value)
            except Exception:
                return int(default)
        if isinstance(default, float):
            try:
                return float(value)
            except Exception:
                return float(default)
        if isinstance(default, str):
            return str(value or default)
        return value if value is not None else default

    def _build_task_view_base(self, task_name: str) -> TaskViewBase:
        """构造任务基础视图。"""
        name = str(task_name or '').strip()
        cfg = self._get_task_cfg(name)
        if not isinstance(cfg, TaskScheduleItemConfig):
            cfg = TaskScheduleItemConfig()
        return TaskViewBase(
            name=name,
            enabled=self.is_task_enabled(name, runtime=True),
            config_enabled=self.is_task_enabled(name, runtime=False),
            trigger=cfg.trigger,
            interval_seconds=int(cfg.interval_seconds),
            failure_interval_seconds=int(cfg.failure_interval_seconds),
            daily_time=str(cfg.daily_time),
            enabled_time_range=str(cfg.enabled_time_range),
            next_run=str(cfg.next_run),
            _task_call=lambda force_call: bool(self._task_executor and self._task_executor.task_call(name, force_call)),
        )

    @staticmethod
    def _task_view_base_kwargs(base: TaskViewBase) -> dict[str, Any]:
        """将基础任务视图转为可复用构造参数。"""
        return {
            'name': base.name,
            'enabled': base.enabled,
            'config_enabled': base.config_enabled,
            'trigger': base.trigger,
            'interval_seconds': base.interval_seconds,
            'failure_interval_seconds': base.failure_interval_seconds,
            'daily_time': base.daily_time,
            'enabled_time_range': base.enabled_time_range,
            'next_run': base.next_run,
            '_task_call': base._task_call,
        }

    def build_task_view(self, task_name: str) -> TaskViewBase:
        """按任务名构造强类型视图。"""
        name = str(task_name or '').strip()
        base = self._build_task_view_base(name)
        base_kwargs = self._task_view_base_kwargs(base)
        raw = self.get_task_features(name)
        feature_cls = TASK_FEATURE_CLASS_MAP.get(name)
        view_cls = TASK_VIEW_CLASS_MAP.get(name)
        if feature_cls is None or view_cls is None:
            return TaskViewBase(**base_kwargs)

        feature_defaults = feature_cls()
        feature_kwargs: dict[str, Any] = {}
        for field_name in feature_cls.__dataclass_fields__.keys():
            default_value = getattr(feature_defaults, field_name)
            feature_kwargs[field_name] = self._feature_value(raw, field_name, default_value)
        feature = feature_cls(**feature_kwargs)
        return view_cls(**base_kwargs, feature=feature)

    def get_task_features(self, task_name: str) -> dict[str, Any]:
        """获取 `task_features` 信息。"""
        cfg = self._get_task_cfg(task_name)
        if cfg is None:
            return {}
        features: dict[str, Any] = dict(cfg.features or {})
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
        min_interval = int(self.config.executor.min_task_interval_seconds)
        default_success = max(min_interval, int(self.config.executor.default_success_interval))
        default_failure = max(min_interval, int(self.config.executor.default_failure_interval))
        now = datetime.now()
        runners = runners or self._collect_task_runners()

        task_names = self._ordered_task_names(runners)
        for task_name in task_names:
            if task_name in self._executor_tasks:
                continue
            self._executor_tasks[task_name] = TaskItem(
                name=task_name,
                enabled=False,
                order_index=max(1, len(self._executor_tasks) + 1),
                next_run=now,
                success_interval=default_success,
                failure_interval=default_failure,
                trigger=TaskTriggerType.INTERVAL.value,
                enabled_time_range=DEFAULT_TASK_ENABLED_TIME_RANGE,
            )

        stale_names = [name for name in list(self._executor_tasks.keys()) if name not in task_names]
        for stale_name in stale_names:
            self._executor_tasks.pop(stale_name, None)

        for index, task_name in enumerate(task_names, start=1):
            cfg = self._get_task_cfg(task_name)
            item = self._executor_tasks.get(task_name)
            has_runner = task_name in runners

            if cfg is None:
                # 内置重启任务仅在异常恢复时按需触发，不参与常驻调度。
                enabled = bool(has_runner and task_name != 'restart')
            else:
                enabled = bool(cfg.enabled and has_runner)
            order_index = index
            (
                success_interval,
                failure_interval,
                trigger_text,
                enabled_time_range,
                parsed_next_run,
            ) = self._resolve_task_schedule_fields(
                cfg,
                min_interval=min_interval,
                default_success=default_success,
                default_failure=default_failure,
            )
            kwargs = {
                'enabled': enabled,
                'order_index': order_index,
                'success_interval': success_interval,
                'failure_interval': failure_interval,
                'trigger': trigger_text,
                'enabled_time_range': enabled_time_range,
            }
            if parsed_next_run is not None:
                kwargs['next_run'] = parsed_next_run
            elif enabled and item and item.next_run < now:
                kwargs['next_run'] = now

            if self._task_executor:
                self._task_executor.update_task(task_name, **kwargs)
            elif item:
                item.enabled = bool(kwargs['enabled'])
                item.order_index = int(kwargs['order_index'])
                item.success_interval = int(kwargs['success_interval'])
                item.failure_interval = int(kwargs['failure_interval'])
                item.trigger = str(kwargs['trigger'])
                item.enabled_time_range = str(kwargs['enabled_time_range'])
                if 'next_run' in kwargs:
                    item.next_run = kwargs['next_run']

    def _init_executor(self):
        """创建并启动统一任务执行器。"""
        runners = self._collect_task_runners_with_recovery()
        self._executor_tasks = self._build_executor_tasks(runners)
        self._sync_executor_tasks_from_config(runners=runners)
        self._accept_executor_events = True
        self._task_executor = TaskExecutor(
            tasks=self._executor_tasks,
            runners=runners,
            on_snapshot=self._on_executor_snapshot,
            on_task_done=self._on_executor_task_done,
        )
        self._task_executor.start()

    def _stop_executor(self) -> bool:
        """停止执行器并清空执行器持有的任务快照。"""
        self._accept_executor_events = False
        executor = self._task_executor
        if executor is None:
            self._executor_tasks = {}
            return True

        stopped = executor.stop(wait_timeout=1.5)
        if not stopped:
            # 二次等待，避免任务线程在长 sleep 阶段导致 stop 超时后误判已停。
            stopped = executor.stop(wait_timeout=6.0)
        if not stopped:
            logger.warning('执行器停止超时，仍在回收中，暂不允许重新启动')
            return False

        self._task_executor = None
        self._executor_tasks = {}
        return True

    def _run_task_main(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_main` 子流程。"""
        rect, err = self._prepare_task_scene('main')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskMain(engine=self, ui=self.ui, ocr_tool=self._get_ocr_tool())
        return task.run(rect=rect)

    def _run_task_friend(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_friend` 子流程。"""
        rect, err = self._prepare_task_scene('friend')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskFriend(engine=self, ui=self.ui, ocr_tool=self._get_ocr_tool())
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

    def _run_task_land_scan(self, _ctx: TaskContext) -> TaskResult:
        """执行 `task_land_scan` 子流程。"""
        rect, err = self._prepare_task_scene('land_scan')
        if err is not None or rect is None:
            return err or TaskResult(success=False, error='窗口未找到')
        self._reset_device_runtime_guards()
        task = TaskLandScan(engine=self, ui=self.ui, ocr_tool=self._get_ocr_tool())
        return task.run(rect=rect)

    def _run_task_restart(self, _ctx: TaskContext) -> TaskResult:
        """执行内置重启任务：重启窗口并完成启动收敛。"""
        payload = dict(self._restart_task_payload or {})
        source_task = str(payload.get('source_task') or 'unknown')
        err_type = str(payload.get('err_type') or 'Exception')
        attempt = max(1, int(payload.get('attempt') or 1))
        limit = max(1, int(payload.get('limit') or 1))

        try:
            ok = bool(
                self._restart_target_window_for_recovery(
                    task_name=source_task,
                    attempt=attempt,
                    limit=limit,
                    err_type=err_type,
                )
            )
        except Exception as exc:
            logger.exception(f'[restart] 重启任务执行异常: {exc}')
            ok = False
        finally:
            self._restart_task_payload = None
            if self._task_executor is not None:
                self._task_executor.update_task('restart', enabled=False)
            item = self._executor_tasks.get('restart')
            if item is not None:
                item.enabled = False

        if ok:
            return TaskResult(success=True)
        return TaskResult(success=False, error='重启任务执行失败')

    def _queue_restart_task(
        self,
        *,
        source_task: str,
        err_type: str,
        attempt: int,
        limit: int,
    ) -> bool:
        """入队一次 `restart` 任务（NIKKE 风格）。"""
        executor = self._task_executor
        if executor is None:
            return False

        self._restart_task_payload = {
            'source_task': str(source_task or 'unknown'),
            'err_type': str(err_type or 'Exception'),
            'attempt': int(attempt),
            'limit': int(limit),
        }
        executor.update_task('restart', enabled=True, order_index=0)
        queued = bool(executor.task_call('restart', force_call=True))
        if not queued:
            self._restart_task_payload = None
        return queued

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

        if task_name == 'restart' and not result.success:
            reason = str(result.error or '重启任务失败，已停止任务')
            self._request_manual_takeover(reason=reason)
            return

        # 对齐 NIKKE：daily 任务的下次执行时间由执行器统一按 daily_time 计算，
        # 任务实现层无需每次显式返回 next_run_seconds。
        cfg = self._get_task_cfg(task_name)
        if (
            result.success
            and result.next_run_seconds is None
            and cfg is not None
            and cfg.trigger == TaskTriggerType.DAILY
            and self._task_executor is not None
        ):
            self._task_executor.task_delay(
                task_name,
                target_time=self._next_daily_target_time(cfg.daily_time),
            )

        if result.success:
            self._task_exception_retry_counts.pop(task_name, None)

        self._persist_task_next_run(task_name)

        status_text = '成功' if result.success else '失败'
        next_run_text = self._format_task_next_run(self._executor_tasks.get(task_name))
        display_name = self._task_display_name(task_name)
        msg = f'[{display_name}] 任务完成: {status_text} | 下次执行: {next_run_text}'
        if not result.success and result.error:
            msg = f'{msg} | 错误: {result.error}'
        logger.info(msg)

        self._emit_stats_now()

    def _request_manual_takeover(self, reason: str):
        """请求人工接管：异步停止引擎，避免执行器线程自停造成 join 冲突。"""
        if self._fatal_error_stop_requested:
            return
        self._fatal_error_stop_requested = True
        message = str(reason or '检测到致命异常，请手动处理')
        logger.critical(message)

        def _stop_engine():
            try:
                self.stop()
            except Exception as exc:
                logger.debug(f'fatal stop failed: {exc}')

        threading.Thread(target=_stop_engine, name='FatalErrorStopper', daemon=True).start()
