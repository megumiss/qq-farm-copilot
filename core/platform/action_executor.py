"""操作执行器 - 模拟鼠标操作"""

import random
import time

import pyautogui
from loguru import logger

from models.farm_state import Action, OperationResult

# 禁用pyautogui的安全暂停（我们自己控制延迟）
pyautogui.PAUSE = 0.1
pyautogui.FAILSAFE = True  # 鼠标移到左上角可紧急停止


class ActionExecutor:
    """负责 `ActionExecutor` 的任务执行与状态推进。"""

    def __init__(
        self,
        window_rect: tuple[int, int, int, int],
        delay_min: float = 0.5,
        delay_max: float = 2.0,
        click_offset: int = 5,
    ):
        """初始化对象并准备运行所需状态。"""
        self._window_left = window_rect[0]
        self._window_top = window_rect[1]
        self._window_width = window_rect[2]
        self._window_height = window_rect[3]
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._click_offset = click_offset
        self._cancel_checker = None

    def set_cancel_checker(self, fn):
        """设置 `cancel_checker` 参数。"""
        self._cancel_checker = fn

    def _is_cancelled(self) -> bool:
        """判断是否满足 `cancelled` 条件。"""
        return bool(self._cancel_checker and self._cancel_checker())

    def _sleep_interruptible(self, seconds: float, interval: float = 0.01) -> bool:
        """执行 `sleep interruptible` 相关处理。"""
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

    def update_window_rect(self, rect: tuple[int, int, int, int]):
        """更新 `window_rect` 状态。"""
        self._window_left, self._window_top = rect[0], rect[1]
        self._window_width, self._window_height = rect[2], rect[3]

    def relative_to_absolute(self, rel_x: int, rel_y: int) -> tuple[int, int]:
        """将相对于窗口的坐标转为屏幕绝对坐标"""
        abs_x = self._window_left + rel_x
        abs_y = self._window_top + rel_y
        return abs_x, abs_y

    def _random_offset(self) -> tuple[int, int]:
        """生成随机偏移"""
        ox = random.randint(-self._click_offset, self._click_offset)
        oy = random.randint(-self._click_offset, self._click_offset)
        return ox, oy

    def _random_delay(self):
        """操作间延迟"""
        if self._is_cancelled():
            return
        self._sleep_interruptible(0.3)

    def click(self, x: int, y: int) -> bool:
        """点击指定坐标"""
        if self._is_cancelled():
            return False
        try:
            ox, oy = self._random_offset()
            target_x = x + ox
            target_y = y + oy
            pyautogui.moveTo(target_x, target_y, duration=0.02)
            if self._is_cancelled():
                return False
            if not self._sleep_interruptible(0.05):
                return False
            if self._is_cancelled():
                return False
            pyautogui.click(target_x, target_y)
            logger.debug(f'点击 ({target_x}, {target_y})')
            return True
        except Exception as e:
            logger.error(f'点击失败: {e}')
            return False

    def execute_action(self, action: Action) -> OperationResult:
        """执行单个操作"""
        if self._is_cancelled():
            return OperationResult(action=action, success=False, message='执行已取消', timestamp=time.time())
        pos = action.click_position
        if not pos or 'x' not in pos or 'y' not in pos:
            return OperationResult(action=action, success=False, message='缺少点击坐标', timestamp=time.time())

        # 转换坐标
        abs_x, abs_y = self.relative_to_absolute(int(pos['x']), int(pos['y']))

        # 检查坐标是否在窗口范围内
        if not (
            self._window_left <= abs_x <= self._window_left + self._window_width
            and self._window_top <= abs_y <= self._window_top + self._window_height
        ):
            return OperationResult(
                action=action, success=False, message=f'坐标 ({abs_x},{abs_y}) 超出窗口范围', timestamp=time.time()
            )

        success = self.click(abs_x, abs_y)
        self._random_delay()

        return OperationResult(
            action=action, success=success, message=action.description if success else '点击失败', timestamp=time.time()
        )

    def execute_actions(self, actions: list[Action], max_count: int = 20) -> list[OperationResult]:
        """按优先级执行操作序列"""
        results = []
        executed = 0

        for action in actions:
            if self._is_cancelled():
                logger.info('动作序列执行取消')
                break
            if executed >= max_count:
                logger.info(f'已达到单轮最大操作数 {max_count}，停止执行')
                break

            logger.info(f'执行: {action.description} (优先级:{action.priority})')
            result = self.execute_action(action)
            results.append(result)

            if result.success:
                executed += 1
                logger.info(f'✓ {action.description}')
            else:
                logger.warning(f'✗ {action.description}: {result.message}')

        return results
