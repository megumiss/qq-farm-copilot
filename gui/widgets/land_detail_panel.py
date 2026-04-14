"""农场详情占位面板。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel


class LandDetailPanel(QWidget):
    """农场详情页（占位）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = BodyLabel('农场详情功能开发中')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint, 1)
