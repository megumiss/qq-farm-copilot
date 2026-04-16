"""Bot 引擎代理（主进程，NIKKE 风格进程级停止）。"""

from __future__ import annotations

import io
import multiprocessing as mp
import queue
import re
import time
import uuid
from typing import Any

from loguru import logger
from PIL import Image as PILImage
from PyQt6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, pyqtSignal

from core.engine.bot.worker import bot_worker_main
from core.platform.window_manager import WindowManager
from models.config import AppConfig, RunMode, resolve_effective_run_mode


class _SchedulerSnapshot:
    """主进程侧统计快照容器。"""

    def __init__(self):
        self._stats: dict[str, Any] = {
            'harvest': 0,
            'plant': 0,
            'water': 0,
            'weed': 0,
            'bug': 0,
            'steal': 0,
            'sell': 0,
            'total_actions': 0,
            'current_platform': '--',
            'window_id': '--',
            'current_task': '--',
            'next_task': '--',
            'next_run': '--',
            'running_tasks': 0,
            'pending_tasks': 0,
            'waiting_tasks': 0,
            'elapsed': '--',
            'state': 'idle',
        }

    def set_stats(self, stats: dict[str, Any]) -> None:
        if not isinstance(stats, dict):
            return
        self._stats = dict(stats)

    def patch_state(self, state: str) -> None:
        self._stats['state'] = str(state or 'idle')

    def get_stats(self) -> dict[str, Any]:
        return dict(self._stats)


