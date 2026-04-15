"""Fluent 全局设置面板。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    OptionsConfigItem,
    OptionsSettingCard,
    OptionsValidator,
    SettingCardGroup,
    SwitchSettingCard,
)


class _LocalOptionsSettingCard(OptionsSettingCard):
    """仅用于本面板的选项卡：不写 qconfig，全程本地值驱动。"""

    def __init__(self, config_item, icon, title, content=None, texts=None, parent=None):
        self._current_value = config_item.value
        super().__init__(config_item, icon, title, content, texts, parent)
        try:
            self.buttonGroup.buttonClicked.disconnect()
        except Exception:
            pass
        self.buttonGroup.buttonClicked.connect(self._on_button_clicked)
        self.setValue(config_item.value)

    def _on_button_clicked(self, button) -> None:
        value = button.property(self.configName)
        if value == self._current_value:
            return
        self._current_value = value
        self.configItem.value = value
        self.choiceLabel.setText(button.text())
        self.choiceLabel.adjustSize()
        self.optionChanged.emit(self.configItem)

    def setValue(self, value):
        self._current_value = value
        for button in self.buttonGroup.buttons():
            is_checked = button.property(self.configName) == value
            button.setChecked(is_checked)
            if is_checked:
                self.choiceLabel.setText(button.text())
                self.choiceLabel.adjustSize()

    def currentValue(self):
        return self._current_value


class GlobalSettingsPanel(QWidget):
    """应用级设置（主题/窗口效果）。"""

    apply_requested = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = True
        self._build_ui()
        self._loading = False

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self._theme_config = OptionsConfigItem(
            'global_settings',
            'theme_mode',
            'auto',
            OptionsValidator(['auto', 'light', 'dark']),
        )
        self.settings_group = SettingCardGroup('全局设置', self)
        self.theme_card = _LocalOptionsSettingCard(
            self._theme_config,
            FluentIcon.BRUSH,
            '主题',
            '选择应用主题模式',
            texts=['跟随系统', '浅色', '深色'],
            parent=self.settings_group,
        )
        self.mica_card = SwitchSettingCard(
            FluentIcon.TRANSPARENT,
            '云母效果',
            '开启后使用窗口材质效果',
            parent=self.settings_group,
        )
        self.settings_group.addSettingCards([self.theme_card, self.mica_card])
        self.theme_card.optionChanged.connect(lambda *_: self._emit_apply())
        self.mica_card.checkedChanged.connect(lambda *_: self._emit_apply())
        root.addWidget(self.settings_group)
        root.addStretch()

    def _emit_apply(self) -> None:
        if self._loading:
            return
        self.apply_requested.emit(str(self.theme_card.currentValue() or 'auto'), bool(self.mica_card.isChecked()))

    def set_values(self, theme_mode: str, mica_enabled: bool) -> None:
        self._loading = True
        value = str(theme_mode or 'auto')
        if value not in {'auto', 'light', 'dark'}:
            value = 'auto'
        self.theme_card.setValue(value)
        self.mica_card.setChecked(bool(mica_enabled))
        self._loading = False
