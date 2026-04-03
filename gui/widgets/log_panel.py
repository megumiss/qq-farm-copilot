"""日志面板 - 深色终端风格"""

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QTextEdit


class LogPanel(QTextEdit):
    MAX_LINES = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet("""
            QTextEdit {
                background-color: #f8fafc; color: #1e293b;
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 12px; border: none; padding: 8px;
            }
        """)

    def append_log(self, message: str):
        if 'ERROR' in message or '\u2717' in message:
            color = '#dc2626'
        elif 'WARNING' in message:
            color = '#d97706'
        elif '\u2713' in message:
            color = '#16a34a'
        elif 'INFO' in message:
            color = '#2563eb'
        else:
            color = '#64748b'

        self.append(f'<span style="color:{color}">{message}</span>')

        if self.document().blockCount() > self.MAX_LINES:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.KeepAnchor, 50)
            cursor.removeSelectedText()

        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
