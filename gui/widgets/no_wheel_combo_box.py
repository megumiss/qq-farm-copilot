"""禁用滚轮切换的下拉框。"""

from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QComboBox


class NoWheelComboBox(QComboBox):
    """阻止鼠标滚轮直接修改当前选项。"""

    def wheelEvent(self, event: QWheelEvent):
        event.ignore()
