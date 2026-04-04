"""出售任务。"""

from __future__ import annotations

from core.base.step_result import StepResult
from core.ui.assets import (
    BTN_BATCH_SELL,
    BTN_CLOSE,
    BTN_CONFIRM,
    WAREHOUSE_CHECK,
)
from models.farm_state import ActionType


class TaskFarmSell:
    """封装 `TaskFarmSell` 任务的执行入口与步骤。"""
    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui

    def run(self, features, sold_this_round: bool) -> tuple[StepResult, bool]:
        """执行当前模块主流程并返回结果。"""
        if sold_this_round or not features.get('auto_sell', False):
            return StepResult(), sold_this_round

        if not self.ui.appear_then_click(WAREHOUSE_CHECK, offset=(30, 30), interval=1, threshold=0.8, static=False):
            return StepResult(), sold_this_round
        self.engine._sleep_interruptible(0.6)

        batch_clicked = False
        for _ in range(5):
            self.ui.device.screenshot()
            if self.ui.appear_then_click(BTN_BATCH_SELL, offset=(30, 30), interval=1, threshold=0.8, static=False):
                batch_clicked = True
                self.engine._sleep_interruptible(0.4)
                break
            self.engine._sleep_interruptible(0.2)

        if not batch_clicked:
            self._close_page()
            return StepResult(), sold_this_round

        for _ in range(5):
            self.ui.device.screenshot()
            if self.ui.appear_then_click(BTN_CONFIRM, offset=(30, 30), interval=1, threshold=0.8, static=False):
                self.engine._record_stat(ActionType.SELL)
                self.engine._sleep_interruptible(0.4)
                self._close_page()
                return StepResult.from_value('批量出售果实'), True
            self.engine._sleep_interruptible(0.2)

        self._close_page()
        return StepResult(), sold_this_round

    def _close_page(self):
        """执行 `close page` 相关处理。"""
        self.ui.device.screenshot()
        self.ui.appear_then_click(BTN_CLOSE, offset=(30, 30), interval=1, threshold=0.8, static=False)
        self.ui.appear_then_click(BTN_CLOSE, offset=(30, 30), interval=1, threshold=0.8, static=False)


