"""操作执行器 - 支持后台消息点击与前台回退。"""

import ctypes
import math
import random
import time
from ctypes import wintypes

from loguru import logger

from models.config import RunMode
from models.farm_state import Action, OperationResult
from utils.run_mode_decorator import UNSET
from utils.run_mode_decorator import Config as DecoratorConfig

# Windows 消息常量
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

user32 = ctypes.windll.user32


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
        user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(0.03)
        user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
        self._bg_last_client_pos = (cx, cy)
        return True

    @staticmethod
    def _set_cursor_pos(abs_x: int, abs_y: int) -> bool:
        """将系统鼠标移动到绝对坐标。"""
        return bool(user32.SetCursorPos(int(abs_x), int(abs_y)))

    @staticmethod
    def _get_cursor_pos() -> tuple[int, int]:
        """读取当前鼠标绝对坐标。"""
        point = wintypes.POINT()
        ok = bool(user32.GetCursorPos(ctypes.byref(point)))
        if not ok:
            return 0, 0
        return int(point.x), int(point.y)

    @classmethod
    def _move_cursor_foreground(cls, abs_x: int, abs_y: int, duration: float = 0.0) -> bool:
        """前台模式移动鼠标，支持负坐标多屏。"""
        target_x = int(abs_x)
        target_y = int(abs_y)
        total_duration = max(0.0, float(duration))
        if total_duration <= 0:
            return cls._set_cursor_pos(target_x, target_y)

        start_x, start_y = cls._get_cursor_pos()
        steps = max(1, min(120, int(round(total_duration * 120.0))))
        step_sleep = total_duration / float(steps)
        for step in range(1, steps + 1):
            ratio = float(step) / float(steps)
            move_x = int(round(start_x + (target_x - start_x) * ratio))
            move_y = int(round(start_y + (target_y - start_y) * ratio))
            if not cls._set_cursor_pos(move_x, move_y):
                return False
            if step < steps and step_sleep > 0:
                time.sleep(step_sleep)
        return True

    @staticmethod
    def _mouse_left_down_foreground() -> bool:
        """前台模式按下鼠标左键。"""
        user32.mouse_event(int(MOUSEEVENTF_LEFTDOWN), 0, 0, 0, 0)
        return True

    @staticmethod
    def _mouse_left_up_foreground() -> bool:
        """前台模式释放鼠标左键。"""
        user32.mouse_event(int(MOUSEEVENTF_LEFTUP), 0, 0, 0, 0)
        return True

    @classmethod
    def _click_foreground(cls, abs_x: int, abs_y: int) -> bool:
        """前台鼠标点击。"""
        if not cls._move_cursor_foreground(int(abs_x), int(abs_y), duration=0.02):
            return False
        time.sleep(0.03)
        cls._mouse_left_down_foreground()
        time.sleep(0.03)
        cls._mouse_left_up_foreground()
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
        user32.SendMessageW(wintypes.HWND(self._hwnd), WM_MOUSEMOVE, wparam, lparam)
        self._bg_last_client_pos = (cx, cy)
        if duration > 0:
            time.sleep(float(duration))
        return True

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _move_by_mode(self, abs_x: int, abs_y: int, duration: float = 0.0) -> bool:
        return self._move_cursor_foreground(int(abs_x), int(abs_y), duration=max(0.0, float(duration)))

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
        user32.SendMessageW(wintypes.HWND(self._hwnd), WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        self._bg_dragging = True
        return True

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _mouse_down_by_mode(self) -> bool:
        return self._mouse_left_down_foreground()

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
        user32.SendMessageW(wintypes.HWND(self._hwnd), WM_LBUTTONUP, 0, lparam)
        self._bg_dragging = False
        return True

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _mouse_up_by_mode(self) -> bool:
        return self._mouse_left_up_foreground()

    def execute_action(self, action: Action) -> OperationResult:
        """执行单个操作"""
        pos = action.click_position
        if not pos or 'x' not in pos or 'y' not in pos:
            return OperationResult(action=action, success=False, message='缺少点击坐标', timestamp=time.time())

        exec_pos = action.extra.get('live_click_position', {}) if isinstance(action.extra, dict) else {}
        if exec_pos and 'x' in exec_pos and 'y' in exec_pos:
            target_rel_x = int(exec_pos['x'])
            target_rel_y = int(exec_pos['y'])
        else:
            target_rel_x = int(pos['x'])
            target_rel_y = int(pos['y'])

        # 转换坐标
        abs_x, abs_y = self.relative_to_absolute(target_rel_x, target_rel_y)
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

    @DecoratorConfig.when(RUN_MODE=RunMode.BACKGROUND)
    def swipe_absolute(
        self,
        p1: tuple[int, int],
        p2: tuple[int, int],
        *,
        speed: float = 15.0,
        hold: float = 0.0,
        rel_p1: tuple[int, int] | None = None,
        rel_p2: tuple[int, int] | None = None,
    ) -> bool:
        """执行鼠标滑动（后台模式）。"""
        try:
            x1, y1 = int(p1[0]), int(p1[1])
            x2, y2 = int(p2[0]), int(p2[1])
        except Exception:
            logger.error('滑动失败: 坐标格式非法')
            return False

        if not self._in_window(x1, y1) or not self._in_window(x2, y2):
            logger.warning(f'滑动越界: ({x1}, {y1}) -> ({x2}, {y2})')
            return False

        distance = math.hypot(x2 - x1, y2 - y1)
        if distance <= 0:
            return True

        speed = max(0.1, float(speed))
        hold = max(0.0, float(hold))
        ok = self._swipe_decel_profile(
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            distance=distance,
            speed=speed,
            hold=hold,
            rel_p1=rel_p1,
            rel_p2=rel_p2,
        )

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

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def swipe_absolute(
        self,
        p1: tuple[int, int],
        p2: tuple[int, int],
        *,
        speed: float = 15.0,
        hold: float = 0.0,
        rel_p1: tuple[int, int] | None = None,
        rel_p2: tuple[int, int] | None = None,
    ) -> bool:
        """执行鼠标滑动（前台模式）。"""
        try:
            x1, y1 = int(p1[0]), int(p1[1])
            x2, y2 = int(p2[0]), int(p2[1])
        except Exception:
            logger.error('滑动失败: 坐标格式非法')
            return False

        if not self._in_window(x1, y1) or not self._in_window(x2, y2):
            logger.warning(f'滑动越界: ({x1}, {y1}) -> ({x2}, {y2})')
            return False

        distance = math.hypot(x2 - x1, y2 - y1)
        if distance <= 0:
            return True

        speed_value = max(0.1, float(speed)) * 1.8
        hold_value = max(0.0, float(hold))
        duration_scale = 33.0
        duration = distance / speed_value / 1000.0 * duration_scale
        duration = max(0.05, min(0.35, float(duration)))

        if rel_p1 is None:
            log_p1 = (x1, y1)
        else:
            log_p1 = (int(rel_p1[0]), int(rel_p1[1]))
        if rel_p2 is None:
            log_p2 = (x2, y2)
        else:
            log_p2 = (int(rel_p2[0]), int(rel_p2[1]))

        pressed = False
        try:
            if not self._move_cursor_foreground(x1, y1, duration=0.0):
                return False
            self._mouse_left_down_foreground()
            pressed = True
            if not self._move_cursor_foreground(x2, y2, duration=duration):
                return False
            if hold_value > 0:
                time.sleep(hold_value)
            self._mouse_left_up_foreground()
            pressed = False
            logger.info(f'滑动: ({log_p1[0]}, {log_p1[1]}) -> ({log_p2[0]}, {log_p2[1]})')
            return True
        except Exception as e:
            logger.error(f'滑动失败: ({log_p1[0]}, {log_p1[1]}) -> ({log_p2[0]}, {log_p2[1]}) | 错误: {e}')
            return False
        finally:
            if pressed:
                try:
                    self._mouse_left_up_foreground()
                except Exception:
                    pass

    def _swipe_decel_profile(
        self,
        *,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        distance: float,
        speed: float,
        hold: float,
        rel_p1: tuple[int, int] | None = None,
        rel_p2: tuple[int, int] | None = None,
    ) -> bool:
        """执行统一减速滑动轨迹（前后台共用）。"""
        duration_scale = 33.0
        total_duration = distance / speed / 1000.0 * duration_scale
        max_duration = 0.56
        min_duration = 0.08
        if total_duration > max_duration:
            total_duration = max_duration
        if total_duration < min_duration:
            total_duration = min_duration

        tail_ratio = 0.35
        total_steps = max(14, min(60, int(distance / 12)))
        tail_steps = max(8, int(total_steps * tail_ratio))
        head_steps = max(8, total_steps - tail_steps)
        tail_weight = 2.0
        weighted_steps = float(head_steps) + float(tail_steps) * tail_weight
        head_step_duration = total_duration / weighted_steps
        tail_step_duration = head_step_duration * tail_weight

        if not self.move_abs(x1, y1, duration=0.0):
            return False
        time.sleep(0.03)
        if not self.mouse_down():
            return False

        ok = True
        try:
            head_ratio = 1.0 - tail_ratio
            for i in range(1, head_steps + 1):
                ratio = head_ratio * (i / float(head_steps))
                tx = int(round(x1 + (x2 - x1) * ratio))
                ty = int(round(y1 + (y2 - y1) * ratio))
                if not self.move_abs(tx, ty, duration=head_step_duration):
                    ok = False
                    break

            if ok:
                for i in range(1, tail_steps + 1):
                    ratio = head_ratio + tail_ratio * (i / float(tail_steps))
                    tx = int(round(x1 + (x2 - x1) * ratio))
                    ty = int(round(y1 + (y2 - y1) * ratio))
                    if not self.move_abs(tx, ty, duration=tail_step_duration):
                        ok = False
                        break

            if ok and distance >= 120:
                sign_x = 0 if x2 == x1 else (1 if x2 > x1 else -1)
                sign_y = 0 if y2 == y1 else (1 if y2 > y1 else -1)
                brake_px = max(1, min(3, int(distance * 0.0045)))
                back_x = x2 - sign_x * brake_px
                back_y = y2 - sign_y * brake_px
                if self._in_window(back_x, back_y):
                    self.move_abs(back_x, back_y, duration=0.012)
                    self.move_abs(x2, y2, duration=0.016)

            if ok:
                if hold > 0:
                    stop_frames = max(1, min(80, int(hold / 0.016)))
                    stop_dt = hold / float(stop_frames)
                else:
                    stop_frames = 6
                    stop_dt = 0.012
                axis_x = abs(x2 - x1) >= abs(y2 - y1)
                settle_sign_x = 0 if x2 == x1 else (1 if x2 > x1 else -1)
                settle_sign_y = 0 if y2 == y1 else (1 if y2 > y1 else -1)
                settle_amp = 2 if distance >= 420 else 1
                for _ in range(stop_frames):
                    if axis_x:
                        settle_x = x2 - settle_sign_x * settle_amp
                        settle_y = y2
                    else:
                        settle_x = x2
                        settle_y = y2 - settle_sign_y * settle_amp
                    if not self.move_abs(settle_x, settle_y, duration=stop_dt * 0.5):
                        ok = False
                        break
                    if not self.move_abs(x2, y2, duration=stop_dt * 0.5):
                        ok = False
                        break
        finally:
            self.mouse_up()

        return ok
