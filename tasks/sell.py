"""出售任务。"""

from __future__ import annotations

from loguru import logger

from core.engine.task.registry import TaskResult
from core.ui.assets import (
    BTN_BATCH_SELL,
    BTN_CLOSE,
    BTN_CONFIRM,
    BTN_PLANTING,
    MAIN_GOTO_WAREHOUSE,
)
from core.ui.page import page_main, page_warehouse
from models.farm_state import ActionType
from tasks.base import TaskBase


class TaskSell(TaskBase):
    """封装 `TaskSell` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行独立出售任务并返回调度结果。"""
        self.ui.ui_ensure(page_warehouse)

        if not self._batch_sell_once():
            return self.ok()
        return self.ok()

    def _batch_sell_once(self) -> bool:
        """仓库内执行一次批量出售。"""
        logger.info('出售流程: 批量出售')
        batch_clicked = False

        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(BTN_BATCH_SELL, offset=30, interval=1):
                batch_clicked = True
                continue
            if batch_clicked and self.ui.appear_then_click(BTN_CONFIRM, offset=30, interval=1, static=False):
                self.engine._record_stat(ActionType.SELL)
                self.ui.device.sleep(0.5)
                continue
            if self.ui.appear(BTN_PLANTING, offset=30) and self.ui.appear_then_click(
                BTN_CLOSE, offset=30, interval=1, static=False
            ):
                continue
            if self.ui.appear(MAIN_GOTO_WAREHOUSE, offset=30):
                if not batch_clicked:
                    return False
                else:
                    return True
