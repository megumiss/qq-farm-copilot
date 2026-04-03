"""nklite UI 导航。"""

from __future__ import annotations

from typing import Callable

from loguru import logger

from core.nklite.base.button import Button
from core.nklite.base.timer import Timer
from core.nklite.handler.info_handler import InfoHandler
from core.nklite.ui.page import *


class UI(InfoHandler):
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
        goto_main_point_resolver: Callable[[tuple[int, int, int, int] | None], tuple[int, int]] | None = None,
    ):
        super().__init__(config=config, detector=detector, device=device)
        self._crop_name_resolver = crop_name_resolver
        self._cancel_checker = cancel_checker
        self._goto_main_point_resolver = goto_main_point_resolver
        self.ui_current: Page = page_unknown

    def _is_cancelled(self) -> bool:
        return bool(self._cancel_checker and self._cancel_checker())

    def ui_page_appear(self, page: Page):
        check = page.check_button
        if check is None:
            return False
        if isinstance(check, (list, tuple, set)):
            if not check:
                return False
            return all(self.appear(btn, offset=(30, 30), threshold=0.8, static=False) for btn in check)
        return self.appear(check, offset=(30, 30), threshold=0.8, static=False)

    def ui_get_current_page(self, skip_first_screenshot=True, timeout=2.0):
        logger.info('UI get current page')
        deadline = Timer(timeout, count=1).start()

        while True:
            if self._is_cancelled():
                return page_unknown
            if skip_first_screenshot:
                skip_first_screenshot = False
                if self.device.image is None:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            for page in self.ui_pages:
                if page.check_button is None:
                    continue
                if self.ui_page_appear(page=page):
                    logger.info(f'UI page={page.cn_name}')
                    self.ui_current = page
                    return page

            logger.info('Unknown ui page')
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
        key = 'goto_main'
        if interval and not self._button_interval_ready(key, float(interval)):
            return False

        x, y = GOTO_MAIN.location
        if self._goto_main_point_resolver:
            try:
                x, y = self._goto_main_point_resolver(getattr(self.device, 'rect', None))
            except Exception:
                pass

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
        for page in self.ui_pages:
            page.parent = None

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

            if self.ui_additional():
                continue

            if timeout.reached():
                return False

    def ui_ensure(self, destination, confirm_wait=0, skip_first_screenshot=True):
        self.ui_get_current_page(skip_first_screenshot=skip_first_screenshot)
        if self.ui_current == destination:
            logger.info(f'Already at {destination.cn_name}')
            return False
        logger.info(f'Goto {destination.cn_name}')
        return self.ui_goto(destination, confirm_wait=confirm_wait, skip_first_screenshot=True)

    def ui_additional(self):
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
        return self.ui_ensure(destination=page_main)

    def ui_wait_loading(self):
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
