"""P-1 异常处理 — 关闭弹窗/商店/任务奖励分享"""
import pyautogui
from loguru import logger

from models.farm_state import ActionType
from core.cv_detector import DetectResult
from core.strategies.base import BaseStrategy, StrategyResult


class PopupStrategy(BaseStrategy):
    requires_page = {"popup", "buy_confirm", "shop", "unknown"}
    expected_page_after = {"main", "popup", "plot_menu", "seed_select", "shop", "buy_confirm"}

    def handle_popup(self, detections: list[DetectResult]) -> str | None:
        """处理弹窗：分享(双倍奖励) > 领取 > 确认 > 关闭 > 取消"""
        # 优先检测分享按钮（任务奖励弹窗，拿双倍）
        share_btn = self.find_by_name(detections, "btn_share")
        if share_btn:
            return self._share_and_cancel(share_btn)

        for btn_name in ["btn_claim", "btn_confirm", "btn_close", "btn_cancel"]:
            det = self.find_by_name(detections, btn_name)
            if det:
                label = btn_name.replace("btn_", "")
                self.click(det.x, det.y, f"关闭弹窗({label})", ActionType.CLOSE_POPUP)
                return f"关闭弹窗({label})"
        return None

    def _share_and_cancel(self, share_btn: DetectResult) -> str:
        """点分享 → 等微信窗口弹出 → 点取消 → 回游戏，拿双倍奖励

        微信分享窗口"取消"按钮在窗口右下角，位置相对固定。
        点取消后游戏不检测是否真的分享了，直接发放双倍奖励。
        """
        if self.stopped:
            return "取消领取双倍任务奖励(停止中)"
        self.click(share_btn.x, share_btn.y, "点击分享(双倍奖励)", ActionType.CLOSE_POPUP)
        if not self.sleep(2.0):  # 等待微信分享窗口弹出
            return "取消领取双倍任务奖励(停止中)"

        # 按 Escape 关闭微信分享窗口（比找取消按钮更可靠）
        if self.stopped:
            return "取消领取双倍任务奖励(停止中)"
        pyautogui.press("escape")
        if not self.sleep(1.0):  # 等待窗口关闭，回到游戏
            return "取消领取双倍任务奖励(停止中)"

        logger.info("任务奖励: 分享→取消，领取双倍奖励")
        return "领取双倍任务奖励"

    def close_shop(self, rect: tuple):
        """关闭商店页面"""
        self.close_shop_page(rect, max_attempts=3)

    def run_once(self, detections: list[DetectResult], **_kwargs) -> StrategyResult:
        return StrategyResult.from_value(self.handle_popup(detections))

