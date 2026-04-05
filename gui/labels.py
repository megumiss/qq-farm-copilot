"""GUI 文案配置读取。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_LABELS_PATH = Path(__file__).resolve().parents[1] / 'configs' / 'ui_labels.json'


@lru_cache(maxsize=1)
def load_ui_labels() -> dict:
    """加载统一 UI 文案配置。"""
    if not _LABELS_PATH.exists():
        return {}
    try:
        data = json.loads(_LABELS_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

