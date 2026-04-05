"""设备能力封装：桥接 BotEngine 截图与点击。"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image as PILImage

from core.base.button import Button
from models.farm_state import Action, ActionType


class DeviceStuckError(RuntimeError):
    """设备长时间无有效操作，判定卡死。"""


class DeviceTooManyClickError(RuntimeError):
    """短时间重复点击同类目标过多。"""


class Device:
    """提供 `Device` 的设备能力适配接口。"""

    def __init__(self, engine: Any):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.rect: tuple[int, int, int, int] | None = None
        self.image: np.ndarray | None = None
        self.preview_image: PILImage.Image | None = None
        self.detect_record: set[str] = set()
        self.click_record = deque(maxlen=15)
        self.stuck_long_wait_list = {'login_check', 'pause'}
        self._stuck_started_at = time.perf_counter()

    def set_rect(self, rect: tuple[int, int, int, int]):
        """设置 `rect` 参数。"""
        self.rect = rect

    def screenshot(
        self, rect: tuple[int, int, int, int] | None = None, *, prefix: str = 'farm', save: bool = False
    ) -> np.ndarray | None:
        """执行一次截图并更新 `image/preview_image`。"""
        self.stuck_record_check()
        if rect is not None:
            self.rect = rect
        if self.rect is None:
            self.image = None
            self.preview_image = None
            return None

        if save:
            image, _ = self.engine.screen_capture.capture_and_save(self.rect, prefix)
        else:
            image = self.engine.screen_capture.capture_region(self.rect)
        if image is None:
            self.image = None
            self.preview_image = None
            return None

        preview_image = self._crop_preview_image(image)
        if preview_image is None:
            self.image = None
            self.preview_image = None
            return None

        self.engine.screenshot_updated.emit(preview_image)
        cv_image = self.engine.cv_detector.pil_to_cv2(preview_image)
        self.preview_image = preview_image
        self.image = cv_image
        return cv_image

    def _crop_preview_image(self, image: PILImage.Image | None) -> PILImage.Image | None:
        """按窗口 nonclient 配置裁剪预览图。"""
        if image is None:
            return None
        platform = getattr(self.engine.config.planting, 'window_platform', 'qq')
        platform_value = platform.value if hasattr(platform, 'value') else str(platform)
        return self.engine.window_manager.crop_window_image_for_preview(image, platform_value)

    def set_image(self, image: np.ndarray | None):
        """设置 `image` 参数。"""
        self.image = image

    def click_button(self, button: Button, click_offset=0):
        """点击按钮对象（逻辑坐标）。"""
        x, y = button.location
        if isinstance(click_offset, (int, float)):
            x += int(click_offset)
            y += int(click_offset)
        elif isinstance(click_offset, (tuple, list)) and len(click_offset) == 2:
            x += int(click_offset[0])
            y += int(click_offset[1])
        return self.click_point(x, y, desc=button.name)

    def click_point(self, x: int, y: int, desc: str = 'point_click', action_type: str = ActionType.NAVIGATE):
        """点击逻辑坐标点（会映射到当前截图坐标系）。"""
        if not self.engine.action_executor:
            return False
        if self.engine._is_cancel_requested():
            return False
        self._handle_control_check(desc)

        rel_x, rel_y = self.engine.resolve_live_click_point(int(x), int(y))
        action = Action(
            type=str(action_type),
            click_position={'x': int(rel_x), 'y': int(rel_y)},
            priority=0,
            description=str(desc or 'device_click'),
        )
        result = self.engine.action_executor.execute_action(action)
        return bool(result.success)

    def _relative_to_absolute(self, x: int, y: int) -> tuple[int, int] | None:
        """将逻辑坐标转换为屏幕绝对坐标。"""
        if not self.engine.action_executor:
            return None
        rel_x, rel_y = self.engine.resolve_live_click_point(int(x), int(y))
        return self.engine.action_executor.relative_to_absolute(int(rel_x), int(rel_y))

    def drag_down_point(self, x: int, y: int, duration: float = 0.05) -> bool:
        """移动到目标点后按下鼠标，用于拖拽起手。"""
        if self.engine._is_cancel_requested():
            return False
        pos = self._relative_to_absolute(int(x), int(y))
        if pos is None:
            return False
        abs_x, abs_y = pos
        if not self.engine.action_executor.move_abs(abs_x, abs_y, duration=duration):
            return False
        return self.engine.action_executor.mouse_down()

    def drag_move_point(self, x: int, y: int, duration: float = 0.1) -> bool:
        """拖拽中移动到目标点。"""
        if self.engine._is_cancel_requested():
            return False
        pos = self._relative_to_absolute(int(x), int(y))
        if pos is None:
            return False
        abs_x, abs_y = pos
        return self.engine.action_executor.move_abs(abs_x, abs_y, duration=duration)

    def drag_up(self) -> bool:
        """结束拖拽，释放鼠标。"""
        if not self.engine.action_executor:
            return False
        return self.engine.action_executor.mouse_up()

    def long_click_point(self, x: int, y: int, seconds: float):
        """长按逻辑坐标点。"""
        ok = self.click_point(int(x), int(y), desc=f'long_click({seconds:.1f}s)')
        if ok:
            self.sleep(seconds)
        return ok

    def sleep(self, seconds: float):
        """执行 `sleep` 相关处理。"""
        return self.engine._sleep_interruptible(float(seconds))

    def _handle_control_check(self, marker: str | None):
        """点击命中时重置卡死计时，并检查点击风暴。"""
        self.stuck_record_clear()
        self.click_record_add(marker)
        self.click_record_check()

    def click_record_check(self):
        """检查点击历史，避免循环疯狂点击。"""
        if not self.click_record:
            return False
        count: dict[str, int] = {}
        for key in self.click_record:
            count[key] = count.get(key, 0) + 1
        sorted_counts = sorted(count.items(), key=lambda item: item[1], reverse=True)
        if sorted_counts[0][1] >= 12:
            logger.warning(f'Too many click for one target: {sorted_counts[0][0]}')
            logger.warning(f'History click: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise DeviceTooManyClickError(f'too many click for `{sorted_counts[0][0]}`')
        if len(sorted_counts) >= 2 and sorted_counts[0][1] >= 6 and sorted_counts[1][1] >= 6:
            logger.warning(f'Too many click between two targets: {sorted_counts[0][0]}, {sorted_counts[1][0]}')
            logger.warning(f'History click: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise DeviceTooManyClickError(f'too many click between `{sorted_counts[0][0]}` and `{sorted_counts[1][0]}`')
        return False

    def click_record_add(self, marker: str | None):
        """记录一次点击目标。"""
        text = str(marker or '').strip() or 'point_click'
        self.click_record.append(text)

    def stuck_record_check(self):
        """检查是否长时间无有效点击。"""
        if self.engine._is_cancel_requested():
            return False
        elapsed = time.perf_counter() - self._stuck_started_at
        if elapsed < 360.0:
            return False
        if elapsed < 480.0:
            for button in self.stuck_long_wait_list:
                if button in self.detect_record:
                    return False
        logger.warning('Wait too long')
        logger.warning(f'Waiting for {sorted(self.detect_record)}')
        self.stuck_record_clear()
        if self.app_is_running():
            raise DeviceStuckError('wait too long')
        raise DeviceStuckError('app is not running')

    def stuck_record_add(self, button):
        """记录一次“尝试识别但未点击”的按钮。"""
        if button is None:
            return None
        self.detect_record.add(str(button))
        return None

    def stuck_record_clear(self):
        """清空待识别记录并重置卡死计时。"""
        self.detect_record = set()
        self._stuck_started_at = time.perf_counter()

    def click_record_clear(self):
        """清空点击历史。"""
        self.click_record.clear()

    def app_is_running(self) -> bool:
        """执行 `app is running` 相关处理。"""
        return not self.engine._is_cancel_requested()

    def get_orientation(self):
        """获取 `orientation` 信息。"""
        return 0
