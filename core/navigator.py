"""页面导航器：页面感知跳转与 ensure 入口。"""
from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger

from core.cv_detector import CVDetector, DetectResult
from core.page_graph import NavAction, PageGraph, PageId, scene_to_page
from core.scene_detector import identify_scene
from models.farm_state import ActionType


CaptureFn = Callable[
    [tuple, str, list[str] | None, bool],
    tuple[object | None, list[DetectResult], object | None],
]


class Navigator:
    def __init__(
        self,
        cv_detector: CVDetector,
        popup_strategy,
        capture_fn: Callable,
        cancel_checker: Callable[[], bool] | None = None,
        page_graph: PageGraph | None = None,
    ):
        self.cv_detector = cv_detector
        self.popup = popup_strategy
        self.capture_fn = capture_fn
        self.cancel_checker = cancel_checker
        self.page_graph = page_graph or PageGraph()

    def _is_cancelled(self) -> bool:
        return bool(self.cancel_checker and self.cancel_checker())

    def _sleep_interruptible(self, seconds: float, interval: float = 0.03) -> bool:
        if seconds <= 0:
            return not self._is_cancelled()
        end_at = time.perf_counter() + seconds
        while True:
            if self._is_cancelled():
                return False
            remain = end_at - time.perf_counter()
            if remain <= 0:
                return True
            time.sleep(min(interval, remain))

    def get_current_page(
        self,
        rect: tuple,
        timeout: float = 1.5,
        stable_hits: int = 2,
    ) -> tuple[PageId, list[DetectResult]]:
        """获取当前页面，带连续帧确认。"""
        deadline = time.perf_counter() + max(0.2, timeout)
        candidate = PageId.UNKNOWN
        candidate_hits = 0
        last_dets: list[DetectResult] = []

        while time.perf_counter() < deadline:
            if self._is_cancelled():
                break
            cv_image, detections, _ = self.capture_fn(rect, "nav", None, False)
            if cv_image is None:
                continue
            scene = identify_scene(detections, self.cv_detector, cv_image)
            page = scene_to_page(scene)
            last_dets = detections

            if page == candidate:
                candidate_hits += 1
            else:
                candidate = page
                candidate_hits = 1

            if candidate_hits >= max(1, stable_hits):
                return candidate, detections
            if not self._sleep_interruptible(0.08):
                break

        # 超时仍未达到稳定帧要求时，统一回落 UNKNOWN，避免误判页面。
        return PageId.UNKNOWN, last_dets

    def _do_action(self, rect: tuple, detections: list[DetectResult], action: NavAction) -> bool:
        if action.click_blank:
            self.popup.click_blank(rect)
            return True

        for name in action.candidates:
            det = self.popup.find_by_name(detections, name)
            if det:
                self.popup.click(det.x, det.y, action.description, ActionType.NAVIGATE)
                return True
        for prefix in action.candidate_prefixes:
            det = self.popup.find_by_prefix_first(detections, prefix)
            if det:
                self.popup.click(det.x, det.y, action.description, ActionType.NAVIGATE)
                return True
        return False

    def goto(
        self,
        rect: tuple,
        target: PageId,
        timeout: float = 4.0,
        confirm_wait: float = 0.25,
        stable_hits: int = 1,
    ) -> bool:
        """跳转到目标页面，超时返回 False。"""
        deadline = time.perf_counter() + max(0.5, timeout)
        while time.perf_counter() < deadline:
            if self._is_cancelled():
                return False
            current, detections = self.get_current_page(
                rect=rect,
                timeout=0.7,
                stable_hits=stable_hits,
            )
            if current == target:
                return True

            action = self.page_graph.next_action(current, target)
            if not action:
                logger.debug(f"导航无路径: {current.value} -> {target.value}，执行兜底点击空白处")
                self.popup.click_blank(rect)
            else:
                acted = self._do_action(rect, detections, action)
                if not acted:
                    logger.debug(
                        f"导航动作缺少按钮: action={action.name}, current={current.value}, "
                        f"target={target.value}"
                    )
                    self.popup.click_blank(rect)
            if not self._sleep_interruptible(confirm_wait):
                return False
        return False

    def ensure(
        self,
        rect: tuple,
        target: PageId,
        timeout: float = 4.0,
        confirm_wait: float = 0.25,
    ) -> bool:
        current, _ = self.get_current_page(rect=rect, timeout=0.8, stable_hits=1)
        if current == target:
            return True
        return self.goto(
            rect=rect,
            target=target,
            timeout=timeout,
            confirm_wait=confirm_wait,
            stable_hits=1,
        )
