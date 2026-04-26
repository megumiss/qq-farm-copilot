"""物品领取任务（QQSVIP领取 + 商城领取）。"""

from __future__ import annotations

from loguru import logger

from core.engine.task.registry import TaskResult
from core.ui.assets import (
    ASSET_NAME_TO_CONST,
    BTN_CLAIM,
    BTN_MALL_FREE,
    BTN_MALL_FREE_DONE,
    BTN_ONECLICK_OPEN,
    BTN_QQSVIP,
)
from core.ui.page import page_mail, page_main, page_mall
from tasks.base import TaskBase

MENU_GOTO_MAIL = ASSET_NAME_TO_CONST.get('menu_goto_mail')


class TaskGift(TaskBase):
    """封装 `TaskGift` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行物品领取流程。"""
        enable_svip = self.task.gift.feature.auto_svip_gift
        enable_mall = self.task.gift.feature.auto_mall_gift
        enable_mail = self.task.gift.feature.auto_mail
        logger.info('领取流程: 开始 | SVIP={} 商城={} 邮件={}', enable_svip, enable_mall, enable_mail)

        self.ui.ui_ensure(page_main)

        if enable_svip:
            self._run_qqsvip_gift()

        if enable_mall:
            self._run_mall_gift()

        if enable_mail:
            self._run_mail_gift()

        self.ui.ui_ensure(page_main)
        logger.info('领取流程: 结束')
        return self.ok()

    def _run_qqsvip_gift(self):
        """领取 QQSVIP 礼包。"""
        logger.info('领取流程: 检查QQSVIP礼包领取')
        self.ui.device.screenshot()
        if not self.ui.appear(BTN_QQSVIP, offset=30):
            logger.info('领取流程: 未找到QQSVIP礼包入口')
            return

        while 1:
            self.ui.device.screenshot()
            if self.ui.handle_click_close():
                continue
            if self.ui.appear_then_click(BTN_QQSVIP, offset=30, threshold=0.85, interval=1):
                continue
            if self.ui.appear_then_click(BTN_CLAIM, offset=30, interval=1, static=False):
                continue
            if not self.ui.appear(BTN_QQSVIP, threshold=0.85, offset=30):
                break
        logger.info('领取流程: QQSVIP礼包流程结束')
        return

    def _run_mall_gift(self):
        """领取商城免费商品"""
        logger.info('领取流程: 检查商城领取')
        self.ui.ui_ensure(page_mall, confirm_wait=0.5)

        while 1:
            self.ui.device.screenshot()
            if self.ui.handle_click_close():
                continue
            if self.ui.appear(BTN_MALL_FREE_DONE, threshold=0.65, offset=30):
                break
            if self.ui.appear_then_click(BTN_MALL_FREE, offset=30, threshold=0.65, interval=1):
                continue
        logger.info('领取流程: 商城领取流程结束')
        return

    def _run_mail_gift(self):
        """邮件领取"""
        logger.info('领取流程: 检查邮件领取')
        self.ui.ui_ensure(page_mail)

        clicker = 0
        while 1:
            self.ui.device.screenshot()
            if self.ui.handle_click_close():
                continue
            if clicker > 1:
                break
            if not self.ui.appear(BTN_ONECLICK_OPEN, offset=30):
                break
            if self.ui.appear_then_click(BTN_ONECLICK_OPEN, offset=30, interval=1):
                clicker += 1
                continue
        logger.info('领取流程: 邮件领取流程结束')
        return
