"""Bot 截图、识别与点击桥接逻辑。"""

from __future__ import annotations

import time

import cv2
import numpy as np
from PIL import Image as PILImage

from core.vision.cv_detector import DetectResult
from models.config import RunMode, resolve_effective_run_mode
from models.farm_state import Action, ActionType


class BotVisionMixin:
    """Bot 截图、识别与点击桥接逻辑。"""

    def _prepare_window(self) -> tuple | None:
        """刷新并激活窗口，返回当前有效截图区域。"""
        window = self.window_manager.refresh_window_info(self.config.window_title_keyword)
        if not window:
            return None
        effective_mode = resolve_effective_run_mode(self.config.safety.run_mode, self.config.planting.window_platform)
        if effective_mode == RunMode.FOREGROUND:
            self.window_manager.activate_window()
            time.sleep(0.3)
        rect = self.window_manager.get_capture_rect()
        if not rect:
            rect = (window.left, window.top, window.width, window.height)
        if self.action_executor:
            self.action_executor.update_window_rect(rect)
            self.action_executor.update_window_handle(window.hwnd)
        if self.device:
            self.device.set_rect(rect)
        return rect

    def _emit_annotated(self, cv_image: np.ndarray, detections: list[DetectResult]):
        """将识别结果绘制为标注图并推送到界面。"""
        if detections:
            annotated = self.cv_detector.draw_results(cv_image, detections)
            annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            annotated_pil = PILImage.fromarray(annotated_rgb)
            detection_sender = getattr(self, 'emit_detection_preview', None)
            if callable(detection_sender):
                detection_sender(annotated_pil)
            else:
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

    def _handle_seed_select_scene(self, detections: list[DetectResult]) -> str | None:
        """处理种子选择场景：命中目标种子后执行点击播种。"""
        crop_name = self._resolve_crop_name()
        seed = next((d for d in detections if d.name == f'seed_{crop_name}'), None)
        if not seed:
            return None
        if not self.action_executor:
            return None
        rel_x, rel_y = self.resolve_live_click_point(int(seed.x), int(seed.y))
        action = Action(
            type=ActionType.PLANT,
            click_position={'x': int(rel_x), 'y': int(rel_y)},
            priority=0,
            description=f'播种{crop_name}',
        )
        result = self.action_executor.execute_action(action)
        if not result.success:
            return None
        self._record_stat(ActionType.PLANT)
        return f'播种{crop_name}'
