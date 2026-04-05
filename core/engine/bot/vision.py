"""Bot 截图、识别与点击桥接逻辑。"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image as PILImage

from core.vision.cv_detector import DetectResult
from models.farm_state import Action, ActionType


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
        self, rect: tuple, prefix: str = 'farm', save: bool = True
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
        """截图并返回图像；模板识别由业务侧按需调用 detector。"""
        _ = (template_names, template_thresholds, template_rois)
        cv_image, image = self._capture_frame(rect, prefix=prefix, save=save)
        if cv_image is None or image is None:
            return None, [], None

        return cv_image, [], image

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
