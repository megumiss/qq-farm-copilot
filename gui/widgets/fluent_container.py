"""Fluent 透明容器组件。"""

from __future__ import annotations

from PyQt6.QtGui import QColor
from qfluentwidgets import CardWidget


class TransparentCardContainer(CardWidget):
    """用于滚动区域内容层的无底色 Fluent 容器。"""

    def _normalBackgroundColor(self):
        return QColor(0, 0, 0, 0)

    def _hoverBackgroundColor(self):
        return QColor(0, 0, 0, 0)

    def _pressedBackgroundColor(self):
        return QColor(0, 0, 0, 0)

    def paintEvent(self, _event):
        # 内容容器仅用于布局，不绘制任何卡片底色或边框。
        return
