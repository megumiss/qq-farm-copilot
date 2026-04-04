"""nklite UI 导航。"""

from __future__ import annotations

from typing import Callable

from loguru import logger

from core.base.button import Button
from core.base.timer import Timer
from core.handler.info_handler import InfoHandler
from core.ui.page import *


class UI(InfoHandler):
    """封装 `UI` 相关的数据与行为。"""
    ui_pages = [
        page_unknown,
        page_main,
        page_shop,
        page_friend,
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
        device,
        crop_name_resolver: Callable[[], str],
        cancel_checker: Callable[[], bool],
    ):
        """初始化对象并准备运行所需状态。"""
        super().__init__(config=config, detector=detector, device=device)
        self._crop_name_resolver = crop_name_resolver
        self._cancel_checker = cancel_checker
        self.ui_current: Page = page_unknown

    def _is_cancelled(self) -> bool:
        """判断是否满足 `cancelled` 条件。"""
        return bool(self._cancel_checker and self._cancel_checker())

    def ui_page_appear(self, page: Page):
        """判断某个页面是否出现（支持单按钮或多按钮联合判定）。"""
        check = page.check_button
        if check is None:
            return False
        if isinstance(check, (list, tuple, set)):
            if not check:
                return False
            return all(self.appear(btn, offset=(30, 30), threshold=0.8, static=False) for btn in check)
        return self.appear(check, offset=(30, 30), threshold=0.8, static=False)

    def ui_get_current_page(self, skip_first_screenshot=True, timeout=2.0):
        """识别当前页面；未知时尝试回主与弹窗处理，直到超时。"""
        logger.info('UI get current page')
        deadline = Timer(timeout, count=1).start()

        while True:
            if self._is_cancelled():
                return page_unknown
            # 首轮尽量复用已有截图，减少无意义截屏。
            if skip_first_screenshot:
                skip_first_screenshot = False
                if self.device.image is None:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # 按 ui_pages 顺序尝试页面判定，命中即返回当前页。
            for page in self.ui_pages:
                if page.check_button is None:
                    continue
                if self.ui_page_appear(page=page):
                    logger.info(f'UI page={page.cn_name}')
                    self.ui_current = page
                    return page

            logger.info('Unknown ui page')
            # 未知页面先尝试固定坐标回主，再尝试弹窗处理，最后按超时退出。
            if self._click_goto_main(interval=2.0):
                deadline.reset()
                continue
            if self.ui_additional():
                deadline.reset()
                continue
            if deadline.reached():
                break

        logger.warning('Unknown ui page')
        self.ui_current = page_unknown
        return page_unknown

    def _click_goto_main(self, interval: float = 2.0) -> bool:
        """按固定坐标点击“回主”按钮，并应用点击节流。"""
        key = 'goto_main'
        if interval and not self._button_interval_ready(key, float(interval)):
            return False

        x, y = GOTO_MAIN.location

        button = Button(
            area=(int(x), int(y), int(x) + 1, int(y) + 1),
            color=(128, 128, 128),
            button=(int(x), int(y), int(x) + 1, int(y) + 1),
            file=None,
            name='goto_main',
        )
        ok = bool(self.device.click(button))
        if ok and interval:
            self._button_interval_hit(key)
        return ok

    def ui_goto(self, destination, offset=(30, 30), confirm_wait=0, skip_first_screenshot=True):
        """从当前页导航到目标页。

        做法：
        - 先基于页面 link 反向构建可达父链。
        - 循环识别当前页并执行单步跳转。
        - 无法跳转时交给 `ui_additional` 清弹窗，超时返回失败。
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

        logger.info(f'UI goto {destination.cn_name}')
        confirm_timer = Timer(confirm_wait, count=max(1, int(confirm_wait // 0.5) or 1)).start()
        timeout = Timer(6.0, count=1).start()
        while True:
            if self._is_cancelled():
                return False
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_page_appear(destination):
                if confirm_timer.reached():
                    self.ui_current = destination
                    logger.info(f'Page arrive: {destination.cn_name}')
                    return True
            else:
                confirm_timer.reset()

            clicked = False
            # 在可达集合内寻找“当前出现页面 -> parent”的跳转按钮并执行单步切换。
            for page in visited:
                if not page.parent:
                    continue
                if not self.ui_page_appear(page):
                    continue
                button = page.links[page.parent]
                logger.info(f'Page switch: {page.cn_name} -> {page.parent.cn_name}')
                self.device.click(button)
                clicked = True
                break
            if clicked:
                continue

            # 跳转失败时优先处理全局弹窗，再判断是否超时。
            if self.ui_additional():
                continue

            if timeout.reached():
                return False

    def ui_ensure(self, destination, confirm_wait=0, skip_first_screenshot=True):
        """确保当前页面位于目标页；已在目标页则不重复跳转。"""
        self.ui_get_current_page(skip_first_screenshot=skip_first_screenshot)
        if self.ui_current == destination:
            logger.info(f'Already at {destination.cn_name}')
            return False
        logger.info(f'Goto {destination.cn_name}')
        return self.ui_goto(destination, confirm_wait=confirm_wait, skip_first_screenshot=True)

    def ui_additional(self):
        """统一处理全局弹窗；任一处理命中即返回 True。"""
        if self.handle_level_up():
            return True
        if self.handle_reward():
            return True
        if self.handle_shop_residual():
            return True
        if self.handle_announcement():
            return True
        if self.handle_login_reward():
            return True
        if self.handle_system_error():
            return True
        return False

    def ui_goto_main(self):
        """快捷入口：导航回主页面。"""
        return self.ui_ensure(destination=page_main)

    def ui_wait_loading(self):
        """等待加载阶段结束：弹窗持续出现或稳定无弹窗均视为完成。"""
        confirm_timer = Timer(1.5, count=2)
        overall_timer = Timer(2.0)
        while True:
            if self._is_cancelled():
                return False
            self.device.screenshot()
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


