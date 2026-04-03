"""NIKKE 风格计时器。"""

from __future__ import annotations

import time


class Timer:
    def __init__(self, limit: float, count: int = 1):
        self.limit = max(0.0, float(limit))
        self.count = max(1, int(count))
        self._start_at = 0.0
        self._hits = 0

    def start(self) -> 'Timer':
        self._start_at = time.perf_counter()
        self._hits = 0
        return self

    def started(self) -> bool:
        return self._start_at > 0.0

    def clear(self):
        self._start_at = 0.0
        self._hits = 0

    def reset(self):
        self._start_at = time.perf_counter()
        self._hits = 0

    def reached(self) -> bool:
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
