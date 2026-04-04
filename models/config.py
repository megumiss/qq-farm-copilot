"""应用配置模型"""

import json
import os
import re
from enum import Enum

from pydantic import BaseModel, Field, PrivateAttr, field_validator


class PlantMode(str, Enum):
    PREFERRED = 'preferred'  # 用户手动指定作物
    BEST_EXP_RATE = 'best_exp_rate'  # 当前等级下单位时间经验最高


class SellMode(str, Enum):
    BATCH_ALL = 'batch_all'  # 批量全部出售


class WindowPosition(str, Enum):
    LEFT_CENTER = 'left_center'
    CENTER = 'center'
    RIGHT_CENTER = 'right_center'
    TOP_LEFT = 'top_left'
    TOP_RIGHT = 'top_right'
    LEFT_BOTTOM = 'left_bottom'
    RIGHT_BOTTOM = 'right_bottom'


class WindowPlatform(str, Enum):
    QQ = 'qq'
    WECHAT = 'wechat'


class SellConfig(BaseModel):
    mode: SellMode = SellMode.BATCH_ALL

    @field_validator('mode', mode='before')
    @classmethod
    def _force_batch_mode(cls, _value):
        return SellMode.BATCH_ALL


class SafetyConfig(BaseModel):
    random_delay_min: float = 0.1
    random_delay_max: float = 0.3
    click_offset_range: int = 5
    max_actions_per_round: int = 20


class ScreenshotConfig(BaseModel):
    quality: int = 80
    save_history: bool = True
    max_history_count: int = 50


class TaskTriggerType(str, Enum):
    INTERVAL = 'interval'
    DAILY = 'daily'


class TaskScheduleItemConfig(BaseModel):
    enabled: bool = True
    trigger: TaskTriggerType = TaskTriggerType.INTERVAL
    interval_seconds: int = 1800
    daily_time: str = '04:00'
    failure_interval_seconds: int = 60
    features: dict[str, bool] = Field(default_factory=dict)

    @field_validator('interval_seconds', mode='before')
    @classmethod
    def _normalize_interval(cls, value):
        return max(1, int(value))

    @field_validator('failure_interval_seconds', mode='before')
    @classmethod
    def _normalize_failure_interval(cls, value):
        return max(1, int(value))

    @field_validator('daily_time', mode='before')
    @classmethod
    def _normalize_daily_time(cls, value):
        text = str(value or '04:00').strip()
        if not re.match(r'^\d{2}:\d{2}$', text):
            return '04:00'
        hour = int(text[:2])
        minute = int(text[3:5])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return '04:00'
        return f'{hour:02d}:{minute:02d}'

    @field_validator('features', mode='before')
    @classmethod
    def _normalize_features(cls, value):
        if not isinstance(value, dict):
            return {}
        return {str(k): bool(v) for k, v in value.items()}


class TasksConfig(BaseModel):
    farm_main: TaskScheduleItemConfig = Field(
        default_factory=lambda: TaskScheduleItemConfig(
            enabled=True,
            trigger=TaskTriggerType.INTERVAL,
            interval_seconds=60,
            daily_time='04:00',
            failure_interval_seconds=30,
            features={
                'auto_harvest': True,
                'auto_plant': True,
                'auto_weed': True,
                'auto_water': True,
                'auto_bug': True,
                'auto_sell': True,
                'auto_upgrade': True,
                'auto_fertilize': False,
                'auto_bad': False,
            },
        )
    )
    friend: TaskScheduleItemConfig = Field(
        default_factory=lambda: TaskScheduleItemConfig(
            enabled=True,
            trigger=TaskTriggerType.INTERVAL,
            interval_seconds=1800,
            daily_time='04:00',
            failure_interval_seconds=60,
            features={
                'auto_help': True,
                'auto_steal': False,
            },
        )
    )
    share: TaskScheduleItemConfig = Field(
        default_factory=lambda: TaskScheduleItemConfig(
            enabled=True,
            trigger=TaskTriggerType.DAILY,
            interval_seconds=86400,
            daily_time='04:00',
            failure_interval_seconds=300,
            features={
                'auto_task': True,
            },
        )
    )


class ExecutorConfig(BaseModel):
    empty_queue_policy: str = 'stay'
    default_success_interval: int = 30
    default_failure_interval: int = 30
    max_failures: int = 3

    @field_validator('empty_queue_policy', mode='before')
    @classmethod
    def _normalize_empty_queue_policy(cls, value):
        text = str(value or 'stay').strip().lower()
        if text not in {'stay', 'goto_main'}:
            return 'stay'
        return text


class PlantingConfig(BaseModel):
    strategy: PlantMode = PlantMode.BEST_EXP_RATE
    preferred_crop: str = '白萝卜'  # strategy=preferred 时使用
    player_level: int = 10
    window_platform: WindowPlatform = WindowPlatform.QQ
    window_position: WindowPosition = WindowPosition.LEFT_CENTER


class AppConfig(BaseModel):
    window_title_keyword: str = 'QQ经典农场'
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    screenshot: ScreenshotConfig = Field(default_factory=ScreenshotConfig)
    tasks: TasksConfig = Field(default_factory=TasksConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    planting: PlantingConfig = Field(default_factory=PlantingConfig)
    sell: SellConfig = Field(default_factory=SellConfig)

    _config_path: str = PrivateAttr(default='')
    _template_path: str = PrivateAttr(default='')

    @staticmethod
    def _read_json_file(path: str) -> dict:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}

    @classmethod
    def _resolve_template_path(cls, config_path: str, template_path: str | None = None) -> str:
        if template_path:
            return str(template_path)
        _ = config_path
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, 'configs', 'config.template.json')

    @classmethod
    def _deep_merge_dict(cls, base: dict, override: dict) -> dict:
        out = dict(base)
        for key, value in (override or {}).items():
            if key in out and isinstance(out[key], dict) and isinstance(value, dict):
                out[key] = cls._deep_merge_dict(out[key], value)
            else:
                out[key] = value
        return out

    @classmethod
    def load(cls, path: str = 'configs/config.json', template_path: str | None = None) -> 'AppConfig':
        template_file = cls._resolve_template_path(path, template_path)
        template_data: dict = {}
        if template_file and os.path.exists(template_file):
            try:
                template_data = cls._read_json_file(template_file)
            except Exception:
                template_data = {}

        if os.path.exists(path):
            user_data = cls._read_json_file(path)
            data = cls._deep_merge_dict(template_data, user_data)
            config = cls(**data)
        else:
            if template_data:
                config = cls(**template_data)
            else:
                config = cls()
        config._config_path = path
        config._template_path = template_file
        return config

    def save(self, path: str | None = None):
        p = path or self._config_path or 'configs/config.json'
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(self.model_dump(), f, ensure_ascii=False, indent=2)
