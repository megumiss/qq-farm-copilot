"""任务基类：统一任务上下文类型声明。"""

from __future__ import annotations

from typing import Mapping
from typing import TYPE_CHECKING

from core.engine.task.registry import TaskResult

if TYPE_CHECKING:
    from core.engine.bot.local_engine import LocalBotEngine
    from core.ui.ui import UI


class TaskBase:
    """统一持有 `engine/ui`，用于 IDE 静态跳转与补全。"""

    engine: 'LocalBotEngine'
    ui: 'UI'

    def __init__(self, engine: 'LocalBotEngine', ui: 'UI'):
        self.engine = engine
        self.ui = ui

    def get_features(self, task_name: str) -> dict[str, bool]:
        """获取任务特性开关字典。"""
        return self.engine.get_task_features(task_name)

    @staticmethod
    def has_feature(features: Mapping[str, bool] | None, key: str, default: bool = False) -> bool:
        """读取特性开关并归一化为 bool。"""
        if not isinstance(features, Mapping):
            return bool(default)
        return bool(features.get(str(key), default))

    def is_feature_enabled(self, task_name: str, key: str, default: bool = False) -> bool:
        """按任务名读取某个特性开关。"""
        return self.has_feature(self.get_features(task_name), key, default=default)

    @staticmethod
    def ok(*, next_run_seconds: int | None = None) -> TaskResult:
        """构造成功结果。"""
        return TaskResult(success=True, next_run_seconds=next_run_seconds, error='')

    @staticmethod
    def fail(error: str, *, next_run_seconds: int | None = None) -> TaskResult:
        """构造失败结果。"""
        return TaskResult(
            success=False,
            next_run_seconds=next_run_seconds,
            error=str(error or ''),
        )
