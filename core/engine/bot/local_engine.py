"""Bot 本地引擎（运行于 worker 子进程）。"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from core.engine.bot.bootstrap import BotInitMixin
from core.engine.bot.executor import BotExecutorMixin
from core.engine.bot.runtime import BotRuntimeMixin
from core.engine.bot.vision import BotVisionMixin


class LocalBotEngine(BotInitMixin, BotExecutorMixin, BotRuntimeMixin, BotVisionMixin, QObject):
    """封装 worker 进程内本地引擎。"""

    log_message = pyqtSignal(str)
    screenshot_updated = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    detection_result = pyqtSignal(object)
    config_updated = pyqtSignal(dict)

    def __init__(self, config, *, runtime_paths=None, instance_id: str = 'default'):
        super().__init__(config, runtime_paths=runtime_paths, instance_id=instance_id)
