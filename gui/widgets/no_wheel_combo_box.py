"""Fluent 下拉框：禁用滚轮误触，移除弹层外侧透明留白。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QWheelEvent
from qfluentwidgets.components.widgets.combo_box import ComboBox, ComboBoxMenu


class _FlatComboBoxMenu(ComboBoxMenu):
    """紧凑弹层：去除外边距与阴影，避免外侧透明框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.view.setViewportMargins(0, 0, 0, 0)
        self.view.setGraphicsEffect(None)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)


class NoWheelComboBox(ComboBox):
    """阻止滚轮直接切换项，并使用紧凑弹层样式。"""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()

    def _createComboMenu(self):
        return _FlatComboBoxMenu(self)
