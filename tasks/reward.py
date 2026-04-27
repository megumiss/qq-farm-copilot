"""任务奖励领取。"""

from __future__ import annotations

from loguru import logger

from core.engine.task.registry import TaskResult
from core.ui.assets import (
    ASSET_NAME_TO_CONST,
    BTN_CLAIM_TASK,
    BTN_DIRECT_CLAIM,
    BTN_SHARE_YELLOW,
)
from core.ui.page import page_main, page_task
from tasks.base import TaskBase
from utils.win_input import press_escape

BTN_TASK_DAILY_TAB = ASSET_NAME_TO_CONST.get('btn_task_daily')
BTN_TASK_GROWTH_TAB = ASSET_NAME_TO_CONST.get('btn_task_growth')


class TaskReward(TaskBase):
    """封装 `TaskReward` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行任务奖励领取并返回调度结果。"""
        _ = rect
        enable_daily = self.task.reward.feature.claim_daily_task
        enable_growth = self.task.reward.feature.claim_growth_task
        logger.info('奖励流程: 开始 | 每日任务={} 成长任务={}', enable_daily, enable_growth)
        if enable_daily or enable_growth:
            self.ui.ui_ensure(page_task, confirm_wait=0.3)

        if enable_daily:
            self._run_daily_flow()
        if enable_growth:
            self._run_growth_flow()

        self.ui.ui_ensure(page_main)
        logger.info('奖励流程: 结束')
        return self.ok()

    def _run_daily_flow(self):
        """执行任务奖励领取流程。"""
        logger.info('奖励流程: 检查每日任务')

        while 1:
            self.ui.device.screenshot()
            if self.ui.handle_click_close():
                continue
            if self.ui.appear_then_click(BTN_CLAIM_TASK, offset=(-30, -10, 30, 300), interval=1):
                continue
            if not self.ui.appear(BTN_CLAIM_TASK, offset=(-30, -10, 30, 300)):
                break
        return

    def _run_growth_flow(self):
        """执行任务奖励领取流程。"""
        logger.info('奖励流程: 检查成长任务')
        platform_value = self.config.planting.window_platform.value
        if platform_value != 'wechat':
            logger.warning('分享流程: 当前平台={}，直接领取，不分享', platform_value)

        while 1:
            self.ui.device.screenshot()
            if self.ui.handle_click_close():
                continue
            if self.ui.appear_then_click(BTN_CLAIM_TASK, offset=(-30, -250, 30, 10)):
                continue
            if self.ui.appear(BTN_SHARE_YELLOW, offset=30, static=False):
                if platform_value == 'wechat' and self.ui.appear_then_click(
                    BTN_SHARE_YELLOW, offset=30, interval=3, static=False
                ):
                    self.ui.device.sleep(2)
                    if not press_escape():
                        logger.warning('奖励流程: 发送 ESC 失败')
                    continue
                if platform_value != 'wechat' and self.ui.appear_then_click(
                    BTN_DIRECT_CLAIM, offset=30, interval=1, static=False
                ):
                    continue
            if not self.ui.appear(BTN_CLAIM_TASK, offset=(-30, -250, 30, 10)):
                break

        return
