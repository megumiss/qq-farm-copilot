"""活动商店任务（商城免费物品领取）。"""

from __future__ import annotations

from collections import defaultdict

from loguru import logger

from core.base.timer import Timer
from core.engine.task.registry import TaskResult
from core.ui.assets import (
    BTN_CLICK_TO_CLOSE,
    BTN_HAHA_SHOP,
    BTN_HAHA_SHOP_CHECK,
    BTN_HAHA_SHOP_CLOSE,
    BTN_HAHA_SHOP_FREE_REFRESH,
    BTN_HAHA_SHOP_ITEM,
)
from core.ui.page import page_main
from tasks.base import TaskBase


class TaskEventShop(TaskBase):
    """封装 `TaskEventShop` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        _ = rect
        logger.info('活动商店: 开始')
        self.ui.ui_ensure(page_main)
        self._run_haha_shop_claim()
        logger.info('活动商店: 结束')
        return self.ok()

    def _run_haha_shop_claim(self) -> None:
        logger.info('活动商店: 打开南瓜乐翻天')
        while 1:
            self.ui.device.screenshot()
            if self.ui.appear(BTN_HAHA_SHOP_CHECK, offset=30):
                break
            if self.ui.appear_then_click(BTN_HAHA_SHOP, offset=30, interval=1):
                continue

        idle_timer = Timer(1, count=3)
        area_click_count: dict[tuple[int, int, int, int], int] = defaultdict(int)
        while 1:
            self.ui.device.screenshot()
            self._mask_clicked_haha_shop_items(area_click_count)

            if self.ui.appear_then_click(BTN_CLICK_TO_CLOSE, offset=30, interval=1):
                idle_timer.clear()
                continue
            if self.ui.appear(BTN_HAHA_SHOP_ITEM, offset=(-120, -10, 250, 180)):
                hit_area = tuple(int(v) for v in BTN_HAHA_SHOP_ITEM.button)
                if self.ui.device.click_button(BTN_HAHA_SHOP_ITEM):
                    area_click_count[hit_area] += 1
                    click_count = int(area_click_count[hit_area])
                    if click_count >= 2:
                        logger.info('活动商店: 跳过该位置 | area={}', hit_area)
                    else:
                        logger.info('活动商店: 购买种子 | area={}', hit_area)
                    idle_timer.clear()
                    self.ui.device.sleep(0.5)
                continue
            if self.ui.appear(BTN_HAHA_SHOP_FREE_REFRESH, offset=30):
                if not idle_timer.started():
                    idle_timer.start()
                if idle_timer.reached():
                    if self.ui.device.click_button(BTN_HAHA_SHOP_FREE_REFRESH):
                        area_click_count.clear()
                        self.ui.device.stuck_record_clear()
                        self.ui.device.click_record_clear()
                        idle_timer.clear()
                        logger.info('活动商店: 点击免费刷新')
                continue
            if not idle_timer.started():
                idle_timer.start()
            if idle_timer.reached():
                logger.info('活动商店: 结束购买')
                break

        while 1:
            self.ui.device.screenshot()
            if self.ui.appear(BTN_HAHA_SHOP, offset=30):
                logger.info('活动商店: 关闭南瓜乐翻天')
                break
            if self.ui.appear_then_click(BTN_HAHA_SHOP_CLOSE, offset=30, interval=1):
                continue

    def _mask_clicked_haha_shop_items(self, area_click_count: dict[tuple[int, int, int, int], int]) -> None:
        """将同位置点击达到 2 次的 item 区域在当前截图中涂白。"""
        image = self.ui.device.image
        if image is None:
            return
        if not area_click_count:
            return

        h, w = image.shape[:2]
        for area, count in area_click_count.items():
            if int(count) < 2:
                continue
            x1, y1, x2, y2 = [int(v) for v in area]
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(x1 + 1, min(x2, w))
            y2 = max(y1 + 1, min(y2, h))
            image[y1:y2, x1:x2] = 255
