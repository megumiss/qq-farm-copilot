"""Fluent 设置面板（全新实现）。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    CheckBox,
    DoubleSpinBox,
    FluentIcon,
    LineEdit,
    PushButton,
    ScrollArea,
    SpinBox,
)

from core.platform.window_manager import WindowManager
from gui.widgets.no_wheel_combo_box import NoWheelComboBox
from models.config import AppConfig, PlantMode, RunMode, WindowPlatform, WindowPosition
from models.game_data import get_crop_names


class SettingsPanel(QWidget):
    """实例设置编辑面板。"""

    config_changed = pyqtSignal(object)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._wm = WindowManager()
        self._crop_names = get_crop_names()
        self._loading = True
        self._build_ui()
        self._load()
        self._loading = False

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        content = QWidget(self)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        card = CardWidget(content)
        layout.addWidget(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)
        card_layout.addWidget(BodyLabel('设置'))
        card_layout.addWidget(CaptionLabel('窗口、平台、种植策略'))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        card_layout.addLayout(form)

        self.level = SpinBox(card)
        self.level.setRange(1, 100)
        self.level_ocr = CheckBox('自动同步', card)
        level_row = QWidget(card)
        level_layout = QHBoxLayout(level_row)
        level_layout.setContentsMargins(0, 0, 0, 0)
        level_layout.setSpacing(8)
        level_layout.addWidget(self.level)
        level_layout.addWidget(self.level_ocr)
        level_layout.addStretch()
        form.addRow('等级:', level_row)

        self.strategy = NoWheelComboBox(card)
        self.strategy.addItem('自动最新', PlantMode.LATEST_LEVEL.value)
        self.strategy.addItem('自动最优', PlantMode.BEST_EXP_RATE.value)
        self.strategy.addItem('手动选择', PlantMode.PREFERRED.value)
        form.addRow('策略:', self.strategy)

        self.crop = NoWheelComboBox(card)
        for crop in self._crop_names:
            self.crop.addItem(str(crop), str(crop))
        form.addRow('作物:', self.crop)

        self.warehouse_first = CheckBox('仓库优先', card)
        form.addRow('播种:', self.warehouse_first)

        self.platform = NoWheelComboBox(card)
        self.platform.addItem('QQ', WindowPlatform.QQ.value)
        self.platform.addItem('微信', WindowPlatform.WECHAT.value)
        form.addRow('平台:', self.platform)

        self.run_mode = NoWheelComboBox(card)
        self.run_mode.addItem('后台模式', RunMode.BACKGROUND.value)
        self.run_mode.addItem('前台模式', RunMode.FOREGROUND.value)
        form.addRow('运行方式:', self.run_mode)

        self.keyword = LineEdit(card)
        self.keyword.setPlaceholderText('窗口标题关键字')
        form.addRow('窗口关键词:', self.keyword)

        self.window_select = NoWheelComboBox(card)
        select_row = QWidget(card)
        select_layout = QHBoxLayout(select_row)
        select_layout.setContentsMargins(0, 0, 0, 0)
        select_layout.setSpacing(8)
        select_layout.addWidget(self.window_select, 1)
        self.refresh_btn = PushButton('刷新', select_row)
        self.refresh_btn.setIcon(FluentIcon.SYNC)
        self.refresh_btn.setFixedWidth(64)
        select_layout.addWidget(self.refresh_btn)
        form.addRow('选择窗口:', select_row)

        self.window_position = NoWheelComboBox(card)
        self.window_position.addItem('左侧居中', WindowPosition.LEFT_CENTER.value)
        self.window_position.addItem('居中', WindowPosition.CENTER.value)
        self.window_position.addItem('右侧居中', WindowPosition.RIGHT_CENTER.value)
        self.window_position.addItem('左上', WindowPosition.TOP_LEFT.value)
        self.window_position.addItem('右上', WindowPosition.TOP_RIGHT.value)
        self.window_position.addItem('左下', WindowPosition.LEFT_BOTTOM.value)
        self.window_position.addItem('右下', WindowPosition.RIGHT_BOTTOM.value)
        form.addRow('窗口位置:', self.window_position)

        delay_row = QWidget(card)
        delay_layout = QHBoxLayout(delay_row)
        delay_layout.setContentsMargins(0, 0, 0, 0)
        delay_layout.setSpacing(8)
        self.delay_min = DoubleSpinBox(delay_row)
        self.delay_min.setRange(0, 10)
        self.delay_min.setDecimals(2)
        self.delay_max = DoubleSpinBox(delay_row)
        self.delay_max.setRange(0, 10)
        self.delay_max.setDecimals(2)
        delay_layout.addWidget(self.delay_min)
        delay_layout.addWidget(self.delay_max)
        form.addRow('随机延迟:', delay_row)

        self.offset = SpinBox(card)
        self.offset.setRange(0, 50)
        form.addRow('点击抖动:', self.offset)

        self.max_actions = SpinBox(card)
        self.max_actions.setRange(1, 500)
        form.addRow('单轮点击上限:', self.max_actions)

        self.debug = CheckBox('启用 Debug 日志', card)
        form.addRow('调试日志:', self.debug)

        for sig in (
            self.level.valueChanged,
            self.level_ocr.toggled,
            self.strategy.currentIndexChanged,
            self.crop.currentIndexChanged,
            self.warehouse_first.toggled,
            self.platform.currentIndexChanged,
            self.run_mode.currentIndexChanged,
            self.window_select.currentIndexChanged,
            self.window_position.currentIndexChanged,
            self.delay_min.valueChanged,
            self.delay_max.valueChanged,
            self.offset.valueChanged,
            self.max_actions.valueChanged,
            self.debug.toggled,
        ):
            sig.connect(self._save)
        self.keyword.editingFinished.connect(self._on_keyword_committed)
        self.refresh_btn.clicked.connect(self._refresh_windows)

    def _refresh_windows(self) -> None:
        current = str(self.window_select.currentData() or self.config.window_select_rule or 'auto')
        self.window_select.blockSignals(True)
        self.window_select.clear()
        self.window_select.addItem('自动（平台优先）', 'auto')
        windows = self._wm.list_windows(str(self.keyword.text() or self.config.window_title_keyword))
        for idx, info in enumerate(windows):
            self.window_select.addItem(f'#{idx + 1} {info.title[:16]}', f'index:{idx}')
        self.window_select.select_data(current)
        self.window_select.blockSignals(False)

    def _on_keyword_committed(self) -> None:
        self._refresh_windows()
        self._save()

    def _load(self) -> None:
        c = self.config
        self.level.setValue(int(c.planting.player_level))
        self.level_ocr.setChecked(bool(c.planting.level_ocr_enabled))
        self.strategy.select_data(c.planting.strategy.value)
        self.crop.select_data(c.planting.preferred_crop)
        self.warehouse_first.setChecked(bool(c.planting.warehouse_first))
        self.platform.select_data(c.planting.window_platform.value)
        self.run_mode.select_data(c.safety.run_mode.value)
        self.keyword.setText(str(c.window_title_keyword or ''))
        self.window_position.select_data(c.planting.window_position.value)
        self.delay_min.setValue(float(c.safety.random_delay_min))
        self.delay_max.setValue(float(c.safety.random_delay_max))
        self.offset.setValue(int(c.safety.click_offset_range))
        self.max_actions.setValue(int(c.safety.max_actions_per_round))
        self.debug.setChecked(bool(c.safety.debug_log_enabled))
        self._refresh_windows()
        self.window_select.select_data(c.window_select_rule or 'auto')

    def _save(self) -> None:
        if self._loading:
            return
        c = self.config
        c.planting.player_level = int(self.level.value())
        c.planting.level_ocr_enabled = bool(self.level_ocr.isChecked())
        c.planting.strategy = PlantMode(str(self.strategy.currentData() or PlantMode.LATEST_LEVEL.value))
        c.planting.preferred_crop = str(self.crop.currentData() or c.planting.preferred_crop)
        c.planting.warehouse_first = bool(self.warehouse_first.isChecked())
        c.planting.window_platform = WindowPlatform(str(self.platform.currentData() or WindowPlatform.QQ.value))
        c.safety.run_mode = RunMode(str(self.run_mode.currentData() or RunMode.BACKGROUND.value))
        c.window_title_keyword = str(self.keyword.text() or '').strip()
        c.window_select_rule = str(self.window_select.currentData() or 'auto')
        c.planting.window_position = WindowPosition(
            str(self.window_position.currentData() or WindowPosition.LEFT_CENTER.value)
        )
        d_min, d_max = float(self.delay_min.value()), float(self.delay_max.value())
        c.safety.random_delay_min = min(d_min, d_max)
        c.safety.random_delay_max = max(d_min, d_max)
        c.safety.click_offset_range = int(self.offset.value())
        c.safety.max_actions_per_round = int(self.max_actions.value())
        c.safety.debug_log_enabled = bool(self.debug.isChecked())
        c.save()
        self.config_changed.emit(c)

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._loading = True
        self._load()
        self._loading = False
