"""gui GUI 加载器。"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Callable

from models.config import AppConfig

GUI_MODULE = 'gui.main_window_core'
GUI_API_VERSION = 2
BOOT_PROTOCOL = 1
BOOT_CALLER = 'gui.window_loader'
BOOT_SIGNATURE = 'qqfarm-gui-boot-v1'


def _load_builder() -> Callable[[Any, dict[str, Any]], Any]:
    module = None
    last_exc: Exception | None = None
    try:
        module = import_module(GUI_MODULE)
    except Exception as exc:
        last_exc = exc
    if module is None:
        raise RuntimeError('缺少 gui 核心模块，无法启动。') from last_exc
    module_api = getattr(module, 'GUI_API_VERSION', None)
    if module_api != GUI_API_VERSION:
        raise RuntimeError('gui GUI API 版本不匹配')
    builder = getattr(module, 'build_main_window', None)
    if not callable(builder):
        raise RuntimeError('gui 缺少 build_main_window 入口')
    return builder


def build_main_window(config: AppConfig):
    builder = _load_builder()
    return builder(
        config,
        {
            'protocol': BOOT_PROTOCOL,
            'caller': BOOT_CALLER,
            'signature': BOOT_SIGNATURE,
        },
    )
