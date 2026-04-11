"""Bot worker 子进程入口。"""

from __future__ import annotations

import io
import os
import queue
import traceback
from typing import Any

from loguru import logger
from PIL import Image as PILImage

from core.engine.bot.local_engine import LocalBotEngine
from models.config import AppConfig


def _configure_worker_logger(
    event_queue,
    enable_debug: bool,
    *,
    runtime_paths: dict[str, Any] | None = None,
    instance_id: str = 'default',
) -> None:
    """按配置重建 worker 日志输出级别。"""
    level = 'DEBUG' if bool(enable_debug) else 'INFO'
    logger.remove()
    logs_dir = str((runtime_paths or {}).get('logs_dir') or 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    logger.add(
        os.path.join(logs_dir, f'qq_farm_copilot_worker_{instance_id}_{{time:YYYY-MM-DD}}.log'),
        rotation='00:00',
        retention='7 days',
        level=level,
        format='{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}',
        encoding='utf-8',
    )
    logger.add(
        lambda m: _safe_put(event_queue, {'type': 'log', 'data': str(m).strip()}),
        level=level,
        format='{time:HH:mm:ss} | {level:<7} | {message}',
    )


def _safe_put(event_queue, payload: dict[str, Any]) -> None:
    """安全写入事件队列，避免队列异常影响主流程。"""
    try:
        event_queue.put_nowait(payload)
    except Exception:
        pass


def _load_config(raw: Any) -> AppConfig:
    """从 dict/AppConfig 构建配置对象。"""
    if isinstance(raw, AppConfig):
        return raw
    if isinstance(raw, dict):
        try:
            return AppConfig.model_validate(raw)
        except Exception:
            return AppConfig(**raw)
    return AppConfig()


def _image_to_png_bytes(image: Any) -> bytes | None:
    """将 PIL 图片序列化为 PNG 字节。"""
    if image is None or not isinstance(image, PILImage.Image):
        return None
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return buf.getvalue()


def _make_command_result(cmd_id: str, cmd: str, ok: bool, error: str = '') -> dict[str, Any]:
    """构造命令响应事件。"""
    return {
        'type': 'command_result',
        'id': cmd_id,
        'cmd': cmd,
        'ok': bool(ok),
        'error': str(error or ''),
    }


def bot_worker_main(
    initial_config: dict[str, Any],
    command_queue,
    event_queue,
    runtime_paths: dict[str, Any] | None = None,
    instance_id: str = 'default',
) -> None:
    """worker 进程主循环。"""
    config = _load_config(initial_config)
    _configure_worker_logger(
        event_queue,
        config.safety.debug_log_enabled,
        runtime_paths=runtime_paths,
        instance_id=instance_id,
    )
    engine = LocalBotEngine(config, runtime_paths=runtime_paths, instance_id=instance_id)

    def _forward_image_event(event_type: str, image: Any) -> None:
        raw = _image_to_png_bytes(image)
        if raw is None:
            return
        _safe_put(event_queue, {'type': event_type, 'data': raw})

    # 跨线程任务执行时优先走直接队列回传，避免依赖 Qt 事件循环分发信号。
    engine.emit_preview = lambda image: _forward_image_event('screenshot', image)
    engine.emit_detection_preview = lambda image: _forward_image_event('detection', image)
    engine.emit_stats = lambda stats: _safe_put(event_queue, {'type': 'stats', 'data': dict(stats or {})})

    engine.log_message.connect(lambda text: _safe_put(event_queue, {'type': 'log', 'data': str(text)}))
    engine.state_changed.connect(lambda state: _safe_put(event_queue, {'type': 'state', 'data': str(state)}))
    engine.stats_updated.connect(lambda stats: _safe_put(event_queue, {'type': 'stats', 'data': dict(stats or {})}))

    engine.screenshot_updated.connect(
        lambda image: _safe_put(
            event_queue,
            {'type': 'screenshot', 'data': _image_to_png_bytes(image)},
        )
    )
    engine.detection_result.connect(
        lambda image: _safe_put(
            event_queue,
            {'type': 'detection', 'data': _image_to_png_bytes(image)},
        )
    )

    try:
        _safe_put(event_queue, {'type': 'state', 'data': 'idle'})
        _safe_put(event_queue, {'type': 'stats', 'data': engine.scheduler.get_stats()})

        while True:
            try:
                request = command_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            except Exception:
                continue

            if not isinstance(request, dict):
                continue

            cmd_id = str(request.get('id') or '')
            cmd = str(request.get('cmd') or '').strip().lower()
            payload = request.get('data')

            if not cmd:
                _safe_put(event_queue, _make_command_result(cmd_id, cmd, False, 'empty command'))
                continue

            try:
                if cmd == 'shutdown':
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    _safe_put(event_queue, _make_command_result(cmd_id, cmd, True))
                    break

                if cmd == 'start':
                    ok = bool(engine.start())
                    _safe_put(event_queue, _make_command_result(cmd_id, cmd, ok))
                    continue

                if cmd == 'stop':
                    engine.stop()
                    _safe_put(event_queue, _make_command_result(cmd_id, cmd, True))
                    continue

                if cmd == 'pause':
                    engine.pause()
                    _safe_put(event_queue, _make_command_result(cmd_id, cmd, True))
                    continue

                if cmd == 'resume':
                    engine.resume()
                    _safe_put(event_queue, _make_command_result(cmd_id, cmd, True))
                    continue

                if cmd == 'run_once':
                    engine.run_once()
                    _safe_put(event_queue, _make_command_result(cmd_id, cmd, True))
                    continue

                if cmd == 'update_config':
                    new_cfg = _load_config(payload)
                    _configure_worker_logger(
                        event_queue,
                        new_cfg.safety.debug_log_enabled,
                        runtime_paths=runtime_paths,
                        instance_id=instance_id,
                    )
                    engine.update_config(new_cfg)
                    _safe_put(event_queue, _make_command_result(cmd_id, cmd, True))
                    continue

                _safe_put(event_queue, _make_command_result(cmd_id, cmd, False, f'unknown command: {cmd}'))
            except Exception as exc:
                logger.error(f'worker command `{cmd}` failed: {exc}')
                logger.debug(traceback.format_exc())
                _safe_put(event_queue, _make_command_result(cmd_id, cmd, False, str(exc)))
    finally:
        try:
            engine.stop()
        except Exception:
            pass
