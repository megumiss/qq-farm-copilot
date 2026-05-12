"""任务配置强类型视图（自动生成，请勿手改）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

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
    daily_times: list[str]
    enabled_time_range: str
    next_run: str
    _task_call: TaskCall = field(repr=False, compare=False)

    def call(self, force_call: bool = True) -> bool:
        return bool(self._task_call(bool(force_call)))


@dataclass(slots=True)
class MainFeatures:
    auto_harvest: bool = True
    auto_plant: bool = False
    auto_weed: bool = True
    auto_water: bool = True
    auto_bug: bool = True
    auto_expand: bool = True
    auto_upgrade: bool = True
    auto_fertilize: bool = False


@dataclass(slots=True)
class FriendFeatures:
    auto_steal: bool = False
    steal_enabled_time_range: str = '00:00:00-23:59:59'
    steal_limit_count: int = 0
    auto_help: bool = True
    help_only_guard_dog: bool = False
    help_enabled_time_range: str = '00:00:00-23:59:59'
    help_limit_count: int = 0
    auto_accept_request: bool = True
    blacklist: list[str] = field(default_factory=list)
    steal_stats: bool = False


@dataclass(slots=True)
class RewardFeatures:
    claim_growth_task: bool = False
    claim_daily_task: bool = True


@dataclass(slots=True)
class GiftFeatures:
    auto_svip_gift: bool = True
    auto_mall_gift: bool = True
    auto_mail: bool = True


@dataclass(slots=True)
class MainTaskView(TaskViewBase):
    feature: MainFeatures = field(default_factory=MainFeatures)


@dataclass(slots=True)
class FriendTaskView(TaskViewBase):
    feature: FriendFeatures = field(default_factory=FriendFeatures)


@dataclass(slots=True)
class ShareTaskView(TaskViewBase):
    feature: EmptyFeatures = field(default_factory=EmptyFeatures)


@dataclass(slots=True)
class RewardTaskView(TaskViewBase):
    feature: RewardFeatures = field(default_factory=RewardFeatures)


@dataclass(slots=True)
class GiftTaskView(TaskViewBase):
    feature: GiftFeatures = field(default_factory=GiftFeatures)


@dataclass(slots=True)
class EventShopTaskView(TaskViewBase):
    feature: EmptyFeatures = field(default_factory=EmptyFeatures)


@dataclass(slots=True)
class SellTaskView(TaskViewBase):
    feature: EmptyFeatures = field(default_factory=EmptyFeatures)


@dataclass(slots=True)
class LandScanTaskView(TaskViewBase):
    feature: EmptyFeatures = field(default_factory=EmptyFeatures)


@dataclass(slots=True)
class RestartTaskView(TaskViewBase):
    feature: EmptyFeatures = field(default_factory=EmptyFeatures)


TASK_FEATURE_CLASS_MAP = {
    'main': MainFeatures,
    'friend': FriendFeatures,
    'share': EmptyFeatures,
    'reward': RewardFeatures,
    'gift': GiftFeatures,
    'event_shop': EmptyFeatures,
    'sell': EmptyFeatures,
    'land_scan': EmptyFeatures,
    'restart': EmptyFeatures,
}

TASK_VIEW_CLASS_MAP = {
    'main': MainTaskView,
    'friend': FriendTaskView,
    'share': ShareTaskView,
    'reward': RewardTaskView,
    'gift': GiftTaskView,
    'event_shop': EventShopTaskView,
    'sell': SellTaskView,
    'land_scan': LandScanTaskView,
    'restart': RestartTaskView,
}
