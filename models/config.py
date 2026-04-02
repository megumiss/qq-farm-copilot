"""应用配置模型"""
import json
import os
from enum import Enum
from pydantic import BaseModel, Field, PrivateAttr, field_validator


class PlantMode(str, Enum):
    PREFERRED = "preferred"          # 用户手动指定作物
    BEST_EXP_RATE = "best_exp_rate"  # 当前等级下单位时间经验最高


class SellMode(str, Enum):
    BATCH_ALL = "batch_all"        # 批量全部出售


class WindowPosition(str, Enum):
    LEFT_CENTER = "left_center"
    CENTER = "center"
    RIGHT_CENTER = "right_center"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    LEFT_BOTTOM = "left_bottom"
    RIGHT_BOTTOM = "right_bottom"


class WindowPlatform(str, Enum):
    QQ = "qq"
    WECHAT = "wechat"


class FeaturesConfig(BaseModel):
    auto_harvest: bool = True
    auto_plant: bool = True
    auto_weed: bool = True
    auto_water: bool = True
    auto_bug: bool = True
    auto_fertilize: bool = False
    auto_sell: bool = True
    auto_steal: bool = False
    auto_help: bool = True
    auto_bad: bool = False
    auto_task: bool = True
    auto_upgrade: bool = True


class SellConfig(BaseModel):
    mode: SellMode = SellMode.BATCH_ALL

    @field_validator("mode", mode="before")
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


class ScheduleConfig(BaseModel):
    farm_check_minutes: int = 1
    friend_check_minutes: int = 30
    task_check_minutes: int = 60


class PlantingConfig(BaseModel):
    strategy: PlantMode = PlantMode.BEST_EXP_RATE
    preferred_crop: str = "白萝卜"  # strategy=preferred 时使用
    player_level: int = 10
    buy_quantity: int = 50
    window_platform: WindowPlatform = WindowPlatform.QQ
    window_position: WindowPosition = WindowPosition.LEFT_CENTER


class AppConfig(BaseModel):
    window_title_keyword: str = "QQ经典农场"
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    screenshot: ScreenshotConfig = Field(default_factory=ScreenshotConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    planting: PlantingConfig = Field(default_factory=PlantingConfig)
    sell: SellConfig = Field(default_factory=SellConfig)

    _config_path: str = PrivateAttr(default="")

    @classmethod
    def load(cls, path: str = "config.json") -> "AppConfig":
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = cls(**data)
        else:
            config = cls()
        config._config_path = path
        return config

    def save(self, path: str | None = None):
        p = path or self._config_path or "config.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, ensure_ascii=False, indent=2)
