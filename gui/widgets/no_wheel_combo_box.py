"""Fluent 下拉框：禁用滚轮误触。"""

from __future__ import annotations

from PyQt6.QtGui import QWheelEvent
from qfluentwidgets import ComboBox


class NoWheelComboBox(ComboBox):
    """阻止滚轮直接切换项，避免悬停误改。"""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()

    def select_data(self, value, default_index: int = 0) -> None:
        """按 data 选中项，不存在时回退默认索引。"""
        idx = self.findData(value)
        if idx < 0:
            idx = max(0, min(default_index, self.count() - 1))
        if idx >= 0:
            self.setCurrentIndex(idx)
