"""Bot 引擎入口。"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from core.engine.bot.executor_mixin import BotExecutorMixin
from core.engine.bot.init_mixin import BotInitMixin
from core.engine.bot.runtime_mixin import BotRuntimeMixin
from core.engine.bot.task_entry_mixin import BotTaskEntryMixin
from core.engine.bot.vision_mixin import BotVisionMixin


class BotEngine(BotInitMixin, BotExecutorMixin, BotRuntimeMixin, BotVisionMixin, BotTaskEntryMixin, QObject):
    """封装 `BotEngine` 相关的数据与行为。"""
    log_message = pyqtSignal(str)
    screenshot_updated = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    detection_result = pyqtSignal(object)
