"""NIKKE 风格计时器。"""

from __future__ import annotations

import time


class Timer:
    """封装 `Timer` 相关的数据与行为。"""

    def __init__(self, limit: float, count: int = 1):
        """初始化对象并准备运行所需状态。"""
        self.limit = max(0.0, float(limit))
        self.count = max(1, int(count))
        self._start_at = 0.0
        self._hits = 0

    def start(self) -> 'Timer':
        """启动当前模块的主流程。"""
        self._start_at = time.perf_counter()
        self._hits = 0
        return self

    def started(self) -> bool:
        """判断计时器是否已经启动。"""
        return self._start_at > 0.0

    def clear(self):
        """清空当前状态并停止计时。"""
        self._start_at = 0.0
        self._hits = 0

    def reset(self):
        """重置计时起点。"""
        self._start_at = time.perf_counter()
        self._hits = 0

    def reached(self) -> bool:
        """判断是否达到设定时限。"""
        if not self.started():
            self.start()
            return False
        if (time.perf_counter() - self._start_at) < self.limit:
            return False
        self._hits += 1
        if self._hits >= self.count:
            return True
        self._start_at = time.perf_counter()
        return False
