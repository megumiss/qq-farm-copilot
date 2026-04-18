"""TaskMain 土地相关逻辑（扩建/升级）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from core.base.timer import Timer
from core.ui.assets import *
from core.ui.page import GOTO_MAIN, page_main

if TYPE_CHECKING:
    from core.engine.bot.local_engine import LocalBotEngine
    from core.ui.ui import UI


class TaskMainLandMixin:
    """提供自动扩建与自动升级流程。"""

    engine: 'LocalBotEngine'
    ui: 'UI'

    def _run_feature_expand(self) -> str | None:
        """自动扩建"""
        return self._try_expand()

    def _run_feature_upgrade(self) -> str | None:
        """自动升级"""
        return self._try_upgrade()

    def _try_expand(self) -> str | None:
        """执行一次扩建流程"""
        logger.info('自动扩建: 开始')
        self.ui.ui_ensure(page_main)
        # 点击空白处
        self.ui.device.click_button(GOTO_MAIN)
        self.ui.device.screenshot()
        if not self.ui.appear(BTN_EXPAND, offset=30, static=False):
            logger.info('自动扩建: 未发现待扩建土地')
            return None

        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(BTN_EXPAND, offset=30, interval=1, static=False):
                continue
            if self.ui.appear(BTN_EXPAND_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_EXPAND_DIRECT_CONFIRM, offset=30, interval=1
            ):
                continue
            if self.ui.appear(BTN_EXPAND_CHECK, offset=30) and self.ui.appear_then_click(
                BTN_EXPAND_CONFIRM, offset=30, interval=1
            ):
                continue
            if not self.ui.appear(BTN_EXPAND, offset=30, static=False):
                logger.info('自动扩建: 已完成')
                break

        return None

    def _try_upgrade(self) -> str | None:
        """尝试执行一次升级流程；失败后短路避免重复触发。"""
        if self._upgrade_failed:
            return None

        levelup_button = ASSET_NAME_TO_CONST.get('icon_levelup')
        if levelup_button is None:
            logger.warning('自动升级流程: 缺少 icon_levelup 模板，跳过升级功能')
            self._upgrade_failed = True
            return None

        self.ui.device.screenshot()
        if not self.ui.appear(levelup_button, offset=30, threshold=0.8, static=False):
            return None

        acted = False
        confirm_timer = Timer(0.2, count=1)
        while 1:
            if self.ui.device.screenshot() is None:
                return None

            if self.ui.appear_then_click(levelup_button, offset=30, interval=1, threshold=0.8, static=False):
                acted = True
                continue
            if self.ui.appear_then_click_any(
                [BTN_CONFIRM, BTN_DIRECT_CLAIM],
                offset=30,
                interval=1,
                threshold=0.8,
                static=False,
            ):
                acted = True
                continue
            if self.ui.appear_then_click(BTN_CLOSE, offset=30, interval=1, threshold=0.8, static=False):
                continue

            if not self.ui.appear(levelup_button, offset=30, threshold=0.8, static=False):
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    self._upgrade_failed = False
                    return '自动升级' if acted else None
            else:
                confirm_timer.clear()
