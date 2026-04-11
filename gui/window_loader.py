"""GUI 加载器（fail-closed）。"""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any, Callable

GUI_MODULE = 'gui.main_window_core'
DEV_GUI_MODULE = 'private.main_window_core'
GUI_API_VERSION = 2
BOOT_PROTOCOL = 1
BOOT_CALLER = 'gui.window_loader'
BOOT_SIGNATURE = 'qqfarm-gui-boot-v1'


def _load_gui_builder() -> Callable[[Any, dict[str, Any]], Any]:
    """加载 GUI 构建函数；失败时直接抛错终止启动。"""
    module = None
    last_exc: Exception | None = None
    candidates = [GUI_MODULE]
    if os.getenv('QQFARM_ALLOW_DEV_GUI_SOURCE', '0').strip() not in {'0', 'false', 'False'}:
        candidates.append(DEV_GUI_MODULE)

    for mod_name in candidates:
        try:
            module = import_module(mod_name)
            break
        except Exception as exc:
            last_exc = exc
            continue

    if module is None:
        raise RuntimeError('缺少核心 GUI 模块，当前版本无法启动。') from last_exc

    api_version = getattr(module, 'GUI_API_VERSION', None)
    if api_version != GUI_API_VERSION:
        raise RuntimeError('GUI API 版本不匹配')

    builder = getattr(module, 'build_main_window', None)
    if not callable(builder):
        raise RuntimeError('核心 GUI 模块入口缺少。')
    return builder


def _build_boot_ctx() -> dict[str, Any]:
    """构建启动上下文，用于校验调用方版本。"""
    return {
        'protocol': BOOT_PROTOCOL,
        'caller': BOOT_CALLER,
        'signature': BOOT_SIGNATURE,
    }


def build_main_window(config: Any):
    """构建主窗口。"""
    builder = _load_gui_builder()
    return builder(config, _build_boot_ctx())
