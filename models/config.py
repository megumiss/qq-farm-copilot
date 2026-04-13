"""应用配置模型"""

import json
import os
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr, field_validator

from utils.app_paths import (
    ensure_user_configs,
    instance_config_file,
    resolve_config_file,
)


class PlantMode(str, Enum):
    """封装 `PlantMode` 相关的数据与行为。"""

    PREFERRED = 'preferred'  # 用户手动指定作物
    BEST_EXP_RATE = 'best_exp_rate'  # 当前等级下单位时间经验最高
    LATEST_LEVEL = 'latest_level'  # 当前等级下可种植的最高等级作物


class SellMode(str, Enum):
    """封装 `SellMode` 相关的数据与行为。"""

    BATCH_ALL = 'batch_all'  # 批量全部出售


class WindowPosition(str, Enum):
    """封装 `WindowPosition` 相关的数据与行为。"""

    LEFT_CENTER = 'left_center'
    CENTER = 'center'
    RIGHT_CENTER = 'right_center'
    TOP_LEFT = 'top_left'
    TOP_RIGHT = 'top_right'
    LEFT_BOTTOM = 'left_bottom'
    RIGHT_BOTTOM = 'right_bottom'


class WindowPlatform(str, Enum):
    """封装 `WindowPlatform` 相关的数据与行为。"""

    QQ = 'qq'
    WECHAT = 'wechat'


class RunMode(str, Enum):
    """封装 `RunMode` 相关的数据与行为。"""

    FOREGROUND = 'foreground'
    BACKGROUND = 'background'


def is_background_mode_supported(window_platform: WindowPlatform | str) -> bool:
    """判断当前平台是否支持后台模式。"""
    _ = window_platform
    return True


def resolve_effective_run_mode(run_mode: RunMode | str, window_platform: WindowPlatform | str) -> RunMode:
    """根据配置计算生效运行模式。"""
    _ = window_platform
    mode = run_mode if isinstance(run_mode, RunMode) else RunMode(str(run_mode))
    return mode


class SellConfig(BaseModel):
    """定义 `SellConfig` 的配置数据结构与默认值。"""

    mode: SellMode = SellMode.BATCH_ALL

    @field_validator('mode', mode='before')
    @classmethod
    def _force_batch_mode(cls, _value):
        """执行 `force batch mode` 相关处理。"""
        return SellMode.BATCH_ALL


class SafetyConfig(BaseModel):
    """定义 `SafetyConfig` 的配置数据结构与默认值。"""

    random_delay_min: float = 0.1
    random_delay_max: float = 0.3
    click_offset_range: int = 5
    max_actions_per_round: int = 20
    run_mode: RunMode = RunMode.BACKGROUND
    debug_log_enabled: bool = False


class ScreenshotConfig(BaseModel):
    """定义 `ScreenshotConfig` 的配置数据结构与默认值。"""

    save_history: bool = True
    max_history_count: int = 50


class TaskTriggerType(str, Enum):
    """封装 `TaskTriggerType` 任务的执行入口与步骤。"""

    INTERVAL = 'interval'
    DAILY = 'daily'


DEFAULT_MIN_TASK_INTERVAL_SECONDS = 5
DEFAULT_TASK_NEXT_RUN = '2026-01-01 00:00'
DEFAULT_TASK_ENABLED_TIME_RANGE = '00:00:00-23:59:59'


def _normalize_hh_mm_text(text: str, fallback: str) -> str:
    """将输入文本规范化为 `HH:MM`。"""
    if not re.match(r'^\d{2}:\d{2}$', text):
        return fallback
    hour = int(text[:2])
    minute = int(text[3:5])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return fallback
    return f'{hour:02d}:{minute:02d}'


def _normalize_hh_mm_ss_text(text: str, fallback: str) -> str:
    """将输入文本规范化为 `HH:MM:SS`。"""
    if not re.match(r'^\d{2}:\d{2}:\d{2}$', text):
        return fallback
    hour = int(text[:2])
    minute = int(text[3:5])
    second = int(text[6:8])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59 or second < 0 or second > 59:
        return fallback
    return f'{hour:02d}:{minute:02d}:{second:02d}'


def normalize_task_enabled_time_range(value: Any) -> str:
    """规范化任务启用时间段为 `HH:MM:SS-HH:MM:SS`。"""
    raw = str(value or DEFAULT_TASK_ENABLED_TIME_RANGE).strip()
    for sep in ('-', '~', '～', '—'):
        if sep not in raw:
            continue
        start_raw, end_raw = raw.split(sep, 1)
        start = _normalize_hh_mm_ss_text(start_raw.strip(), '')
        end = _normalize_hh_mm_ss_text(end_raw.strip(), '')
        if start and end:
            return f'{start}-{end}'
        return DEFAULT_TASK_ENABLED_TIME_RANGE
    return DEFAULT_TASK_ENABLED_TIME_RANGE


