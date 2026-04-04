"""nklite 任务步骤结果。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepResult:
    """封装 `StepResult` 相关的数据与行为。"""
    action: str | None = None
    actions: list[str] = field(default_factory=list)

    @classmethod
    def from_value(cls, value) -> 'StepResult':
        """执行 `from value` 相关处理。"""
        if isinstance(value, StepResult):
            return value
        if value is None:
            return cls()
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return cls()
            return cls(action=text, actions=[text])
        if isinstance(value, list):
            texts = [str(v).strip() for v in value if str(v).strip()]
            return cls(action=(texts[-1] if texts else None), actions=texts)
        text = str(value).strip()
        if not text:
            return cls()
        return cls(action=text, actions=[text])
