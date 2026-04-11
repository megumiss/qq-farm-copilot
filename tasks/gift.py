"""免费礼包任务（QQSVIP礼包 + 商城礼包）。"""

from __future__ import annotations

from loguru import logger

from core.engine.task.registry import TaskResult
from core.ui.assets import (
    ASSET_NAME_TO_CONST,
    BTN_CLAIM,
    BTN_CLOSE,
    BTN_CONFIRM,
    BTN_SHARE_GREEN,
    BTN_SHARE_YELLOW,
    MAIN_GOTO_MENU,
    MAIN_GOTO_SHARE,
    MENU_GOTO_MAIN,
)
from core.ui.page import page_main, page_mall
from tasks.base import TaskBase

MENU_GOTO_MAIL = ASSET_NAME_TO_CONST.get('menu_goto_mail')


class TaskGift(TaskBase):
    """封装 `TaskGift` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行免费礼包流程。"""
        _ = rect
        features = self.get_features('gift')
        enable_svip = self.has_feature(features, 'auto_svip_gift', default=True)
        enable_mall = self.has_feature(features, 'auto_mall_gift', default=True)
        enable_mail = self.has_feature(features, 'auto_mail', default=True)
        completed_steps: list[str] = []
        logger.info('礼包流程: 开始 | SVIP={} 商城={} 邮件={}', enable_svip, enable_mall, enable_mail)

        self.ui.ui_ensure(page_main)

        if enable_svip:
            qqsvip = self._run_qqsvip_gift()
            if qqsvip:
                completed_steps.append(qqsvip)

        if enable_mall:
            mall = self._run_mall_gift()
            if mall:
                completed_steps.append(mall)

        if enable_mail:
            mail = self._run_mail_gift()
            if mail:
                completed_steps.append(mail)

        self.ui.ui_ensure(page_main)
        logger.info('礼包流程: 结束 | 动作={}', '、'.join(completed_steps) if completed_steps else '无动作')
        return self.ok()

    def _run_qqsvip_gift(self) -> str | None:
        """领取 QQSVIP 免费礼包。"""
        logger.info('礼包流程: 检查QQSVIP礼包')
        self.ui.device.screenshot()
        if not self.ui.appear_then_click(MAIN_GOTO_SHARE, offset=30, interval=1, threshold=0.8, static=False):
            logger.info('礼包流程: 未命中QQSVIP入口')
            return None

        self.ui.device.sleep(0.5)
        claimed = self._claim_loop(include_share_button=True, max_rounds=12)
        self.ui.ui_ensure(page_main)
        if claimed:
            return '领取QQSVIP礼包'
        return None

    def _run_mall_gift(self) -> str | None:
        """领取商城免费礼包。"""
        logger.info('礼包流程: 检查商城礼包')
        self.ui.ui_ensure(page_mall)
        claimed = self._claim_loop(include_share_button=False, max_rounds=12)
        self.ui.ui_ensure(page_main)
        if claimed:
            return '领取商城礼包'
        return None

    def _run_mail_gift(self) -> str | None:
        """邮件领取：主页 -> 菜单 -> 邮件（模板缺失时跳过）-> 领取。"""
        logger.info('礼包流程: 检查邮件领取')
        self.ui.ui_ensure(page_main)
        if not self._open_menu():
            logger.info('礼包流程: 未能打开菜单，跳过邮件领取')
            return None

        if MENU_GOTO_MAIL is None:
            logger.info('礼包流程: 未配置 menu_goto_mail 模板，跳过邮件领取')
            self.ui.ui_ensure(page_main)
            return None

        if not self._open_mail_page():
            logger.info('礼包流程: 未命中邮件入口，跳过邮件领取')
            self.ui.ui_ensure(page_main)
            return None

        claimed = self._claim_loop(include_share_button=False, max_rounds=10)
        self.ui.ui_ensure(page_main)
        if claimed:
            return '邮件领取'
        return None

    def _open_menu(self) -> bool:
        """打开菜单页并确认已到达菜单态。"""
        for _ in range(6):
            self.ui.device.screenshot()

            if self.ui.appear(MENU_GOTO_MAIN, offset=30, threshold=0.8, static=False):
                return True

            if self.ui.appear_then_click(MAIN_GOTO_MENU, offset=30, interval=1, threshold=0.8, static=False):
                self.ui.device.sleep(0.4)
                continue

            if self.ui.ui_additional():
                self.ui.device.sleep(0.2)
                continue

            self.ui.device.sleep(0.2)

        return False

    def _open_mail_page(self) -> bool:
        """点击菜单内邮件入口，进入邮件界面。"""
        for _ in range(6):
            self.ui.device.screenshot()

            if self.ui.appear_then_click(MENU_GOTO_MAIL, offset=30, interval=1, threshold=0.8, static=False):
                self.ui.device.sleep(0.4)
                return True

            if self.ui.ui_additional():
                self.ui.device.sleep(0.2)
                continue

            self.ui.device.sleep(0.2)

        return False

    def _claim_loop(self, *, include_share_button: bool, max_rounds: int) -> bool:
        """通用礼包领取循环：领取/确认/关闭，直到稳定无动作。"""
        claimed = False
        idle_rounds = 0
        rounds = max(1, int(max_rounds))

        for _ in range(rounds):
            self.ui.device.screenshot()

            if self.ui.appear_then_click(BTN_CLAIM, offset=30, interval=1, threshold=0.8, static=False):
                claimed = True
                idle_rounds = 0
                self.ui.device.sleep(0.2)
                continue

            if include_share_button and self.ui.appear_then_click_any(
                [BTN_SHARE_GREEN, BTN_SHARE_YELLOW],
                offset=30,
                interval=1,
                threshold=0.8,
                static=False,
            ):
                idle_rounds = 0
                self.ui.device.sleep(0.2)
                continue

            if self.ui.appear_then_click(BTN_CONFIRM, offset=30, interval=1, threshold=0.8, static=False):
                idle_rounds = 0
                self.ui.device.sleep(0.2)
                continue

            if self.ui.appear_then_click(BTN_CLOSE, offset=30, interval=1, threshold=0.8, static=False):
                idle_rounds = 0
                self.ui.device.sleep(0.2)
                continue

            if self.ui.ui_additional():
                idle_rounds = 0
                self.ui.device.sleep(0.2)
                continue

            idle_rounds += 1
            if idle_rounds >= 2:
                break
            self.ui.device.sleep(0.2)

        return claimed
