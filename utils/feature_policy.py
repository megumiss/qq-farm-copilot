"""功能策略：统一维护强制禁用的 feature。"""

from __future__ import annotations

# 仅需维护这一处：任务名 -> 强制禁用 feature 名集合
FORCED_OFF_FEATURES_BY_TASK: dict[str, set[str]] = {
    'main': { 'auto_upgrade', 'auto_fertilize'},
    'share': {'auto_task'},
}


def get_forced_off_features(task_name: str) -> set[str]:
    """返回某任务下被强制禁用的功能集合。"""
    return FORCED_OFF_FEATURES_BY_TASK.get(str(task_name), set())


def is_feature_forced_off(task_name: str, feature_name: str) -> bool:
    """判断某个功能是否在强制禁用列表中。"""
    return str(feature_name) in get_forced_off_features(str(task_name))
