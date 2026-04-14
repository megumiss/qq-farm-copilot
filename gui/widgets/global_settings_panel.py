"""Fluent 全局设置面板。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, PrimaryPushButton, SwitchButton

from gui.widgets.no_wheel_combo_box import NoWheelComboBox


class GlobalSettingsPanel(QWidget):
    """应用级设置（主题/窗口效果）。"""

    apply_requested = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        card = CardWidget(self)
        root.addWidget(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)
        card_layout.addWidget(BodyLabel('全局设置'))
        card_layout.addWidget(CaptionLabel('主题、窗口效果等应用级外观'))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        card_layout.addLayout(form)

        self.theme_combo = NoWheelComboBox(card)
        self.theme_combo.addItem('跟随系统', 'auto')
        self.theme_combo.addItem('浅色', 'light')
        self.theme_combo.addItem('深色', 'dark')
        form.addRow('主题:', self.theme_combo)

        self.mica_switch = SwitchButton(card)
        self.mica_switch.setOnText('开')
        self.mica_switch.setOffText('关')
        form.addRow('云母效果:', self.mica_switch)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self.apply_btn = PrimaryPushButton('应用', card)
        self.apply_btn.clicked.connect(self._on_apply)
        action_row.addWidget(self.apply_btn)
        card_layout.addLayout(action_row)
        root.addStretch()

    def _on_apply(self) -> None:
        self.apply_requested.emit(str(self.theme_combo.currentData() or 'auto'), bool(self.mica_switch.isChecked()))

    def set_values(self, theme_mode: str, mica_enabled: bool) -> None:
        self.theme_combo.select_data(str(theme_mode or 'auto'))
        self.mica_switch.setChecked(bool(mica_enabled))
