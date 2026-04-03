"""P3.5 任务 — 点击任务条，自动领取任务奖励

流程：
  检测 btn_task（左下角任务条）→ 点击 →
    - 任务奖励弹窗 → 分享领双倍 / 直接领取
    - 其他弹窗 → 关闭

需要模板：
  btn_task          — 左下角任务提示条
"""
import pyautogui
from loguru import logger

from models.farm_state import ActionType
from core.cv_detector import DetectResult
from core.strategies.base import BaseStrategy, StrategyResult


class TaskStrategy(BaseStrategy):
    requires_page = {"main", "popup"}
    expected_page_after = {"main", "popup"}

    def __init__(self, cv_detector):
        super().__init__(cv_detector)

    def try_task(self, rect: tuple, detections: list[DetectResult]) -> list[str]:
        """检测任务条并执行"""
        btn = self.find_by_name(detections, "btn_task")
        if not btn:
            return []

        self.click(btn.x, btn.y, "点击任务")
        self.sleep(1.0)  # 等待任务弹窗或页面跳转

        return self._handle_task_result(rect)

    def _handle_task_result(self, rect: tuple) -> list[str]:
        """根据点击任务后的页面判断执行什么"""
        actions = []

        for attempt in range(5):
            if self.stopped:
                return actions
            cv_img, dets, _ = self.capture(rect)
            if cv_img is None:
                return actions

            names = {d.name for d in dets}

            # 任务奖励弹窗 → 分享或领取（由 popup 策略处理）
            if {"btn_share", "btn_claim"} & names:
                share = self.find_by_name(dets, "btn_share")
                if share:
                    self._share_and_cancel(share)
                    actions.append("领取双倍任务奖励")
                else:
                    claim = self.find_by_name(dets, "btn_claim")
                    if claim:
                        self.click(claim.x, claim.y, "直接领取", ActionType.CLOSE_POPUP)
                        actions.append("领取任务奖励")
                self.sleep(0.5)
                return actions

            # 其他弹窗 → 关闭
            close = self.find_any(dets, ["btn_close", "btn_confirm", "btn_cancel"])
            if close:
                self.click(close.x, close.y, "关闭弹窗", ActionType.CLOSE_POPUP)
                return actions

            self.sleep(0.3)

        return actions

    def _share_and_cancel(self, share_btn: DetectResult):
        """点分享 → 按 Escape 关闭微信窗口 → 拿双倍奖励"""
        if self.stopped:
            return
        self.click(share_btn.x, share_btn.y, "点击分享(双倍奖励)", ActionType.CLOSE_POPUP)
        if not self.sleep(2.0):  # 等待微信分享窗口弹出
            return
        if self.stopped:
            return
        pyautogui.press("escape")
        self.sleep(1.0)  # 等待回到游戏
        logger.info("任务: 分享→取消，领取双倍奖励")

    def run_once(self, rect: tuple, detections: list[DetectResult], **_kwargs) -> StrategyResult:
        return StrategyResult.from_value(self.try_task(rect, detections))

