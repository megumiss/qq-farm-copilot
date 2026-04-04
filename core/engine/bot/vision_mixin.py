"""Bot 截图、识别与点击桥接逻辑。"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import cv2
import numpy as np
from loguru import logger
from PIL import Image as PILImage

from core.base.button import Button
from core.engine.task.executor import TaskExecutor
from core.engine.task.registry import (
    TaskContext,
    TaskItem,
    TaskResult,
    TaskSnapshot,
    build_default_tasks,
)
from core.engine.task.scheduler import TaskScheduler
from core.ops import ExpandOps, FriendOps, PlantOps, PopupOps, TaskOps
from core.platform.action_executor import ActionExecutor
from core.platform.device import NKLiteDevice
from core.platform.screen_capture import ScreenCapture
from core.platform.window_manager import WindowManager
from core.tasks.task_farm_main import TaskFarmMain
from core.tasks.task_farm_reward import TaskFarmReward
from core.ui.assets import ASSET_NAME_TO_CONST
from core.ui.page import (
    GOTO_MAIN,
    page_main,
)
from core.ui.ui import UI as NKLiteUI
from core.vision.cv_detector import CVDetector, DetectResult
from models.config import AppConfig, PlantMode, TaskTriggerType
from models.farm_state import Action, ActionType
from models.game_data import get_best_crop_for_level
from utils.template_paths import DEFAULT_TEMPLATE_PLATFORM, normalize_template_platform


class BotVisionMixin:
    """Bot 截图、识别与点击桥接逻辑。"""

    def _prepare_window(self) -> tuple | None:
        """刷新并激活窗口，返回当前有效截图区域。"""
        window = self.window_manager.refresh_window_info(self.config.window_title_keyword)
        if not window:
            return None
        self.window_manager.activate_window()
        if not self._sleep_interruptible(0.3):
            return None
        rect = self.window_manager.get_capture_rect()
        if not rect:
            rect = (window.left, window.top, window.width, window.height)
        if self.action_executor:
            self.action_executor.update_window_rect(rect)
        if self.nk_device:
            self.nk_device.set_rect(rect)
        return rect

    def _crop_preview_image(self, image: PILImage.Image | None) -> PILImage.Image | None:
        """仅用于左侧预览显示：按 nonclient 配置裁掉窗口边框/标题栏。"""
        if image is None:
            return None
        platform = getattr(self.config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        return self.window_manager.crop_window_image_for_preview(image, platform_value)

    def _capture_frame(
        self,
        rect: tuple,
        prefix: str = 'farm',
        save: bool = True,
    ) -> tuple[np.ndarray | None, PILImage.Image | None]:
        """执行一次截图并转换为 OpenCV 图像，同时推送 GUI 预览。"""
        if save:
            image, _ = self.screen_capture.capture_and_save(rect, prefix)
        else:
            image = self.screen_capture.capture_region(rect)
        if image is None:
            return None, None
        preview_image = self._crop_preview_image(image)
        if preview_image is None:
            return None, None
        self.screenshot_updated.emit(preview_image)
        cv_image = self.cv_detector.pil_to_cv2(preview_image)
        return cv_image, preview_image

    def _capture_and_detect(
        self,
        rect: tuple,
        prefix: str = 'farm',
        template_names: list[str] | None = None,
        template_thresholds: dict[str, float] | None = None,
        template_rois: dict[str, tuple[int, int, int, int]] | None = None,
        save: bool = True,
    ) -> tuple[np.ndarray | None, list[DetectResult], PILImage.Image | None]:
        """截图并按指定模板/类别执行识别。"""
        cv_image, image = self._capture_frame(rect, prefix=prefix, save=save)
        if cv_image is None or image is None:
            return None, [], None

        # 非 seed 识别统一走 assets 按钮匹配链路。
        if template_names is not None:
            detections = self._detect_templates_with_assets(
                cv_image,
                template_names=template_names,
                thresholds=template_thresholds,
                roi_map=template_rois,
                default_threshold=0.8,
            )
        else:
            detections = []

        return cv_image, detections, image

    @staticmethod
    def _category_from_template_name(name: str) -> str:
        """按模板名前缀映射 DetectResult 类别。"""
        if name.startswith('btn_'):
            return 'button'
        if name.startswith('icon_'):
            return 'status_icon'
        if name.startswith('land_'):
            return 'land'
        if name.startswith('ui_') or name.endswith('_check') or 'goto' in name:
            return 'ui_element'
        return 'unknown'

    def _detect_templates_with_assets(
        self,
        cv_image: np.ndarray,
        template_names: list[str],
        thresholds: dict[str, float] | None = None,
        roi_map: dict[str, tuple[int, int, int, int]] | None = None,
        default_threshold: float = 0.8,
    ) -> list[DetectResult]:
        """使用 assets 中的 Button 模板执行匹配并输出检测结果。"""
        if cv_image is None or not template_names:
            return []

        sh, sw = cv_image.shape[:2]
        out: list[DetectResult] = []
        seen: set[str] = set()
        for raw_name in template_names:
            name = str(raw_name or '').strip()
            if not name or name in seen:
                continue
            seen.add(name)

            btn = ASSET_NAME_TO_CONST.get(name)
            if btn is None:
                logger.debug(f'assets 模板缺失: {name}')
                continue
            btn.ensure_template()
            tpl = btn.image
            if tpl is None:
                logger.debug(f'assets 模板读取失败: {name}')
                continue

            th, tw = tpl.shape[:2]
            threshold = float(thresholds.get(name, default_threshold) if thresholds else default_threshold)
            roi = roi_map.get(name) if roi_map else None

            x_offset = 0
            y_offset = 0
            search = cv_image
            if roi is not None:
                x1, y1, x2, y2 = [int(v) for v in roi]
                x1 = max(0, min(x1, sw - 1))
                y1 = max(0, min(y1, sh - 1))
                x2 = max(x1 + 1, min(x2, sw))
                y2 = max(y1 + 1, min(y2, sh))
                if x2 <= x1 or y2 <= y1:
                    continue
                search = cv_image[y1:y2, x1:x2]
                x_offset = x1
                y_offset = y1

            rh, rw = search.shape[:2]
            if tw >= rw or th >= rh:
                continue

            match_result = cv2.matchTemplate(search, tpl, cv2.TM_CCOEFF_NORMED)
            finite = np.isfinite(match_result)
            if not finite.all():
                match_result = np.where(finite, match_result, -1.0)
            locations = np.where(match_result >= threshold)
            if locations[0].size == 0:
                continue

            max_hits = 64 if name.startswith('land_') else 8
            if locations[0].size > max_hits:
                scores = match_result[locations]
                top_idx = np.argpartition(scores, -max_hits)[-max_hits:]
                pt_ys = locations[0][top_idx]
                pt_xs = locations[1][top_idx]
            else:
                pt_ys, pt_xs = locations

            category = self._category_from_template_name(name)
            for pt_y, pt_x in zip(pt_ys, pt_xs):
                confidence = float(match_result[pt_y, pt_x])
                center_x = int(x_offset + pt_x + tw // 2)
                center_y = int(y_offset + pt_y + th // 2)
                extra = {}
                if roi is not None:
                    extra['roi'] = (x_offset, y_offset, x_offset + rw, y_offset + rh)
                out.append(
                    DetectResult(
                        name=name,
                        category=category,
                        x=center_x,
                        y=center_y,
                        w=int(tw),
                        h=int(th),
                        confidence=confidence,
                        extra=extra,
                    )
                )

        out = self.cv_detector._nms(out, iou_threshold=0.5)
        out.sort(key=lambda r: r.confidence, reverse=True)
        return out

    def _nklite_screenshot(self, rect: tuple[int, int, int, int]) -> np.ndarray | None:
        """nklite 设备截图回调。"""
        cv_image, _ = self._capture_frame(rect, save=False)
        return cv_image

    def _nklite_click(self, x: int, y: int, desc: str) -> bool:
        """nklite 点击回调：统一封装为 ActionExecutor 行为。"""
        if not self.action_executor:
            return False
        rel_x, rel_y = self.resolve_live_click_point(int(x), int(y))
        action = Action(
            type=ActionType.NAVIGATE,
            click_position={'x': int(rel_x), 'y': int(rel_y)},
            priority=0,
            description=str(desc or 'nklite_click'),
        )
        result = self.action_executor.execute_action(action)
        return bool(result.success)

    def _nklite_sleep(self, seconds: float) -> bool:
        """nklite 睡眠回调：复用可中断睡眠。"""
        return self._sleep_interruptible(seconds)

    def _emit_annotated(self, cv_image: np.ndarray, detections: list[DetectResult]):
        """将识别结果绘制为标注图并推送到界面。"""
        if detections:
            annotated = self.cv_detector.draw_results(cv_image, detections)
            annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            annotated_pil = PILImage.fromarray(annotated_rgb)
            self.detection_result.emit(annotated_pil)

    def _record_stat(self, action_type: str):
        """将动作类型映射到统计项并累加。"""
        type_map = {
            ActionType.HARVEST: 'harvest',
            ActionType.PLANT: 'plant',
            ActionType.WATER: 'water',
            ActionType.WEED: 'weed',
            ActionType.BUG: 'bug',
            ActionType.STEAL: 'steal',
            ActionType.SELL: 'sell',
        }
        stat_key = type_map.get(action_type)
        if stat_key:
            self.scheduler.record_action(stat_key)

    def _augment_detections(
        self,
        cv_image: np.ndarray,
        detections: list[DetectResult],
        template_names: list[str],
        thresholds: dict[str, float] | None = None,
        default_threshold: float = 0.8,
    ) -> list[DetectResult]:
        """仅补齐缺失模板，避免每轮重复跑大集合识别。"""
        base = list(detections or [])
        wanted = [str(name).strip() for name in template_names if str(name).strip()]
        if not wanted:
            return base

        existing = {d.name for d in base}
        missing = [name for name in wanted if name not in existing]
        if not missing:
            return base

        extra = self._detect_templates_with_assets(
            cv_image,
            template_names=missing,
            thresholds=thresholds,
            default_threshold=default_threshold,
        )
        if not extra:
            return base

        merged = base + extra
        return self.cv_detector._nms(merged, iou_threshold=0.5)

    def _handle_seed_select_scene(self, detections: list[DetectResult]) -> str | None:
        """处理种子选择场景：命中目标种子后执行点击播种。"""
        crop_name = self._resolve_crop_name()
        seed = self.popup.find_by_name(detections, f'seed_{crop_name}')
        if not seed:
            return None
        self.popup.click(seed.x, seed.y, f'播种{crop_name}', ActionType.PLANT)
        self._record_stat(ActionType.PLANT)
        return f'播种{crop_name}'
