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

    def _run_feature_maintain_actions(
        self,
        *,
        enable_weed: bool,
        enable_bug: bool,
        enable_water: bool,
    ) -> str | None:
        """统一执行一键除草/除虫/浇水，共用确认计时器。"""
        action_specs = []
        if enable_weed:
            action_specs.append((BTN_WEED, ActionType.WEED))
        if enable_bug:
            action_specs.append((BTN_BUG, ActionType.BUG))
        if enable_water:
            action_specs.append((BTN_WATER, ActionType.WATER))
        if not action_specs:
            return None
        action_buttons = [button for button, _ in action_specs]

        logger.info(
            '一键维护流程: 开始 | 除草={} 除虫={} 浇水={}',
            enable_weed,
            enable_bug,
            enable_water,
        )

        self.ui.device.screenshot()
        if not self.ui.appear_any(action_buttons, offset=30, static=False):
            return None

        confirm_timer = Timer(0.5, count=2)
        while 1:
            self.ui.device.screenshot()

            clicked_action: str | None = None
            for button, stat_action in action_specs:
                if self.ui.appear(button, offset=30, static=False):
                    clicked_action = stat_action
                    break
            if self.ui.appear_then_click_any(action_buttons, offset=30, interval=0.3, static=False):
                if clicked_action is not None:
                    self.engine._record_stat(clicked_action)
                confirm_timer.clear()
                continue

            if not self.ui.appear_any(action_buttons, offset=30, static=False):
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    return '一键维护'
            else:
                confirm_timer.clear()

    # TODO
    def _run_feature_fertilize(self) -> str | None:
        """自动施肥"""
        return None