class BotEngine(QObject):
    """GUI 侧 Bot 引擎代理：命令发到 worker，事件从 worker 回传。"""

    log_message = pyqtSignal(str)
    screenshot_updated = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    detection_result = pyqtSignal(object)
    config_updated = pyqtSignal(dict)

    def __init__(
        self,
        config: AppConfig,
        *,
        runtime_paths: dict[str, str] | None = None,
        instance_id: str = 'default',
        allow_idle_prewarm: bool = True,
    ):
        super().__init__()
        self.config = config
        self.instance_id = str(instance_id or 'default')
        self.runtime_paths = dict(runtime_paths or {})
        self.scheduler = _SchedulerSnapshot()
        self._allow_idle_prewarm = bool(allow_idle_prewarm)
        self._window_manager = WindowManager()

        self._ctx = mp.get_context('spawn')
        self._worker: mp.Process | None = None
        self._command_queue = None
        self._event_queue = None
        self._responses: dict[str, dict[str, Any]] = {}

        self._poller = QTimer(self)
        self._poller.setInterval(80)
        self._poller.timeout.connect(self._drain_events)
        self._poller.start()
        QTimer.singleShot(0, self._prewarm_worker)

    @staticmethod
    def _relay_worker_log(text: str) -> None:
        """将 worker 回传日志写入主进程 logger（文件/控制台/UI 统一）。"""
        raw = str(text or '').strip()
        if not raw:
            return

        # worker 默认格式: "HH:mm:ss | LEVEL   | message"
        parts = [part.strip() for part in raw.split('|', 2)]
        if len(parts) == 3:
            level = parts[1].upper()
            message = parts[2]
            if re.fullmatch(r'[A-Z]+', level):
                if level in {'TRACE', 'DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL'}:
                    logger.log(level, message)
                    return
        logger.info(raw)

    def _prewarm_worker(self) -> None:
        """空闲时预热 worker，减少首次点击启动等待。"""
        if not self._allow_idle_prewarm:
            return
        app = QCoreApplication.instance()
        if app is None or QCoreApplication.closingDown():
            return
        self._ensure_worker()

    def _ensure_worker(self) -> bool:
        if self._worker and self._worker.is_alive():
            return True

        try:
            self._command_queue = self._ctx.Queue()
            self._event_queue = self._ctx.Queue()
            self._worker = self._ctx.Process(
                target=bot_worker_main,
                args=(
                    self.config.model_dump(),
                    self._command_queue,
                    self._event_queue,
                    dict(self.runtime_paths),
                    self.instance_id,
                ),
                name='QQFarmWorker',
                daemon=True,
            )
            self._worker.start()
            return bool(self._worker.is_alive())
        except Exception as exc:
            self.log_message.emit(f'启动 worker 失败: {exc}')
            self._worker = None
            self._command_queue = None
            self._event_queue = None
            return False

    def _decode_image(self, raw: Any) -> PILImage.Image | None:
        if raw is None or not isinstance(raw, (bytes, bytearray)):
            return None
        try:
            with io.BytesIO(bytes(raw)) as buf:
                img = PILImage.open(buf)
                return img.convert('RGB')
        except Exception:
            return None

    def _handle_event(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return

        etype = str(event.get('type') or '').strip().lower()
        payload = event.get('data')

        if etype == 'log':
            text = str(payload or '').strip()
            if text:
                self._relay_worker_log(text)
                self.log_message.emit(text)
            return

        if etype == 'state':
            state = str(payload or 'idle')
            self.scheduler.patch_state(state)
            self.state_changed.emit(state)
            self.stats_updated.emit(self.scheduler.get_stats())
            return

        if etype == 'stats':
            if isinstance(payload, dict):
                self.scheduler.set_stats(payload)
                state = str(payload.get('state', '') or '')
                if state:
                    self.state_changed.emit(state)
                self.stats_updated.emit(self.scheduler.get_stats())
            return

        if etype == 'screenshot':
            image = self._decode_image(payload)
            if image is not None:
                self.screenshot_updated.emit(image)
            return

        if etype == 'detection':
            image = self._decode_image(payload)
            if image is not None:
                self.detection_result.emit(image)
            return

        if etype == 'config':
            if isinstance(payload, dict):
                self.config_updated.emit(dict(payload))
            return

        if etype == 'command_result':
            req_id = str(event.get('id') or '')
            if req_id:
                self._responses[req_id] = event
            return

    def _drain_events(self, max_events: int = 200) -> None:
        if self._event_queue is None:
            return

        for _ in range(max_events):
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
            self._handle_event(event)

    def _send_command(
        self,
        cmd: str,
        data: dict[str, Any] | None = None,
        *,
        wait: bool = True,
        timeout: float = 5.0,
        ensure_worker: bool = True,
    ) -> bool:
        if ensure_worker:
            if not self._ensure_worker():
                return False
        else:
            if not self._worker or not self._worker.is_alive():
                return False

        if self._command_queue is None:
            return False

        req_id = uuid.uuid4().hex
        try:
            self._command_queue.put({'id': req_id, 'cmd': str(cmd), 'data': data or {}})
        except Exception as exc:
            self.log_message.emit(f'发送命令失败 `{cmd}`: {exc}')
            return False

        if not wait:
            return True

        deadline = time.time() + max(0.1, float(timeout))
        app = QCoreApplication.instance()
        while time.time() < deadline:
            self._drain_events()
            result = self._responses.pop(req_id, None)
            if result is not None:
                ok = bool(result.get('ok'))
                if not ok:
                    err = str(result.get('error') or '').strip()
                    if err:
                        self.log_message.emit(f'命令失败 `{cmd}`: {err}')
                return ok
            if app is not None:
                app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 5)
            time.sleep(0.005)

        self.log_message.emit(f'命令超时 `{cmd}`')
        return False

    def _shutdown_worker(self, *, force: bool = True) -> None:
        worker = self._worker
        if worker is None:
            return

        if worker.is_alive():
            try:
                self._send_command('shutdown', wait=False, ensure_worker=False)
            except Exception:
                pass
            worker.join(timeout=0.2)

        if force and worker.is_alive():
            try:
                worker.terminate()
            except Exception:
                pass
            worker.join(timeout=1.0)

        if force and worker.is_alive() and hasattr(worker, 'kill'):
            try:
                worker.kill()
            except Exception:
                pass
            worker.join(timeout=0.5)

        self._worker = None
        self._command_queue = None
        self._event_queue = None
        self._responses.clear()

        self.scheduler.patch_state('idle')
        self.state_changed.emit('idle')
        self.stats_updated.emit(self.scheduler.get_stats())

    def start(self) -> bool:
        # 仅前台模式需要拉起窗口；后台模式不抢焦点。
        effective_mode = resolve_effective_run_mode(self.config.safety.run_mode, self.config.planting.window_platform)
        if effective_mode == RunMode.FOREGROUND:
            self._activate_target_window()
        cold_start = not (self._worker and self._worker.is_alive())
        start_timeout = 120.0 if cold_start else 30.0
        if cold_start:
            self.log_message.emit('引擎冷启动中，正在预热组件...')
        ok = self._send_command('start', wait=True, timeout=start_timeout, ensure_worker=True)
        if not ok:
            # 启动失败时回收空闲 worker，避免残留后台进程。
            self._shutdown_worker(force=True)
        return ok

    def _activate_target_window(self) -> None:
        """在主进程尝试拉起目标窗口到前台。"""
        try:
            platform = getattr(self.config.planting, 'window_platform', 'qq')
            platform_value = platform.value if hasattr(platform, 'value') else str(platform)
            if self._window_manager.find_window(
                self.config.window_title_keyword, self.config.window_select_rule, platform_value
            ):
                self._window_manager.activate_window()
        except Exception:
            pass

    def stop(self, *, keep_prewarm: bool = True):
        # 对齐 NIKKE：停止时进程级强停，不依赖业务侧协作取消。
        self._shutdown_worker(force=True)
        self.log_message.emit('Bot已停止')
        if keep_prewarm and self._allow_idle_prewarm:
            QTimer.singleShot(0, self._prewarm_worker)

    def pause(self):
        self._send_command('pause', wait=False, ensure_worker=False)

    def resume(self):
        self._send_command('resume', wait=False, ensure_worker=False)

    def run_once(self):
        if not self._send_command('run_once', wait=False, ensure_worker=False):
            self.log_message.emit('执行器未运行，无法立即执行')

    def update_config(self, config: AppConfig):
        self.config = config
        if self._worker and self._worker.is_alive():
            self._send_command('update_config', data=self.config.model_dump(), wait=False)

    def __del__(self):
        try:
            self._allow_idle_prewarm = False
            self._shutdown_worker(force=True)
        except Exception:
            pass
