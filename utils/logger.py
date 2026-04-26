"""日志系统 - 同时输出到文件和GUI"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger
from PyQt6.QtCore import QObject, pyqtSignal

from utils.app_paths import APP_SETTINGS_FILENAME, user_app_dir


class LogSignal(QObject):
    """用于将日志消息发送到GUI的信号"""

    new_log = pyqtSignal(str)


_log_signal = LogSignal()
_current_log_dir = 'logs'
_debug_enabled = False
DEFAULT_LOG_RETENTION_DAYS = 7
MIN_LOG_RETENTION_DAYS = 1
MAX_LOG_RETENTION_DAYS = 365
_retention_days = DEFAULT_LOG_RETENTION_DAYS


def get_log_signal() -> LogSignal:
    """获取 `log_signal` 信息。"""
    return _log_signal


def _gui_sink(message):
    """将日志发送到GUI"""
    text = message.strip()
    if text:
        _log_signal.new_log.emit(text)


def _resolve_log_level(enable_debug: bool) -> str:
    """根据配置返回日志级别。"""
    return 'DEBUG' if bool(enable_debug) else 'INFO'


def normalize_log_retention_days(value: Any, default: int = DEFAULT_LOG_RETENTION_DAYS) -> int:
    """归一化日志保留天数。"""
    fallback = int(default) if int(default) >= MIN_LOG_RETENTION_DAYS else DEFAULT_LOG_RETENTION_DAYS
    try:
        days = int(str(value).strip())
    except Exception:
        days = fallback
    if days < MIN_LOG_RETENTION_DAYS:
        return MIN_LOG_RETENTION_DAYS
    if days > MAX_LOG_RETENTION_DAYS:
        return MAX_LOG_RETENTION_DAYS
    return days


def load_log_retention_days(app_settings_file: str | Path | None = None) -> int:
    """从 app_settings 读取日志保留天数。"""
    path = Path(app_settings_file) if app_settings_file else user_app_dir() / APP_SETTINGS_FILENAME
    try:
        text = path.read_text(encoding='utf-8')
        data = json.loads(text)
    except Exception:
        return DEFAULT_LOG_RETENTION_DAYS
    if not isinstance(data, dict):
        return DEFAULT_LOG_RETENTION_DAYS
    logging = data.get('logging')
    if not isinstance(logging, dict):
        return DEFAULT_LOG_RETENTION_DAYS
    return normalize_log_retention_days(logging.get('retention_days', DEFAULT_LOG_RETENTION_DAYS))


def cleanup_expired_logs(root_dir: str | Path, *, retention_days: int) -> dict[str, int]:
    """清理 root_dir 下 logs 目录中的过期 .log 文件。"""
    root = Path(root_dir)
    stats = {'scanned': 0, 'deleted': 0, 'failed': 0}
    days = normalize_log_retention_days(retention_days)
    expire_before = time.time() - float(days * 24 * 60 * 60)

    if not root.exists():
        return stats

    for file in root.rglob('*.log'):
        if not file.is_file():
            continue
        parts = [str(part).casefold() for part in file.parts]
        if 'logs' not in parts:
            continue
        stats['scanned'] += 1
        try:
            if file.stat().st_mtime >= expire_before:
                continue
            file.unlink()
            stats['deleted'] += 1
        except Exception:
            stats['failed'] += 1
    return stats


def setup_logger(log_dir: str = 'logs', *, enable_debug: bool = False, retention_days: int | None = None):
    """初始化日志系统"""
    global _current_log_dir, _debug_enabled, _retention_days

    _current_log_dir = str(log_dir or 'logs')
    _debug_enabled = bool(enable_debug)
    if retention_days is not None:
        _retention_days = normalize_log_retention_days(retention_days)
    else:
        _retention_days = normalize_log_retention_days(_retention_days)
    level = _resolve_log_level(_debug_enabled)

    os.makedirs(_current_log_dir, exist_ok=True)

    logger.remove()
    # 控制台输出（无控制台的 windowed exe 下，sys.stderr 可能为 None）
    if getattr(sys, 'stderr', None) is not None:
        logger.add(
            sys.stderr,
            level=level,
            format='<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}',
        )
    # 文件输出
    logger.add(
        f'{_current_log_dir}/qq_farm_copilot_{{time:YYYY-MM-DD}}.log',
        rotation='00:00',
        retention=f'{_retention_days} days',
        level=level,
        format='{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}',
        encoding='utf-8',
    )
    # GUI输出
    logger.add(_gui_sink, level=level, format='{time:HH:mm:ss} | {level:<7} | {message}')

    return logger


def update_logger_level(enable_debug: bool):
    """按新配置重建日志输出级别。"""
    return setup_logger(_current_log_dir, enable_debug=enable_debug, retention_days=_retention_days)


def switch_log_directory(log_dir: str, *, retention_days: int | None = None):
    """切换日志目录并保持当前日志级别。"""
    days = _retention_days if retention_days is None else retention_days
    return setup_logger(log_dir=log_dir, enable_debug=_debug_enabled, retention_days=days)
