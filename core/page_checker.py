"""页面检查器：按页面检查点（局部 ROI）优先识别场景。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from core.cv_detector import CVDetector, DetectResult
from core.scene_detector import Scene


@dataclass(frozen=True)
class _Rule:
    scene: Scene
    templates: tuple[str, ...]
    roi_px: tuple[int, int, int, int] | None = None
    roi_ratio: tuple[float, float, float, float] | None = None
    threshold: float = 0.8


class PageChecker:
    """仿 NIKKE 的页面检查思路：固定页面检查点优先，而非全量模板推断。"""

    def __init__(self, detector: CVDetector, rules: dict[str, Any] | None = None):
        self.detector = detector
        cfg = dict(rules or {})

        scene_rules = cfg.get("scene_rules", [])
        parsed_rules: list[_Rule] = []
        for item in scene_rules:
            if not isinstance(item, dict):
                continue
            scene = self._to_scene(item.get("scene"))
            templates = tuple(str(x) for x in item.get("templates", []) if str(x).strip())
            if scene == Scene.UNKNOWN or not templates:
                continue
            roi_px = self._to_roi_px(item.get("roi_px"))
            ratio = self._to_ratio(item.get("roi_ratio"))
            threshold = float(item.get("threshold", 0.8))
            parsed_rules.append(
                _Rule(
                    scene=scene,
                    templates=templates,
                    roi_px=roi_px,
                    roi_ratio=ratio,
                    threshold=threshold,
                )
            )
        self._rules: tuple[_Rule, ...] = tuple(parsed_rules)

        self._hint_to_scene: dict[str, Scene] = {}
        hint_map = cfg.get("hint_to_scene", {})
        if isinstance(hint_map, dict):
            for key, value in hint_map.items():
                scene = self._to_scene(value)
                if scene != Scene.UNKNOWN:
                    self._hint_to_scene[str(key)] = scene

        farm_templates = cfg.get("farm_templates", [])
        self._farm_templates = [str(x) for x in farm_templates if str(x).strip()]

        self._farm_thresholds: dict[str, float] = {}
        farm_thresholds = cfg.get("farm_thresholds", {})
        if isinstance(farm_thresholds, dict):
            for key, value in farm_thresholds.items():
                self._farm_thresholds[str(key)] = float(value)

        self._farm_roi_px: dict[str, tuple[int, int, int, int]] = {}
        farm_roi_px = cfg.get("farm_roi_px", {})
        if isinstance(farm_roi_px, dict):
            for key, value in farm_roi_px.items():
                roi_px = self._to_roi_px(value)
                if roi_px is not None:
                    self._farm_roi_px[str(key)] = roi_px

        self._farm_roi_ratios: dict[str, tuple[float, float, float, float]] = {}
        farm_roi_ratios = cfg.get("farm_roi_ratios", {})
        if isinstance(farm_roi_ratios, dict):
            for key, value in farm_roi_ratios.items():
                ratio = self._to_ratio(value)
                if ratio is not None:
                    self._farm_roi_ratios[str(key)] = ratio

    @staticmethod
    def _to_scene(raw: Any) -> Scene:
        if isinstance(raw, Scene):
            return raw
        try:
            return Scene(str(raw))
        except Exception:
            return Scene.UNKNOWN

    @staticmethod
    def _to_ratio(raw: Any) -> tuple[float, float, float, float] | None:
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return None
        try:
            return float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
        except Exception:
            return None

    @staticmethod
    def _to_roi_px(raw: Any) -> tuple[int, int, int, int] | None:
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return None
        try:
            x1 = int(raw[0])
            y1 = int(raw[1])
            x2 = int(raw[2])
            y2 = int(raw[3])
            return x1, y1, x2, y2
        except Exception:
            return None

    @staticmethod
    def _clamp_roi(
        roi: tuple[int, int, int, int] | None,
        width: int,
        height: int,
    ) -> tuple[int, int, int, int] | None:
        if roi is None:
            return None
        x1, y1, x2, y2 = roi
        x1 = max(0, min(x1, width - 1))
        y1 = max(0, min(y1, height - 1))
        x2 = max(0, min(x2, width))
        y2 = max(0, min(y2, height))
        x2 = max(x1 + 1, min(x2, width))
        y2 = max(y1 + 1, min(y2, height))
        return x1, y1, x2, y2

    @staticmethod
    def _ratio_to_abs(
        ratio: tuple[float, float, float, float] | None,
        width: int,
        height: int,
    ) -> tuple[int, int, int, int] | None:
        if ratio is None:
            return None
        return PageChecker._clamp_roi(
            (
                int(max(0.0, min(1.0, ratio[0])) * width),
                int(max(0.0, min(1.0, ratio[1])) * height),
                int(max(0.0, min(1.0, ratio[2])) * width),
                int(max(0.0, min(1.0, ratio[3])) * height),
            ),
            width,
            height,
        )

    def _ordered_rules(self, runtime_hint: str | None) -> list[_Rule]:
        if not runtime_hint:
            return list(self._rules)
        hint_scene = self._hint_to_scene.get(str(runtime_hint), Scene.UNKNOWN)
        if hint_scene == Scene.UNKNOWN:
            return list(self._rules)
        preferred = [r for r in self._rules if r.scene == hint_scene]
        rest = [r for r in self._rules if r.scene != hint_scene]
        return preferred + rest

    def _farm_roi_map(self, width: int, height: int) -> dict[str, tuple[int, int, int, int]]:
        roi_map: dict[str, tuple[int, int, int, int]] = {}
        for name, roi in self._farm_roi_px.items():
            abs_roi = self._clamp_roi(roi, width, height)
            if abs_roi is not None:
                roi_map[name] = abs_roi
        for name, ratio in self._farm_roi_ratios.items():
            if name in roi_map:
                continue
            abs_roi = self._ratio_to_abs(ratio, width, height)
            if abs_roi is not None:
                roi_map[name] = abs_roi
        return roi_map

    def detect_scene(
        self,
        cv_image: np.ndarray,
        *,
        runtime_hint: str | None = None,
        crop_name: str | None = None,
    ) -> tuple[Scene, list[DetectResult]]:
        h, w = cv_image.shape[:2]
        for rule in self._ordered_rules(runtime_hint):
            roi_abs = self._clamp_roi(rule.roi_px, w, h) or self._ratio_to_abs(rule.roi_ratio, w, h)
            roi_map = {name: roi_abs for name in rule.templates} if roi_abs else None
            thresholds = {name: rule.threshold for name in rule.templates}
            dets = self.detector.detect_templates(
                cv_image,
                template_names=list(rule.templates),
                default_threshold=rule.threshold,
                thresholds=thresholds,
                roi_map=roi_map,
            )
            if dets:
                return rule.scene, dets

        if crop_name:
            seed_dets = self.detector.detect_seed_template(
                cv_image,
                crop_name_or_template=str(crop_name),
                threshold=0.62,
            )
            if seed_dets:
                return Scene.SEED_SELECT, seed_dets

        farm_templates = list(self._farm_templates)
        farm_thresholds = dict(self._farm_thresholds)
        farm_dets = self.detector.detect_templates(
            cv_image,
            template_names=farm_templates,
            default_threshold=0.8,
            thresholds=farm_thresholds,
            roi_map=self._farm_roi_map(w, h) if (self._farm_roi_px or self._farm_roi_ratios) else None,
        )
        if farm_dets:
            return Scene.FARM_OVERVIEW, farm_dets

        return Scene.UNKNOWN, []
