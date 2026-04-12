"""禁用滚轮切换的下拉框。"""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QPainterPath, QRegion, QWheelEvent
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QFrame, QListView


class NoWheelComboBox(QComboBox):
    """阻止鼠标滚轮直接修改当前选项，并统一下拉弹层行为。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(12)

        # 使用自定义列表视图，避免平台原生弹层导致样式/高度不可控。
        view = QListView(self)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setStyleSheet(
            'QListView {'
            'background-color: #ffffff;'
            'color: #0f172a;'
            'border: 1px solid #cbd5e1;'
            'border-radius: 10px;'
            'padding: 4px;'
            'outline: none;'
            '}'
            'QListView::item {'
            'min-height: 24px;'
            'padding: 4px 8px;'
            'border-radius: 6px;'
            '}'
            'QListView::item:hover {'
            'background-color: #eef2ff;'
            '}'
            'QListView::item:selected {'
            'background-color: #dbeafe;'
            'color: #0f172a;'
            '}'
        )
        self.setView(view)

    def wheelEvent(self, event: QWheelEvent):
        event.ignore()

    def showPopup(self):
        """展开下拉时锚定到控件下方，空间不足再回退到上方。"""
        if self.count() > self.maxVisibleItems():
            self.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        else:
            self.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        super().showPopup()
        popup = self.view().window()
        if popup is None:
            return

        popup_width = max(int(self.width()), int(popup.width()))
        popup_height = int(popup.height())
        anchor = self.mapToGlobal(self.rect().bottomLeft())
        x = int(anchor.x())
        y = int(anchor.y()) + 1

        screen = QGuiApplication.screenAt(anchor) or self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = max(int(available.left()), min(x, int(available.right()) + 1 - popup_width))

            if y + popup_height > int(available.bottom()) + 1:
                y_top = int(self.mapToGlobal(self.rect().topLeft()).y()) - popup_height - 1
                y = y_top if y_top >= int(available.top()) else max(int(available.top()), y)

        popup.resize(popup_width, popup_height)
        popup.move(x, y)
        # 强制弹层按圆角裁剪，避免圆角外残留方形背景。
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(popup.rect().adjusted(0, 0, -1, -1)), 10.0, 10.0)
        popup.setMask(QRegion(clip.toFillPolygon().toPolygon()))
