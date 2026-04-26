"""根据 `configs/config.template.json` 生成任务强类型视图。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / 'configs' / 'config.template.json'
OUTPUT_PATH = ROOT / 'models' / 'task_views.py'


def to_class_name(task_name: str) -> str:
    parts = [part for part in str(task_name).strip().split('_') if part]
    if not parts:
        return 'Unknown'
    return ''.join(part[:1].upper() + part[1:] for part in parts)


def py_literal(value: Any) -> str:
    if isinstance(value, str):
        return repr(value)
    return repr(value)


def detect_field_type_and_default(name: str, value: Any) -> tuple[str, str]:
    key = str(name).strip()
    if isinstance(value, bool):
        return 'bool', f' = {str(value)}'
    if isinstance(value, int) and not isinstance(value, bool):
        return 'int', f' = {value}'
    if isinstance(value, float):
        return 'float', f' = {value}'
    if isinstance(value, str):
        return 'str', f' = {py_literal(value)}'
    if isinstance(value, list):
        cleaned = [str(item) for item in value if str(item).strip()]
        if cleaned:
            escaped = ', '.join(py_literal(item) for item in cleaned)
            return 'list[str]', f' = field(default_factory=lambda: [{escaped}])'
        return 'list[str]', ' = field(default_factory=list)'
    return 'Any', ' = None'


def build_feature_class(task_name: str, features: dict[str, Any]) -> str:
    class_name = f'{to_class_name(task_name)}Features'
    if not features:
        return ''
    lines = [f'@dataclass(slots=True)', f'class {class_name}:']
    for key, value in features.items():
        field_name = str(key).strip()
        field_type, default = detect_field_type_and_default(field_name, value)
        lines.append(f'    {field_name}: {field_type}{default}')
    lines.append('')
    return '\n'.join(lines)


def build_view_class(task_name: str, has_features: bool) -> str:
    class_name = f'{to_class_name(task_name)}TaskView'
    feature_name = f'{to_class_name(task_name)}Features' if has_features else 'EmptyFeatures'
    lines = [
        '@dataclass(slots=True)',
        f'class {class_name}(TaskViewBase):',
        f'    feature: {feature_name} = field(default_factory={feature_name})',
        '',
    ]
    return '\n'.join(lines)


def generate() -> str:
    template = json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))
    tasks = template.get('tasks', {})
    if not isinstance(tasks, dict):
        raise ValueError('invalid tasks in config.template.json')

    feature_classes: list[str] = []
    view_classes: list[str] = []
    feature_map_lines: list[str] = []
    view_map_lines: list[str] = []
    need_any = False

    for task_name, task_cfg in tasks.items():
        if not isinstance(task_cfg, dict):
            continue
        features = task_cfg.get('features', {})
        if not isinstance(features, dict):
            features = {}

        if features:
            feature_text = build_feature_class(task_name, features)
            feature_classes.append(feature_text)
            if 'Any' in feature_text:
                need_any = True
        view_classes.append(build_view_class(task_name, bool(features)))

        feature_cls_name = f'{to_class_name(task_name)}Features' if features else 'EmptyFeatures'
        view_cls_name = f'{to_class_name(task_name)}TaskView'
        feature_map_lines.append(f'    {py_literal(task_name)}: {feature_cls_name},')
        view_map_lines.append(f'    {py_literal(task_name)}: {view_cls_name},')

    typing_any = 'Any, ' if need_any else ''
    header = f'''"""任务配置强类型视图（自动生成，请勿手改）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import {typing_any}Callable

from models.config import TaskTriggerType

TaskCall = Callable[[bool], bool]


@dataclass(slots=True)
class EmptyFeatures:
    """无 feature 的任务占位类型。"""


@dataclass(slots=True)
class TaskViewBase:
    name: str
    enabled: bool
    config_enabled: bool
    trigger: TaskTriggerType | str
    interval_seconds: int
    failure_interval_seconds: int
    daily_time: str
    enabled_time_range: str
    next_run: str
    _task_call: TaskCall = field(repr=False, compare=False)

    def call(self, force_call: bool = True) -> bool:
        return bool(self._task_call(bool(force_call)))

'''

    feature_block = '\n'.join(part for part in feature_classes if part)
    if feature_block:
        feature_block = feature_block + '\n'
    view_block = '\n'.join(view_classes)

    map_block = f"""
TASK_FEATURE_CLASS_MAP = {{
{chr(10).join(feature_map_lines)}
}}

TASK_VIEW_CLASS_MAP = {{
{chr(10).join(view_map_lines)}
}}
"""

    return header + feature_block + view_block + map_block


def main() -> None:
    content = generate()
    OUTPUT_PATH.write_text(content, encoding='utf-8', newline='\n')
    print(f'generated: {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
