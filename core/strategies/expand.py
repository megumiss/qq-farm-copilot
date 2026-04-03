"""P3 资源 — 扩建土地 + 领取任务"""
import time
from loguru import logger

from models.farm_state import ActionType
from core.cv_detector import DetectResult
from core.strategies.base import BaseStrategy


class ExpandStrategy(BaseStrategy):

    def __init__(self, cv_detector):
        super().__init__(cv_detector)
        self._expand_failed = False

    def try_expand(self, rect: tuple, detections: list[DetectResult]) -> str | None:
        """检测可扩建并执行"""
        if self._expand_failed:
            return None
        btn = self.find_by_name(detections, "btn_expand")
        if not btn:
            return None

        self.click(btn.x, btn.y+10, "点击可扩建")
        self.sleep(0.5)

        for _ in range(5):
            if self.stopped:
                return None
            cv_img, dets, _ = self.capture(rect)
            if cv_img is None:
                return None

            direct_confirm = self.find_by_name(dets, "btn_expand_direct_confirm")
            normal_confirm = self.find_by_name(dets, "btn_expand_confirm")
            confirm = direct_confirm or normal_confirm
            if confirm:
                action_name = "直接扩建" if direct_confirm else "扩建确认"
                self.click(confirm.x, confirm.y, action_name)
                self.sleep(0.5)
                self._expand_failed = False
                cv_img2, dets2, _ = self.capture(rect)
                if cv_img2 is not None:
                    close = self.find_any(dets2, ["btn_close", "btn_claim"])
                    if close:
                        self.click(close.x, close.y, "关闭扩建弹窗", ActionType.CLOSE_POPUP)
                return action_name
            self.sleep(0.3)

        self._expand_failed = True
        logger.info("扩建条件不满足，暂停扩建检测")
        return None

    def try_claim_task(self, rect: tuple) -> str | None:
        """自动领取任务奖励（待实现：需要 btn_task 模板）"""
        # TODO: 打开任务页面 → 检测可领取 → 点击领取
        return None

