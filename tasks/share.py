"""分享任务。"""

from __future__ import annotations

import pyautogui
from loguru import logger

from core.engine.task.registry import TaskResult
from core.ui.assets import BTN_CLAIM_YELLOW, BTN_SHARE_GREEN, BTN_SHARE_RED_POINT
from core.ui.page import page_main, page_share
from tasks.base import TaskBase


class TaskShare(TaskBase):
    """封装 `TaskShare` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行分享任务并返回调度结果。"""
        _ = rect
        platform_value = self.config.planting.window_platform.value
        if platform_value != 'wechat':
            logger.warning('每日分享: 当前平台={}，仅支持微信平台，跳过执行', platform_value)
            return self.ok()

        logger.info('每日分享: 开始')
        self.ui.ui_ensure(page_share)

        self._run_share_flow()
        self.ui.ui_ensure(page_main)
        logger.info('每日分享: 结束')
        return self.ok()

    def _run_share_flow(self) -> None:
        """执行每日分享。"""

        times = 0
        while 1:
            self.ui.device.screenshot()

            if times > 3:
                logger.warning('每日分享: 分享超时')
                break
            if self.ui.appear(BTN_SHARE_GREEN, offset=30) and not self.ui.appear(BTN_SHARE_RED_POINT, offset=30):
                break
            if self.ui.appear_then_click(BTN_CLAIM_YELLOW, offset=30, interval=1, static=False):
                continue
            if self.ui.handle_click_close():
                continue
            if self.ui.appear_then_click(BTN_SHARE_GREEN, offset=30, interval=3, static=False):
                self.ui.device.sleep(1 + times * 2)
                times += 1
                pyautogui.press('escape')
                continue
        return