def resolve_task_min_interval_seconds(executor_cfg) -> int:
    """解析任务最小执行间隔（秒）。"""
    try:
        value = int(getattr(executor_cfg, 'min_task_interval_seconds', DEFAULT_MIN_TASK_INTERVAL_SECONDS))
    except Exception:
        value = DEFAULT_MIN_TASK_INTERVAL_SECONDS
    return max(1, value)


class TaskScheduleItemConfig(BaseModel):
    """定义 `TaskScheduleItemConfig` 的配置数据结构与默认值。"""

    enabled: bool = True
    priority: int = 10
    trigger: TaskTriggerType = TaskTriggerType.INTERVAL
    interval_seconds: int = 1800
    enabled_time_range: str = DEFAULT_TASK_ENABLED_TIME_RANGE
    daily_time: str = '00:01'
    next_run: str = DEFAULT_TASK_NEXT_RUN
    failure_interval_seconds: int = 60
    features: dict[str, Any] = Field(default_factory=dict)

    @field_validator('priority', mode='before')
    @classmethod
    def _normalize_priority(cls, value):
        """规范化 `priority` 输入值。"""
        return max(1, int(value))

    @field_validator('interval_seconds', mode='before')
    @classmethod
    def _normalize_interval(cls, value):
        """规范化 `interval` 输入值。"""
        return max(1, int(value))

    @field_validator('failure_interval_seconds', mode='before')
    @classmethod
    def _normalize_failure_interval(cls, value):
        """规范化 `failure_interval` 输入值。"""
        return max(1, int(value))

    @field_validator('daily_time', mode='before')
    @classmethod
    def _normalize_daily_time(cls, value):
        """规范化 `daily_time` 输入值。"""
        text = str(value or '00:01').strip()
        return _normalize_hh_mm_text(text, '00:01')

    @field_validator('enabled_time_range', mode='before')
    @classmethod
    def _normalize_enabled_time_range(cls, value):
        """规范化 `enabled_time_range` 输入值。"""
        return normalize_task_enabled_time_range(value)

    @field_validator('next_run', mode='before')
    @classmethod
    def _normalize_next_run(cls, value):
        """规范化 `next_run` 输入值。"""
        if isinstance(value, datetime):
            return value.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        text = str(value or DEFAULT_TASK_NEXT_RUN).strip().replace('T', ' ')
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.strftime(fmt)
            except Exception:
                continue
        return DEFAULT_TASK_NEXT_RUN

    @field_validator('features', mode='before')
    @classmethod
    def _normalize_features(cls, value):
        """规范化 `features` 输入值。"""
        if not isinstance(value, dict):
            return {}
        out: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if isinstance(item, list):
                cleaned: list[str] = []
                seen: set[str] = set()
                for raw in item:
                    text = str(raw or '').strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    cleaned.append(text)
                out[name] = cleaned
                continue
            out[name] = bool(item)
        return out


class ExecutorConfig(BaseModel):
    """定义 `ExecutorConfig` 的配置数据结构与默认值。"""

    min_task_interval_seconds: int = DEFAULT_MIN_TASK_INTERVAL_SECONDS
    empty_queue_policy: str = 'stay'
    default_success_interval: int = DEFAULT_MIN_TASK_INTERVAL_SECONDS
    default_failure_interval: int = DEFAULT_MIN_TASK_INTERVAL_SECONDS
    max_failures: int = 3

    @field_validator('empty_queue_policy', mode='before')
    @classmethod
    def _normalize_empty_queue_policy(cls, value):
        """规范化 `empty_queue_policy` 输入值。"""
        text = str(value or 'stay').strip().lower()
        if text not in {'stay', 'goto_main'}:
            return 'stay'
        return text

    @field_validator('min_task_interval_seconds', mode='before')
    @classmethod
    def _normalize_min_task_interval(cls, value):
        """规范化任务最小执行间隔（秒）。"""
        return max(1, int(value))

    @field_validator('default_success_interval', 'default_failure_interval', mode='before')
    @classmethod
    def _normalize_default_intervals(cls, value):
        """规范化执行器默认间隔（秒）。"""
        return max(1, int(value))


class PlantingConfig(BaseModel):
    """定义 `PlantingConfig` 的配置数据结构与默认值。"""

    strategy: PlantMode = PlantMode.LATEST_LEVEL
    warehouse_first: bool = True
    preferred_crop: str = '白萝卜'
    player_level: int = 10
    level_ocr_enabled: bool = True
    window_platform: WindowPlatform = WindowPlatform.QQ
    window_position: WindowPosition = WindowPosition.LEFT_CENTER

    @field_validator('player_level', mode='before')
    @classmethod
    def _normalize_player_level(cls, value):
        """规范化 `player_level` 输入值。"""
        try:
            level = int(value)
        except Exception:
            level = 1
        return max(1, min(999, level))


