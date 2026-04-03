"""页面导航器：页面感知跳转与 ensure 入口。"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from core.cv_detector import CVDetector, DetectResult
from core.page_graph import NavAction, PageGraph, PageId, scene_to_page
from core.scene_detector import identify_scene
from models.farm_state import ActionType


CaptureFn = Callable[..., tuple[object | None, list[DetectResult], object | None]]


class Navigator:
    def __init__(
        self,
        cv_detector: CVDetector,
        popup_strategy,
        capture_fn: CaptureFn,
        cancel_checker: Callable[[], bool] | None = None,
        page_graph: PageGraph | None = None,
        rules: dict[str, Any] | None = None,
    ):
        self.cv_detector = cv_detector
        self.popup = popup_strategy
        self.capture_fn = capture_fn
        self.cancel_checker = cancel_checker
        self.page_graph = page_graph or PageGraph()
        cfg = dict(rules or {})
        self._nav_templates = tuple(str(x) for x in cfg.get("templates", []) if str(x).strip())
        self._nav_thresholds = {
            str(k): float(v) for k, v in dict(cfg.get("thresholds", {})).items()
        }
        self._nav_roi_px: dict[str, tuple[int, int, int, int]] = {}
        raw_roi_px = cfg.get("roi_px", {})
        if isinstance(raw_roi_px, dict):
            for name, roi in raw_roi_px.items():
                if not isinstance(roi, (list, tuple)) or len(roi) != 4:
                    continue
                try:
                    self._nav_roi_px[str(name)] = (
                        int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])
                    )
                except Exception:
                    continue
        self._nav_roi_ratios: dict[str, tuple[float, float, float, float]] = {}
        raw_ratios = cfg.get("roi_ratios", {})
        if isinstance(raw_ratios, dict):
            for name, ratio in raw_ratios.items():
                if not isinstance(ratio, (list, tuple)) or len(ratio) != 4:
                    continue
                try:
                    self._nav_roi_ratios[str(name)] = (
                        float(ratio[0]), float(ratio[1]), float(ratio[2]), float(ratio[3])
                    )
                except Exception:
                    continue

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

    def _build_roi_map(self, rect: tuple) -> dict[str, tuple[int, int, int, int]]:
        width = int(rect[2])
        height = int(rect[3])
        roi_map: dict[str, tuple[int, int, int, int]] = {}
        for name, roi in self._nav_roi_px.items():
            x1 = max(0, min(int(roi[0]), width - 1))
            y1 = max(0, min(int(roi[1]), height - 1))
            x2 = max(0, min(int(roi[2]), width))
            y2 = max(0, min(int(roi[3]), height))
            x2 = max(x1 + 1, min(x2, width))
            y2 = max(y1 + 1, min(y2, height))
            roi_map[name] = (x1, y1, x2, y2)
        for name, ratio in self._nav_roi_ratios.items():
            if name in roi_map:
                continue
            x1 = int(max(0.0, min(1.0, ratio[0])) * width)
            y1 = int(max(0.0, min(1.0, ratio[1])) * height)
            x2 = int(max(0.0, min(1.0, ratio[2])) * width)
            y2 = int(max(0.0, min(1.0, ratio[3])) * height)
            x2 = max(x1 + 1, min(x2, width))
            y2 = max(y1 + 1, min(y2, height))
            roi_map[name] = (x1, y1, x2, y2)
        return roi_map

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
            cv_image, detections, _ = self.capture_fn(
                rect,
                prefix="nav",
                categories=None,
                template_names=list(self._nav_templates),
                template_thresholds=self._nav_thresholds,
                template_rois=self._build_roi_map(rect),
                save=False,
            )
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
