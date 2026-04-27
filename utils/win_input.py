"""Windows 键盘输入工具。"""

from __future__ import annotations

import ctypes
import time

VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002


def press_escape(*, hold_seconds: float = 0.02) -> bool:
    """发送一次 ESC 按键。"""
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(int(VK_ESCAPE), 0, 0, 0)
        if float(hold_seconds) > 0:
            time.sleep(float(hold_seconds))
        user32.keybd_event(int(VK_ESCAPE), 0, int(KEYEVENTF_KEYUP), 0)
        return True
    except Exception:
        return False
