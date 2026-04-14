"""Fluent 日志面板。"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtGui import QTextCursor
from qfluentwidgets import PlainTextEdit


class LogPanel(PlainTextEdit):
    """运行日志窗口。"""

    MAX_LINES = 600

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText('运行后显示日志...')

    def append_log(self, message: str) -> None:
        text = str(message or '').rstrip()
        if not text:
            return
        now = datetime.now().strftime('%H:%M:%S')
        self.appendPlainText(f'[{now}] {text}')

        blocks = self.document().blockCount()
        if blocks <= self.MAX_LINES:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
            return

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for _ in range(blocks - self.MAX_LINES):
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
