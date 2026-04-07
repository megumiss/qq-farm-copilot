"""操作执行器 - 支持后台消息点击与前台回退。"""

import ctypes
import random
import time
from ctypes import wintypes

import pyautogui
from loguru import logger

from models.config import RunMode
from models.farm_state import Action, OperationResult
from utils.run_mode_decorator import Config as DecoratorConfig, UNSET

# Windows 消息常量
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

user32 = ctypes.windll.user32

# 禁用 pyautogui 的安全暂停（我们自己控制延迟）
pyautogui.PAUSE = 0.1
pyautogui.FAILSAFE = True


class ActionExecutor:
    """负责点击/拖拽执行，优先后台消息，失败回退前台。"""

    def __init__(
        self,
        window_rect: tuple[int, int, int, int],
        *,
        hwnd: int | None = None,
        run_mode: RunMode = RunMode.BACKGROUND,
        delay_min: float = 0.5,
        delay_max: float = 2.0,
        click_offset: int = 5,
    ):
        """初始化对象并准备运行所需状态。"""
        self._window_left = window_rect[0]
        self._window_top = window_rect[1]
        self._window_width = window_rect[2]
        self._window_height = window_rect[3]
        self._hwnd = hwnd
        self._run_mode = run_mode
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._click_offset = click_offset

        # 后台拖拽状态（用于 drag_down/move/up 三段式）
        self._bg_dragging = False
        self._bg_last_client_pos: tuple[int, int] | None = None

    def update_window_rect(self, rect: tuple[int, int, int, int]):
        """更新 `window_rect` 状态。"""
        self._window_left, self._window_top = rect[0], rect[1]
        self._window_width, self._window_height = rect[2], rect[3]

    def update_window_handle(self, hwnd: int | None):
        """更新窗口句柄。"""
        self._hwnd = hwnd

    def update_run_mode(self, run_mode: RunMode):
        """更新运行模式。"""
        self._run_mode = run_mode

    def get_run_mode(self) -> RunMode:
        """获取当前运行模式。"""
        return self._run_mode

    def resolve_dispatch_option(self, key: str):
        """为分发装饰器提供选项解析。"""
        if key == 'RUN_MODE':
            return self._run_mode
        return UNSET

    def is_background_enabled(self) -> bool:
        """当前是否启用后台输入模式。"""
        return bool(self._run_mode == RunMode.BACKGROUND and self._hwnd)

    def relative_to_absolute(self, rel_x: int, rel_y: int) -> tuple[int, int]:
        """将相对于窗口的坐标转为屏幕绝对坐标。"""
        abs_x = self._window_left + rel_x
        abs_y = self._window_top + rel_y
        return abs_x, abs_y

    def _random_offset(self) -> tuple[int, int]:
        """生成随机偏移。"""
        ox = random.randint(-self._click_offset, self._click_offset)
        oy = random.randint(-self._click_offset, self._click_offset)
        return ox, oy

    def _random_delay(self):
        """操作间延迟。"""
        dmin = min(float(self._delay_min), float(self._delay_max))
        dmax = max(float(self._delay_min), float(self._delay_max))
        time.sleep(random.uniform(dmin, dmax))

    @staticmethod
    def _format_action_name(desc: str) -> str:
        """格式化日志中的动作名称。"""
        text = str(desc or '').strip()
        if not text:
            return 'CLICK'
        return text.upper()

    @staticmethod
    def _make_lparam(x: int, y: int) -> int:
        """构造鼠标消息的 lparam。"""
        return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)

    def _screen_to_client(self, abs_x: int, abs_y: int) -> tuple[int, int] | None:
        """屏幕坐标转换为目标窗口客户区坐标。"""
        if not self._hwnd:
            return None
        point = wintypes.POINT(int(abs_x), int(abs_y))
        ok = user32.ScreenToClient(wintypes.HWND(self._hwnd), ctypes.byref(point))
        if not ok:
            return None
        return int(point.x), int(point.y)

    def _in_window(self, abs_x: int, abs_y: int) -> bool:
        """判断绝对坐标是否在当前窗口矩形范围内。"""
        return (
            self._window_left <= abs_x <= self._window_left + self._window_width
            and self._window_top <= abs_y <= self._window_top + self._window_height
        )

    def _click_background(self, abs_x: int, abs_y: int) -> bool:
        """后台消息点击。"""
        if not self._hwnd:
            return False
        client = self._screen_to_client(abs_x, abs_y)
        if not client:
            return False
        cx, cy = client
        lparam = self._make_lparam(cx, cy)
        hwnd = wintypes.HWND(self._hwnd)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(0.03)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
        self._bg_last_client_pos = (cx, cy)
        return True

    @staticmethod
    def _click_foreground(abs_x: int, abs_y: int) -> bool:
        """前台鼠标点击。"""
        pyautogui.moveTo(int(abs_x), int(abs_y), duration=0.02)
        time.sleep(0.05)
        pyautogui.click(int(abs_x), int(abs_y))
        return True

    @DecoratorConfig.when(RUN_MODE=RunMode.BACKGROUND)
    def _click_by_mode(self, target_x: int, target_y: int) -> bool:
        return self._click_background(int(target_x), int(target_y))

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _click_by_mode(self, target_x: int, target_y: int) -> bool:
        return self._click_foreground(int(target_x), int(target_y))

    def click_absolute(
        self,
        x: int,
        y: int,
        *,
        desc: str = 'click',
        rel_x: int | None = None,
        rel_y: int | None = None,
    ) -> bool:
        """点击屏幕绝对坐标。"""
        try:
            ox, oy = self._random_offset()
            target_x = int(x) + ox
            target_y = int(y) + oy

            if not self._in_window(target_x, target_y):
                logger.warning(f'点击越界: ({target_x}, {target_y})')
                return False

            ok = bool(self._click_by_mode(target_x, target_y))

            if rel_x is None or rel_y is None:
                log_x, log_y = target_x, target_y
            else:
                log_x, log_y = int(rel_x) + ox, int(rel_y) + oy
            name = self._format_action_name(desc)
            if ok:
                logger.info(f'点击: {name} | 坐标: ({log_x}, {log_y})')
                return True
            logger.error(f'点击失败: {name} | 坐标: ({log_x}, {log_y})')
            return False
        except Exception as e:
            if rel_x is None or rel_y is None:
                err_x, err_y = int(x), int(y)
            else:
                err_x, err_y = int(rel_x), int(rel_y)
            name = self._format_action_name(desc)
            logger.error(f'点击失败: {name} | 坐标: ({err_x}, {err_y}) | 错误: {e}')
            return False

    def move_abs(self, x: int, y: int, duration: float = 0.0) -> bool:
        """移动鼠标到绝对坐标。"""
        try:
            return bool(self._move_by_mode(int(x), int(y), float(duration)))
        except Exception as e:
            logger.error(f'移动失败: {e}')
            return False

    @DecoratorConfig.when(RUN_MODE=RunMode.BACKGROUND)
    def _move_by_mode(self, abs_x: int, abs_y: int, duration: float = 0.0) -> bool:
        if not self._hwnd:
            return False
        client = self._screen_to_client(abs_x, abs_y)
        if not client:
            return False
        cx, cy = client
        lparam = self._make_lparam(cx, cy)
        wparam = MK_LBUTTON if self._bg_dragging else 0
        user32.PostMessageW(wintypes.HWND(self._hwnd), WM_MOUSEMOVE, wparam, lparam)
        self._bg_last_client_pos = (cx, cy)
        if duration > 0:
            time.sleep(float(duration))
        return True

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _move_by_mode(self, abs_x: int, abs_y: int, duration: float = 0.0) -> bool:
        pyautogui.moveTo(abs_x, abs_y, duration=max(0.0, float(duration)))
        return True

    def mouse_down(self) -> bool:
        """按下鼠标左键。"""
        try:
            return bool(self._mouse_down_by_mode())
        except Exception as e:
            logger.error(f'按下鼠标失败: {e}')
            return False

    @DecoratorConfig.when(RUN_MODE=RunMode.BACKGROUND)
    def _mouse_down_by_mode(self) -> bool:
        if not self._hwnd or self._bg_last_client_pos is None:
            return False
        cx, cy = self._bg_last_client_pos
        lparam = self._make_lparam(cx, cy)
        user32.PostMessageW(wintypes.HWND(self._hwnd), WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        self._bg_dragging = True
        return True

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _mouse_down_by_mode(self) -> bool:
        pyautogui.mouseDown()
        return True

    def mouse_up(self) -> bool:
        """释放鼠标左键。"""
        try:
            return bool(self._mouse_up_by_mode())
        except Exception as e:
            logger.error(f'释放鼠标失败: {e}')
            return False

    @DecoratorConfig.when(RUN_MODE=RunMode.BACKGROUND)
    def _mouse_up_by_mode(self) -> bool:
        if not self._hwnd or self._bg_last_client_pos is None:
            return False
        cx, cy = self._bg_last_client_pos
        lparam = self._make_lparam(cx, cy)
        user32.PostMessageW(wintypes.HWND(self._hwnd), WM_LBUTTONUP, 0, lparam)
        self._bg_dragging = False
        return True

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _mouse_up_by_mode(self) -> bool:
        pyautogui.mouseUp()
        return True

    def execute_action(self, action: Action) -> OperationResult:
        """执行单个操作"""
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

        desc = str(action.description or 'click')
        success = self.click_absolute(abs_x, abs_y, desc=desc, rel_x=int(pos['x']), rel_y=int(pos['y']))
        self._random_delay()

        return OperationResult(
            action=action, success=success, message=action.description if success else '点击失败', timestamp=time.time()
        )

    def execute_actions(self, actions: list[Action], max_count: int = 20) -> list[OperationResult]:
        """按优先级执行操作序列"""
        results = []
        executed = 0

        for action in actions:
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

    def swipe_absolute(
        self,
        p1: tuple[int, int],
        p2: tuple[int, int],
        *,
        speed: float = 15.0,
        inertia: bool = False,
        rel_p1: tuple[int, int] | None = None,
        rel_p2: tuple[int, int] | None = None,
    ) -> bool:
        """执行鼠标滑动（兼容前台/后台模式）。"""
        try:
            x1, y1 = int(p1[0]), int(p1[1])
            x2, y2 = int(p2[0]), int(p2[1])
        except Exception:
            logger.error('滑动失败: 坐标格式非法')
            return False

        if not self._in_window(x1, y1) or not self._in_window(x2, y2):
            logger.warning(f'滑动越界: ({x1}, {y1}) -> ({x2}, {y2})')
            return False

        distance = max(abs(x2 - x1), abs(y2 - y1))
        if distance <= 0:
            return True

        speed_value = max(1.0, float(speed))
        if inertia:
            total_duration = max(0.05, min(0.45, distance / (speed_value * 220.0)))
            steps = max(4, min(18, distance // 20))
        else:
            # 无惯性模式：增加轨迹采样并降低末段速度，减少抬手瞬间速度。
            total_duration = max(0.15, min(0.95, distance / (speed_value * 140.0)))
            steps = max(8, min(36, distance // 12))

        if not self.move_abs(x1, y1, duration=0.01):
            return False
        if not self.mouse_down():
            return False

        ok = True
        try:
            # 分段时长：越到后段越慢（ease-out），用于主动去惯性。
            duration_weights: list[float] = []
            for i in range(1, int(steps) + 1):
                t = i / float(steps)
                duration_weights.append(0.7 + 1.6 * t if not inertia else 1.0)
            total_weight = sum(duration_weights) if duration_weights else 1.0

            for i in range(1, int(steps) + 1):
                t = i / float(steps)
                if inertia:
                    ratio = t
                else:
                    ratio = 1.0 - pow(1.0 - t, 2.2)
                tx = int(round(x1 + (x2 - x1) * ratio))
                ty = int(round(y1 + (y2 - y1) * ratio))
                step_duration = total_duration * duration_weights[i - 1] / total_weight
                if not self.move_abs(tx, ty, duration=step_duration):
                    ok = False
                    break
            if ok and not inertia:
                # 末端回拉-回位：主动抵消拖拽末速度（比单纯延时更有效）。
                sign_x = 0 if x2 == x1 else (1 if x2 > x1 else -1)
                sign_y = 0 if y2 == y1 else (1 if y2 > y1 else -1)
                pull = max(2, min(10, int(distance * 0.03)))
                back_x = x2 - sign_x * pull
                back_y = y2 - sign_y * pull
                if self._in_window(back_x, back_y):
                    self.move_abs(back_x, back_y, duration=0.03)
                    self.move_abs(x2, y2, duration=0.04)
                time.sleep(0.03)
        finally:
            self.mouse_up()

        if rel_p1 is None:
            log_p1 = (x1, y1)
        else:
            log_p1 = (int(rel_p1[0]), int(rel_p1[1]))
        if rel_p2 is None:
            log_p2 = (x2, y2)
        else:
            log_p2 = (int(rel_p2[0]), int(rel_p2[1]))

        if ok:
            logger.info(f'滑动: ({log_p1[0]}, {log_p1[1]}) -> ({log_p2[0]}, {log_p2[1]})')
        else:
            logger.error(f'滑动失败: ({log_p1[0]}, {log_p1[1]}) -> ({log_p2[0]}, {log_p2[1]})')
        return ok
