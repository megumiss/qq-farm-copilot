"""任务奖励领取。"""

from __future__ import annotations

import pyautogui

from core.base.step_result import StepResult
from core.ui.assets import ASSET_NAME_TO_CONST, BTN_CLAIM, BTN_CLOSE, BTN_CONFIRM, TASK_CHECK

BTN_SHARE = ASSET_NAME_TO_CONST.get('btn_share')


class TaskFarmReward:
    """封装 `TaskFarmReward` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui

    def run(self, rect, features) -> StepResult:
        """执行当前模块主流程并返回结果。"""
        if not features.get('auto_task', False):
            return StepResult()
        if not self.ui.appear_then_click(TASK_CHECK, offset=(30, 30), interval=1, threshold=0.8, static=False):
            return StepResult()
        self.engine._sleep_interruptible(0.6)
        out = StepResult.from_value(self._handle_task_result(rect))
        return out

    def _share_and_cancel(self) -> str:
        """点击分享领奖后用 Esc 取消分享面板，回到游戏页面。"""
        if self.engine._is_cancel_requested():
            return '取消领取双倍任务奖励(停止中)'
        if BTN_SHARE is None:
            return '取消领取双倍任务奖励'
        if not self.ui.appear_then_click(BTN_SHARE, offset=(30, 30), interval=1, threshold=0.8, static=False):
            return '取消领取双倍任务奖励'
        if not self.engine._sleep_interruptible(2.0):
            return '取消领取双倍任务奖励(停止中)'

        if self.engine._is_cancel_requested():
            return '取消领取双倍任务奖励(停止中)'
        pyautogui.press('escape')
        if not self.engine._sleep_interruptible(1.0):
            return '取消领取双倍任务奖励(停止中)'
        return '领取双倍任务奖励'

    def _handle_task_result(self, rect: tuple[int, int, int, int]) -> list[str]:
        """处理任务完成弹窗：优先双倍分享，其次普通领取。"""
        actions: list[str] = []
        for _ in range(5):
            if self.engine._is_cancel_requested():
                return actions

            cv_img, _dets, _image = self.engine._capture_and_detect(rect, save=False, template_names=[])
            if cv_img is None:
                return actions
            self.ui.device.set_image(cv_img)

            if BTN_SHARE is not None and self.ui.appear(BTN_SHARE, offset=(30, 30), threshold=0.8, static=False):
                self._share_and_cancel()
                actions.append('领取双倍任务奖励')
                self.engine._sleep_interruptible(0.5)
                return actions

            if self.ui.appear_then_click(BTN_CLAIM, offset=(30, 30), interval=1, threshold=0.8, static=False):
                actions.append('领取任务奖励')
                self.engine._sleep_interruptible(0.3)
                return actions

            if self.ui.appear_then_click_any(
                [BTN_CLOSE, BTN_CONFIRM], offset=(30, 30), interval=1, threshold=0.8, static=False
            ):
                self.engine._sleep_interruptible(0.2)
                continue

            self.engine._sleep_interruptible(0.3)
        return actions


