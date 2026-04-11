"""nklite UI 导航。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from core.base.timer import Timer
from core.exceptions import GamePageUnknownError, TaskRetryCurrentError
from core.ui.assets import BTN_LOGIN_AGAIN
from core.ui.page import *
from tasks.handler import Handler

if TYPE_CHECKING:
    from core.platform.device import Device


class UI(Handler):
    """封装 `UI` 相关的数据与行为。"""

    ui_pages = [
        page_unknown,
        page_main,
        page_shop,
        page_friend_list,
        page_friend_farm,
        page_mall,
        page_pet,
        page_task,
        page_warehouse,
        page_wiki,
    ]

    def __init__(
        self,
        config,
        detector,
        device: Device,
        crop_name_resolver: Callable[[], str],
    ):
        """初始化对象并准备运行所需状态。"""
        super().__init__(config=config, detector=detector, device=device)
        self._crop_name_resolver = crop_name_resolver
        self.ui_current: Page = page_unknown

    def ui_page_appear(self, page: Page):
        """判断某个页面是否出现（支持单按钮或多按钮交集判定）。"""
        check = page.check_button
        if check is None:
            return False
        if isinstance(check, (list, tuple, set)):
            if not check:
                return False
            return all(self.appear(btn, offset=(30, 30), static=False) for btn in check)
        return self.appear(check, offset=(30, 30), static=False)

    def ui_get_current_page(self, timeout=2.0):
        """识别当前页面；未知时尝试回主与弹窗处理，直到超时。"""
        logger.info('开始识别当前页面')
        deadline = Timer(timeout, count=1).start()

        while True:
            self.device.screenshot()
            # 下次再来弹窗，抛出异常
            self.handle_login_repeat()
            # 重新登录弹窗，点击后重新启动
            self._handle_login_again_retry()

            # 按 ui_pages 顺序尝试页面判定，命中即返回当前页。
            for page in self.ui_pages:
                if page.check_button is None:
                    continue
                if self.ui_page_appear(page=page):
                    logger.info(f'识别到页面={page.cn_name}')
                    self.ui_current = page
                    return page

            logger.info('未识别到页面')
            # 未知页面先尝试固定坐标回主，再尝试弹窗处理，最后按超时退出。
            if self._click_goto_main(interval=2.0):
                deadline.reset()
                continue
            if self.ui_additional():
                deadline.reset()
                continue
            if deadline.reached():
                break

        logger.warning('页面识别超时，仍为未知页面')
        self.ui_current = page_unknown
        raise GamePageUnknownError('页面识别超时，仍为未知页面')

    def _click_goto_main(self, interval: float = 2.0) -> bool:
        """按固定坐标点击“回主”按钮，并应用点击节流。"""
        key = 'goto_main'
        if interval and not self._button_interval_ready(key, float(interval)):
            return False

        ok = bool(self.device.click_button(GOTO_MAIN))
        if ok and interval:
            self._button_interval_hit(key)
        return ok

    def ui_goto(self, destination, offset=(30, 30), confirm_wait=0):
        """从当前页导航到目标页。

        做法：
        - 先基于页面 link 反向构建可达父链。
        - 循环识别当前页并执行单步跳转。
        - 不在此处做全局弹窗处理，持续尝试直到到达目标页。
        """
        # 每次导航前重置 parent，避免沿用上次导航链。
        for page in self.ui_pages:
            page.parent = None

        # 反向建图：从目标页回溯所有可达父节点，形成最短可行切换集合。
        visited = {destination}
        while True:
            new = visited.copy()
            for page in visited:
                for link in self.ui_pages:
                    if link in visited:
                        continue
                    if page in link.links:
                        link.parent = page
                        new.add(link)
            if len(new) == len(visited):
                break
            visited = new

        logger.info(f'开始跳转页面 -> {destination.cn_name}')
        confirm_timer = Timer(confirm_wait, count=1).start()
        while True:
            self.device.screenshot()
            # 下次再来弹窗，抛出异常
            self.handle_login_repeat()
            # 重新登录弹窗，点击后重新启动
            self._handle_login_again_retry()

            if self.ui_page_appear(destination):
                if confirm_timer.reached():
                    self.ui_current = destination
                    logger.info(f'到达页面: {destination.cn_name}')
                    return True
            else:
                confirm_timer.reset()

            clicked = False
            # 在可达集合内寻找“当前出现页面 -> parent”的跳转按钮并执行单步切换。
            for page in visited:
                if not page.parent:
                    continue
                page_switch_key = f'ui_goto_page::{page.name}'
                if not self._button_interval_ready(page_switch_key, 4.0):
                    continue
                if not self.ui_page_appear(page):
                    continue
                self._button_interval_hit(page_switch_key)
                button = page.links[page.parent]
                logger.info(f'页面切换: {page.cn_name} -> {page.parent.cn_name}')
                if self.device.click_button(button):
                    clicked = True
                    break
            if clicked:
                continue

    def ui_ensure(self, destination, confirm_wait=0):
        """确保当前页面位于目标页；已在目标页则不重复跳转。"""
        self.ui_get_current_page()
        if self.ui_current == destination:
            logger.info(f'已在页面: {destination.cn_name}')
            return False
        if self.ui_current == page_main and destination == page_friend_list:
            if self._ensure_main_to_friend():
                return True
        logger.info(f'跳转到页面: {destination.cn_name}')
        return self.ui_goto(destination, confirm_wait=confirm_wait)

    def _ensure_main_to_friend(self) -> bool:
        """主页 -> 好友页专用处理钩子（预留）。"""
        return False

    def ui_additional(self):
        """统一处理全局弹窗；任一处理命中即返回 True。"""
        if self.handle_login_repeat():
            return True
        if self.handle_click_close():
            return True
        if self.handle_announcement():
            return True
        return False

    def _handle_login_again_retry(self) -> bool:
        """命中“重新登录”先点击，再重试当前任务。"""
        if self.appear_then_click(BTN_LOGIN_AGAIN, offset=30, interval=1, static=False):
            raise TaskRetryCurrentError('login again handled, retry current task')
        return False

    def ui_goto_main(self):
        """快捷入口：导航回主页面。"""
        return self.ui_ensure(destination=page_main)

    def ui_wait_loading(self):
        """等待加载阶段结束：弹窗持续出现或稳定无弹窗均视为完成。"""
        confirm_timer = Timer(1.5, count=2)
        overall_timer = Timer(2.0)
        while True:
            self.device.screenshot()
            # 下次再来弹窗，抛出异常
            self.handle_login_repeat()
            # 重新登录弹窗，点击后重新启动
            self._handle_login_again_retry()

            if self.ui_additional():
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    return True
                overall_timer.clear()
            else:
                confirm_timer.clear()
                if not overall_timer.started():
                    overall_timer.start()
                if overall_timer.reached():
                    return True
