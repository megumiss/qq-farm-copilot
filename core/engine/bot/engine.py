"""Bot 引擎入口。"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from core.engine.bot.executor import BotExecutorMixin
from core.engine.bot.bootstrap import BotInitMixin
from core.engine.bot.runtime import BotRuntimeMixin
from core.engine.bot.vision import BotVisionMixin


class BotEngine(BotInitMixin, BotExecutorMixin, BotRuntimeMixin, BotVisionMixin, QObject):
    """封装 `BotEngine` 相关的数据与行为。"""
    log_message = pyqtSignal(str)
    screenshot_updated = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    detection_result = pyqtSignal(object)
