"""策略基类 — 公共方法"""
import time
from dataclasses import dataclass, field
from loguru import logger

from models.farm_state import Action, ActionType
from core.cv_detector import CVDetector, DetectResult


@dataclass
class StrategyResult:
    action: str | None = None
    actions: list[str] = field(default_factory=list)

    @classmethod
    def from_value(cls, value) -> "StrategyResult":
        if isinstance(value, StrategyResult):
            return value
        if value is None:
            return cls()
        if isinstance(value, str):
            return cls(action=value, actions=[value])
        if isinstance(value, list):
            texts = [str(v) for v in value if str(v).strip()]
            return cls(action=(texts[-1] if texts else None), actions=texts)
        text = str(value).strip()
        return cls(action=(text or None), actions=([text] if text else []))


class BaseStrategy:
    requires_page: set[str] = set()
    expected_page_after: set[str] = set()

    def __init__(self, cv_detector: CVDetector):
        self.cv_detector = cv_detector
        self.action_executor = None
        self._capture_fn = None
        self._stop_requested = False
        self._cancel_checker = None
        self._action_hook = None
        self._action_cooldown_seconds = 0.45
        self._action_next_allowed: dict[str, float] = {}

    def set_capture_fn(self, fn):
        self._capture_fn = fn

    def set_cancel_checker(self, fn):
        self._cancel_checker = fn

    def set_action_hook(self, fn):
        self._action_hook = fn

    @property
    def stopped(self) -> bool:
        if self._cancel_checker and self._cancel_checker():
            return True
        return self._stop_requested

    def sleep(self, seconds: float, interval: float = 0.02) -> bool:
        """可中断等待，返回是否完整等待结束。"""
        if seconds <= 0:
            return not self.stopped
        end_at = time.perf_counter() + seconds
        while True:
            if self.stopped:
                return False
            remaining = end_at - time.perf_counter()
            if remaining <= 0:
                return True
            time.sleep(min(interval, remaining))

    def capture(self, rect: tuple):
        if self._capture_fn:
            return self._capture_fn(rect, save=False)
        return None, [], None

    def click(self, x: int, y: int, desc: str = "",
              action_type: str = ActionType.NAVIGATE) -> bool:
        if not self.action_executor or self.stopped:
            return False
        key = f"{action_type}:{desc}"
        now = time.perf_counter()
        allow_at = self._action_next_allowed.get(key, 0.0)
        if now < allow_at:
            logger.debug(f"动作冷却中，跳过点击: {desc} ({allow_at - now:.2f}s)")
            return False
        action = Action(type=action_type, click_position={"x": x, "y": y},
                        priority=0, description=desc)
        result = self.action_executor.execute_action(action)
        if result.success:
            self._action_next_allowed[key] = now + max(0.0, self._action_cooldown_seconds)
            logger.info(f"✓ {desc}")
            if self._action_hook:
                try:
                    self._action_hook(desc, action.type)
                except Exception:
                    pass
        else:
            logger.warning(f"✗ {desc}: {result.message}")
        return result.success

    def find_by_name(self, detections: list[DetectResult], name: str) -> DetectResult | None:
        for d in detections:
            if d.name == name:
                return d
        return None

    def find_by_prefix_first(self, detections: list[DetectResult], prefix: str) -> DetectResult | None:
        for d in detections:
            if d.name.startswith(prefix):
                return d
        return None

    def find_any(self, detections: list[DetectResult], names: list[str]) -> DetectResult | None:
        name_set = set(names)
        for d in detections:
            if d.name in name_set:
                return d
        return None

    def click_blank(self, rect: tuple):
        """点击天空区域关闭弹窗"""
        w, h = rect[2], rect[3]
        self.click(w // 2, int(h * 0.15), "点击空白处")

    def handle_basic_popup(self, detections: list[DetectResult]) -> str | None:
        """关闭常见弹窗：领取/确认/关闭/取消。"""
        for btn_name in ("btn_claim", "btn_confirm", "btn_close", "btn_cancel"):
            det = self.find_by_name(detections, btn_name)
            if det:
                label = btn_name.replace("btn_", "")
                self.click(det.x, det.y, f"关闭弹窗({label})", ActionType.CLOSE_POPUP)
                return f"关闭弹窗({label})"
        return None

    def close_shop_page(self, rect: tuple, max_attempts: int = 3) -> str | None:
        """关闭商店页面。"""
        for _ in range(max(1, int(max_attempts))):
            cv_img, dets, _ = self.capture(rect)
            if cv_img is None:
                return None
            shop_close = self.cv_detector.detect_single_template(
                cv_img, "btn_shop_close", threshold=0.8
            )
            close_btn = shop_close[0] if shop_close else self.find_by_name(dets, "btn_close")
            if not close_btn:
                return None
            self.click(close_btn.x, close_btn.y, "关闭商店", ActionType.CLOSE_POPUP)
            self.sleep(0.3)
        return "关闭商店"

    def run_once(self, *args, **kwargs) -> StrategyResult:
        """策略契约统一入口：子类逐步覆盖。"""
        return StrategyResult()

