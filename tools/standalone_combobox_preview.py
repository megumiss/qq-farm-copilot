"""Standalone ComboBox preview window.

This script is fully independent from project code and only depends on:
- PyQt6
- PyQt6-Fluent-Widgets
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ComboBox


class PreviewWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Standalone ComboBox Preview')
        self.resize(560, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        title = BodyLabel('qfluentwidgets.ComboBox Preview', self)
        root.addWidget(title)

        tip = BodyLabel('仅用于观察下拉弹层效果，不依赖项目业务代码。', self)
        root.addWidget(tip)

        root.addWidget(self._build_row('qfluentwidgets.ComboBox', self._create_fluent_combo()))
        root.addStretch()

    def _build_row(self, label_text: str, combo_widget: QWidget) -> QWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        label = BodyLabel(label_text, card)
        layout.addWidget(label)
        layout.addWidget(combo_widget)
        return card

    @staticmethod
    def _create_fluent_combo() -> ComboBox:
        box = ComboBox()
        box.setMinimumWidth(240)
        box.addItem('秒', userData=1)
        box.addItem('分钟', userData=60)
        box.addItem('小时', userData=3600)
        return box


def main() -> int:
    app = QApplication(sys.argv)
    w = PreviewWindow()
    w.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
