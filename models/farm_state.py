"""农场状态数据模型"""

from enum import Enum

from pydantic import BaseModel


class ActionType(str, Enum):
    """封装 `ActionType` 相关的数据与行为。"""

    HARVEST = 'harvest'
    PLANT = 'plant'
    WATER = 'water'
    WEED = 'weed'
    BUG = 'bug'
    FERTILIZE = 'fertilize'
    REMOVE = 'remove'
    SELL = 'sell'
    STEAL = 'steal'
    HELP_WATER = 'help_water'
    HELP_WEED = 'help_weed'
    HELP_BUG = 'help_bug'
    CLOSE_POPUP = 'close_popup'
    NAVIGATE = 'navigate'


class Action(BaseModel):
    """一个待执行的操作"""

    type: str
    target_plot: int = 0
    click_position: dict = {}  # {"x": 像素x, "y": 像素y}
    priority: int = 0
    description: str = ''
    extra: dict = {}  # 额外参数，如种子名称等


class OperationResult(BaseModel):
    """操作执行结果"""

    action: Action
    success: bool = False
    message: str = ''
    timestamp: float = 0