class AppConfig(BaseModel):
    """定义 `AppConfig` 的配置数据结构与默认值。"""

    window_title_keyword: str = 'QQ经典农场'
    window_select_rule: str = 'auto'
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    screenshot: ScreenshotConfig = Field(default_factory=ScreenshotConfig)
    tasks: dict[str, TaskScheduleItemConfig] = Field(default_factory=dict)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    planting: PlantingConfig = Field(default_factory=PlantingConfig)
    sell: SellConfig = Field(default_factory=SellConfig)

    _config_path: str = PrivateAttr(default='')
    _template_path: str = PrivateAttr(default='')

    @staticmethod
    def _atomic_write_json(path: str | Path, data: dict) -> None:
        """以原子替换方式写入 JSON。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + f'.tmp.{os.getpid()}')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, target)

    @staticmethod
    def _read_json_file(path: str) -> dict:
        """读取 JSON 文件并返回字典对象。"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}

    @classmethod
    def _resolve_template_path(cls, config_path: str, template_path: str | None = None) -> str:
        """解析并计算 `template_path` 的最终结果。"""
        if template_path:
            return str(template_path)
        _ = config_path
        # 模板优先使用内置版本，避免用户目录旧模板缺失新字段导致 UI/功能不更新。
        return str(resolve_config_file('config.template.json', prefer_user=False))

    @classmethod
    def _resolve_config_path(cls, path: str | None = None) -> str:
        """解析并计算用户配置文件路径。"""
        raw = str(path or '').strip()
        if raw:
            candidate = Path(raw)
            if candidate.is_absolute():
                return str(candidate)

            norm = raw.replace('\\', '/')
            if norm.startswith('configs/'):
                # 不再使用项目根共享配置，统一回落到 default 实例配置。
                return str(instance_config_file('default'))
            return str(candidate.resolve())
        return str(instance_config_file('default'))

    @classmethod
    def _deep_merge_dict(cls, base: dict, override: dict) -> dict:
        """递归合并两层字典配置。"""
        out = dict(base)
        for key, value in (override or {}).items():
            if key in out and isinstance(out[key], dict) and isinstance(value, dict):
                out[key] = cls._deep_merge_dict(out[key], value)
            else:
                out[key] = value
        return out

    @classmethod
    def _same_structure_and_order(cls, left, right) -> bool:
        """递归比较配置内容与键顺序是否一致。"""
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            left_keys = list(left.keys())
            right_keys = list(right.keys())
            if left_keys != right_keys:
                return False
            for key in left_keys:
                if not cls._same_structure_and_order(left[key], right[key]):
                    return False
            return True
        if isinstance(left, list):
            if len(left) != len(right):
                return False
            for idx, item in enumerate(left):
                if not cls._same_structure_and_order(item, right[idx]):
                    return False
            return True
        return left == right

    @field_validator('tasks', mode='before')
    @classmethod
    def _normalize_tasks(cls, value):
        """规范化 `tasks` 输入值。"""
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        try:
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
        return {}

    @field_validator('window_select_rule', mode='before')
    @classmethod
    def _normalize_window_select_rule(cls, value):
        """规范化 `window_select_rule` 输入值。"""
        text = str(value or 'auto').strip().lower()
        if not text or text == 'auto':
            return 'auto'
        if text.startswith('index:'):
            suffix = text.split(':', 1)[1]
            try:
                index = int(suffix)
            except Exception:
                return 'auto'
            if index >= 0:
                return f'index:{index}'
        return 'auto'

    @classmethod
    def load(cls, path: str | None = None, template_path: str | None = None) -> 'AppConfig':
        """从配置文件加载并构建配置对象。"""
        ensure_user_configs()

        config_file = cls._resolve_config_path(path)
        template_file = cls._resolve_template_path(config_file, template_path)
        template_data: dict = {}
        if template_file and os.path.exists(template_file):
            try:
                template_data = cls._read_json_file(template_file)
            except Exception:
                template_data = {}

        if os.path.exists(config_file):
            user_data = cls._read_json_file(config_file)
            data = cls._deep_merge_dict(template_data, user_data)
            config = cls(**data)
            # 自动同步模板新增字段与键顺序，避免老用户本地配置顺序/结构漂移。
            normalized = config.model_dump()
            if not cls._same_structure_and_order(user_data, normalized):
                cls._atomic_write_json(config_file, normalized)
        else:
            if template_data:
                config = cls(**template_data)
            else:
                config = cls()
        config._config_path = config_file
        config._template_path = template_file
        return config

    def save(self, path: str | None = None):
        """将当前配置对象写回文件。"""
        p = self._resolve_config_path(path or self._config_path)
        self._atomic_write_json(p, self.model_dump())
