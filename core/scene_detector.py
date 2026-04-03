"""场景识别层 — 根据检测结果判断当前画面场景"""
import time
from enum import Enum
import numpy as np
from core.cv_detector import CVDetector, DetectResult


class Scene(str, Enum):
    """当前画面场景"""
    FARM_OVERVIEW = "farm_overview"
    FRIEND_FARM = "friend_farm"
    PLOT_MENU = "plot_menu"
    SEED_SELECT = "seed_select"
    SHOP_PAGE = "shop_page"
    BUY_CONFIRM = "buy_confirm"
    POPUP = "popup"
    LEVEL_UP = "level_up"
    UNKNOWN = "unknown"


_NOISE_EXEMPT_NAMES = {
    "btn_home", "btn_shop", "btn_shop_close",
    "btn_buy_confirm", "btn_buy_max",
    "btn_close", "btn_confirm", "btn_cancel", "btn_claim", "btn_share",
    "btn_plant", "btn_remove", "btn_fertilize",
}


def _core_identify_scene(names: set[str]) -> Scene:
    if {"btn_buy_confirm", "btn_buy_max"} & names:
        return Scene.BUY_CONFIRM

    if "btn_shop_close" in names and "btn_shop" not in names:
        return Scene.SHOP_PAGE

    if "btn_home" in names:
        return Scene.FRIEND_FARM

    if {"btn_plant", "btn_remove", "btn_fertilize"} & names:
        return Scene.PLOT_MENU

    if any(n.startswith("seed_") for n in names):
        return Scene.SEED_SELECT

    if {"btn_close", "btn_claim", "btn_confirm", "btn_cancel"} & names:
        if "icon_levelup" in names:
            return Scene.LEVEL_UP
        return Scene.POPUP

    farm_indicators = {
        "crop_mature", "crop_dead", "crop_growing",
        "icon_mature", "icon_weed", "icon_bug", "icon_water",
        "btn_shop", "btn_harvest", "btn_weed", "btn_bug", "btn_water",
        "btn_friend_help", "btn_expand",
    }
    has_land = any(n.startswith("land_empty") for n in names)
    if has_land or (names & farm_indicators):
        return Scene.FARM_OVERVIEW

    return Scene.UNKNOWN


def _reduce_names_for_scene(
    detections: list[DetectResult],
    min_confidence: float,
    max_hits_per_name: int,
    noisy_repeat_cap: int | None = None,
) -> set[str]:
    grouped: dict[str, list[DetectResult]] = {}
    for d in detections:
        grouped.setdefault(d.name, []).append(d)

    names: set[str] = set()
    for name, items in grouped.items():
        items.sort(key=lambda x: x.confidence, reverse=True)
        if len(items) > max_hits_per_name:
            continue
        if (
            noisy_repeat_cap is not None
            and len(items) > noisy_repeat_cap
            and name not in _NOISE_EXEMPT_NAMES
        ):
            continue
        if items[0].confidence < min_confidence:
            continue
        names.add(name)
    return names


def identify_scene(detections: list[DetectResult], detector: CVDetector,
                   cv_image: np.ndarray,
                   *,
                   strict_min_confidence: float = 0.82,
                   strict_max_hits_per_name: int = 10,
                   strict_noisy_repeat_cap: int = 24,
                   fallback_min_confidence: float = 0.70,
                   fallback_max_hits_per_name: int = 1_000_000,
                   fallback_noisy_repeat_cap: int = 80) -> Scene:
    """根据检测结果识别当前场景"""
    # 阶段1（严格）：过滤低置信度 + 过滤高重复噪声模板，先做稳健判定。
    strict_names = _reduce_names_for_scene(
        detections=detections,
        min_confidence=strict_min_confidence,
        max_hits_per_name=strict_max_hits_per_name,
        noisy_repeat_cap=strict_noisy_repeat_cap,
    )
    strict_scene = _core_identify_scene(strict_names)
    if strict_scene != Scene.UNKNOWN:
        return strict_scene

    # 阶段2（回退）：仅按每个名称的最佳候选放宽判定，避免漏检。
    fallback_names = _reduce_names_for_scene(
        detections=detections,
        min_confidence=fallback_min_confidence,
        max_hits_per_name=fallback_max_hits_per_name,
        noisy_repeat_cap=fallback_noisy_repeat_cap,
    )
    return _core_identify_scene(fallback_names)


class SceneStabilityTracker:
    """场景稳定确认器：连续命中 + 超时回落 UNKNOWN。"""

    def __init__(
        self,
        stable_hits: int = 2,
        level_up_hits: int = 1,
        confirm_timeout: float = 1.0,
    ):
        self.stable_hits = max(1, int(stable_hits))
        self.level_up_hits = max(1, int(level_up_hits))
        self.confirm_timeout = max(0.1, float(confirm_timeout))
        self._candidate = Scene.UNKNOWN
        self._hits = 0
        self._candidate_since = 0.0

    @property
    def candidate(self) -> Scene:
        return self._candidate

    @property
    def hits(self) -> int:
        return self._hits

    def reset(self):
        self._candidate = Scene.UNKNOWN
        self._hits = 0
        self._candidate_since = 0.0

    def feed(self, raw_scene: Scene) -> Scene | None:
        now = time.perf_counter()
        if raw_scene == self._candidate:
            self._hits += 1
        else:
            self._candidate = raw_scene
            self._hits = 1
            self._candidate_since = now

        required_hits = self.level_up_hits if raw_scene == Scene.LEVEL_UP else self.stable_hits
        if self._hits >= required_hits:
            return raw_scene

        if self._candidate_since and (now - self._candidate_since) >= self.confirm_timeout:
            self.reset()
            return Scene.UNKNOWN

        return None
