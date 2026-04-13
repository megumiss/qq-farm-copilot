"""OCR provider: lazy create and cache OCRTool by scope/key."""

from __future__ import annotations

from threading import Lock

from utils.ocr_utils import OCRTool

_ocr_cache: dict[tuple[str, str], OCRTool] = {}
_ocr_cache_lock = Lock()


def _normalize_scope(scope: str | None) -> str:
    """规范化缓存 scope。"""
    text = str(scope or '').strip().lower()
    return text or 'engine'


def _normalize_key(key: str | None) -> str:
    """规范化缓存 key。"""
    text = str(key or '').strip()
    return text or 'default'


def get_ocr_tool(scope: str = 'engine', key: str | None = None) -> OCRTool:
    """按 `(scope, key)` 获取 OCRTool（懒加载并缓存）。"""
    cache_key = (_normalize_scope(scope), _normalize_key(key))
    with _ocr_cache_lock:
        tool = _ocr_cache.get(cache_key)
        if tool is not None:
            return tool
        tool = OCRTool()
        _ocr_cache[cache_key] = tool
        return tool


def clear_ocr_tool(scope: str = 'engine', key: str | None = None) -> None:
    """清理指定 `(scope, key)` 的 OCRTool 缓存。"""
    cache_key = (_normalize_scope(scope), _normalize_key(key))
    with _ocr_cache_lock:
        _ocr_cache.pop(cache_key, None)


def clear_all_ocr_tools() -> None:
    """清理全部 OCRTool 缓存。"""
    with _ocr_cache_lock:
        _ocr_cache.clear()
