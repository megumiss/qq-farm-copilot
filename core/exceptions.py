"""项目通用异常定义。"""

from __future__ import annotations


class GamePageUnknownError(RuntimeError):
    """页面识别超时，无法确认当前处于可支持页面。"""


class LoginRepeatError(RuntimeError):
    """QQ重复登录。"""


class LoginRecoveryRequiredError(RuntimeError):
    """检测到重新登录弹窗，需要执行登录恢复流程。"""


class WindowCaptureError(RuntimeError):
    """窗口截图链路持续失败（如 PrintWindow/GetDIBits/GetWindowRect）。"""


class BuySeedError(RuntimeError):
    """购买种子失败"""
