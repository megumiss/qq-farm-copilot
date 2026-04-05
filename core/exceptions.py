"""项目通用异常定义。"""

from __future__ import annotations


class GamePageUnknownError(RuntimeError):
    """页面识别超时，无法确认当前处于可支持页面。"""


class LoginRepeatError(RuntimeError):
    """QQ重复登录。"""


class TaskRetryCurrentError(RuntimeError):
    """微信重新登录"""
