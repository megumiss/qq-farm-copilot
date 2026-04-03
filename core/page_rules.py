"""页面规则加载：页面检查器与导航器共享配置。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


def load_page_rules(path: str = "configs/page_rules.json") -> dict[str, Any]:
    rules_path = Path(path)
    if not rules_path.exists():
        logger.warning(f"页面规则文件不存在: {rules_path}")
        return {}
    try:
        raw = json.loads(rules_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            logger.warning(f"页面规则文件格式错误(非对象): {rules_path}")
            return {}
        return raw
    except Exception as exc:
        logger.warning(f"加载页面规则失败: {rules_path}, error={exc}")
        return {}
