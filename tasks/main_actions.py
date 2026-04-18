"""TaskMain 一键动作相关逻辑。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from core.base.timer import Timer
from core.ui.assets import *
from models.farm_state import ActionType

if TYPE_CHECKING:
    from core.engine.bot.local_engine import LocalBotEngine
    from core.ui.ui import UI


class TaskMainActionsMixin:
    """提供一键收获/除草/除虫/浇水/施肥能力。"""

    engine: 'LocalBotEngine'
    ui: 'UI'

    def _run_feature_harvest(self) -> str | None:
        """一键收获"""
        self.ui.device.screenshot()
        if not self.ui.appear(BTN_HARVEST, offset=30, static=False) and not self.ui.appear(
            BTN_MATURE, offset=30, static=False
        ):
            return None

        confirm_timer = Timer(0.2, count=1)
        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(BTN_HARVEST, offset=30, interval=1, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                continue
            if self.ui.appear_then_click(BTN_MATURE, offset=30, interval=1, static=False):
                self.engine._record_stat(ActionType.HARVEST)
                continue
            if not self.ui.appear(BTN_HARVEST, offset=30, static=False) and not self.ui.appear(
                BTN_MATURE, offset=30, static=False
            ):
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    result = '一键收获'
                    break
            else:
                confirm_timer.clear()

        return result

    def _run_feature_weed(self) -> str | None:
        """一键除草"""
        return self._run_feature_single_action(BTN_WEED, ActionType.WEED, '一键除草')

    def _run_feature_bug(self) -> str | None:
        """一键除虫"""
        return self._run_feature_single_action(BTN_BUG, ActionType.BUG, '一键除虫')

    def _run_feature_water(self) -> str | None:
        """一键浇水"""
        return self._run_feature_single_action(BTN_WATER, ActionType.WATER, '一键浇水')

    # TODO 优化操作速度
    def _run_feature_single_action(self, button, stat_action: str, done_text: str) -> str | None:
        """通用单按钮循环动作：首检未命中直接返回，命中后点击到消失。"""
        logger.info('一键{}流程: 开始', done_text)
        self.ui.device.screenshot()
        if not self.ui.appear(button, offset=30, static=False):
            return None

        confirm_timer = Timer(0.2, count=1)
        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(button, offset=30, interval=1, static=False):
                self.engine._record_stat(stat_action)
                continue
            if not self.ui.appear(button, offset=30, static=False):
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    result = done_text
                    break
            else:
                confirm_timer.clear()

        return result

    # TODO
    def _run_feature_fertilize(self) -> str | None:
        """自动施肥"""
        return None
