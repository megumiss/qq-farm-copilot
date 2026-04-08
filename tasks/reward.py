"""任务奖励领取。"""

from __future__ import annotations

import pyautogui

from core.base.step_result import StepResult
from core.ui.assets import ASSET_NAME_TO_CONST, BTN_CLAIM, BTN_CLOSE, BTN_CONFIRM, TASK_CHECK
from tasks.base import TaskBase

# TODO: `btn_share` asset 已删除，当前双倍分享领奖流程会自动跳过。
BTN_SHARE = ASSET_NAME_TO_CONST.get('btn_share')


class TaskReward(TaskBase):
    """封装 `TaskReward` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)

    def run(self, rect, features) -> StepResult:
        """执行当前模块主流程并返回结果。"""
        if not self.has_feature(features, 'auto_task'):
            return StepResult()
        if not self.ui.appear_then_click(TASK_CHECK, offset=(30, 30), interval=1, threshold=0.8, static=False):
            return StepResult()
        self.ui.device.sleep(0.6)
        out = StepResult.from_value(self._handle_task_result(rect))
        return out

    def _share_and_cancel(self) -> str:
        """点击分享领奖后用 Esc 取消分享面板，回到游戏页面。"""
        if BTN_SHARE is None:
            return '取消领取双倍任务奖励'
        if not self.ui.appear_then_click(BTN_SHARE, offset=(30, 30), interval=1, threshold=0.8, static=False):
            return '取消领取双倍任务奖励'
        self.ui.device.sleep(2.0)

        pyautogui.press('escape')
        self.ui.device.sleep(1.0)
        return '领取双倍任务奖励'

    def _handle_task_result(self, rect: tuple[int, int, int, int]) -> list[str]:
        """处理任务完成弹窗：优先双倍分享，其次普通领取。"""
        actions: list[str] = []
        for _ in range(5):
            cv_img = self.ui.device.screenshot(rect=rect, save=False)
            if cv_img is None:
                return actions

            if BTN_SHARE is not None and self.ui.appear(BTN_SHARE, offset=(30, 30), threshold=0.8, static=False):
                self._share_and_cancel()
                actions.append('领取双倍任务奖励')
                self.ui.device.sleep(0.5)
                return actions

            if self.ui.appear_then_click(BTN_CLAIM, offset=(30, 30), interval=1, threshold=0.8, static=False):
                actions.append('领取任务奖励')
                self.ui.device.sleep(0.3)
                return actions

            if self.ui.appear_then_click_any(
                [BTN_CLOSE, BTN_CONFIRM], offset=(30, 30), interval=1, threshold=0.8, static=False
            ):
                self.ui.device.sleep(0.2)
                continue

            self.ui.device.sleep(0.3)
        return actions
