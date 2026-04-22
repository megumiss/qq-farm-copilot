"""任务基类：统一任务上下文类型声明。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

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

    def get_features(self, task_name: str) -> dict[str, Any]:
        """获取任务特性开关字典。"""
        return self.engine.get_task_features(task_name)

    @staticmethod
    def has_feature(features: Mapping[str, Any] | None, key: str, default: bool = False) -> bool:
        """读取特性开关并归一化为 bool。"""
        if not isinstance(features, Mapping):
            return bool(default)
        return bool(features.get(str(key), default))

    def is_feature_enabled(self, task_name: str, key: str, default: bool = False) -> bool:
        """按任务名读取某个特性开关。"""
        return self.has_feature(self.get_features(task_name), key, default=default)

    @staticmethod
    def parse_truthy(value: Any) -> bool:
        """将常见配置值解析为布尔值。"""
        if isinstance(value, bool):
            return value
        text = str(value or '').strip().lower()
        return text in {'1', 'true', 'yes', 'y', 'on'}

    @staticmethod
    def parse_model_item(item: Any) -> dict[str, Any]:
        """将配置项解析为字典副本。"""
        if isinstance(item, dict):
            return dict(item)
        try:
            dumped = item.model_dump()
        except Exception:
            dumped = {}
        return dumped if isinstance(dumped, dict) else {}

    def parse_land_detail_plots(self) -> list[dict[str, Any]]:
        """解析土地详情 `config.land.plots`。"""
        plots_raw = getattr(getattr(self.engine.config, 'land', None), 'plots', [])
        if not isinstance(plots_raw, list) or not plots_raw:
            return []

        parsed: list[dict[str, Any]] = []
        for idx, raw in enumerate(plots_raw, start=1):
            item = self.parse_model_item(raw)
            if not item:
                continue
            item['source_index'] = int(item.get('source_index') or idx)
            item['plot_id'] = str(item.get('plot_id', '') or '').strip()
            parsed.append(item)
        return parsed

    def parse_land_detail_plots_by_flag(self, flag: str, default: bool = False) -> list[dict[str, Any]]:
        """按布尔标记过滤土地详情地块。"""
        key = str(flag or '').strip()
        if not key:
            return []
        return [item for item in self.parse_land_detail_plots() if self.parse_truthy(item.get(key, default))]

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
