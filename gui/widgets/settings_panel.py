"""设置面板 - 紧凑布局，实时生效"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QSpinBox, QCheckBox, QComboBox,
    QGroupBox, QFormLayout, QGridLayout,
)
from PyQt6.QtCore import pyqtSignal

from models.config import AppConfig, PlantMode, WindowPosition, WindowPlatform
from models.game_data import CROPS, get_crop_names, format_grow_time, get_best_crop_for_level


class SettingsPanel(QWidget):
    config_changed = pyqtSignal(object)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._loading = True
        self._init_ui()
        self._load_config()
        self._connect_auto_save()
        self._loading = False

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ===== 种植设置 =====
        plant_group = QGroupBox("种植")
        pf = QFormLayout()
        pf.setSpacing(5)

        row_level = QHBoxLayout()
        self._player_level = QSpinBox()
        self._player_level.setRange(1, 100)
        self._player_level.setFixedWidth(80)
        row_level.addWidget(QLabel("等级"))
        row_level.addWidget(self._player_level)
        self._strategy_combo = QComboBox()
        self._strategy_combo.addItem("自动最优", PlantMode.BEST_EXP_RATE.value)
        self._strategy_combo.addItem("手动指定", PlantMode.PREFERRED.value)
        row_level.addWidget(QLabel("策略"))
        row_level.addWidget(self._strategy_combo, 1)
        pf.addRow(row_level)

        self._auto_crop_label = QLabel()
        self._auto_crop_label.setStyleSheet("color: #16a34a; font-weight: bold; font-size: 12px;")
        pf.addRow("推荐:", self._auto_crop_label)

        self._crop_combo = QComboBox()
        self._crop_names = get_crop_names()
        pf.addRow("作物:", self._crop_combo)

        self._buy_quantity = QSpinBox()
        self._buy_quantity.setRange(1, 999)
        self._buy_quantity.setFixedWidth(80)
        pf.addRow("购买数量:", self._buy_quantity)

        self._player_level.valueChanged.connect(self._on_level_changed)
        self._player_level.valueChanged.connect(self._update_auto_crop_label)
        self._strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        plant_group.setLayout(pf)
        layout.addWidget(plant_group)

        # ===== 功能开关 =====
        feat_group = QGroupBox("功能")
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setContentsMargins(8, 4, 8, 4)
        self._cb_harvest = QCheckBox("收获")
        self._cb_plant = QCheckBox("播种")
        self._cb_water = QCheckBox("浇水")
        self._cb_weed = QCheckBox("除草")
        self._cb_bug = QCheckBox("除虫")
        self._cb_sell = QCheckBox("出售")
        self._cb_steal = QCheckBox("偷菜")
        self._cb_help = QCheckBox("帮忙")
        self._cb_task = QCheckBox("任务")
        self._cb_upgrade = QCheckBox("扩建")
        cbs = [self._cb_harvest, self._cb_plant, self._cb_water,
               self._cb_weed, self._cb_bug, self._cb_sell,
               self._cb_steal, self._cb_help, self._cb_task, self._cb_upgrade]
        for i, cb in enumerate(cbs):
            grid.addWidget(cb, i // 5, i % 5)
        feat_group.setLayout(grid)
        layout.addWidget(feat_group)

        # ===== 其他 =====
        misc_group = QGroupBox("其他")
        mf = QFormLayout()
        mf.setSpacing(5)
        self._window_platform = QComboBox()
        self._window_platform.addItem("QQ", WindowPlatform.QQ.value)
        self._window_platform.addItem("微信", WindowPlatform.WECHAT.value)
        mf.addRow("平台:", self._window_platform)
        self._window_keyword = QLineEdit()
        mf.addRow("窗口关键词:", self._window_keyword)
        self._window_position = QComboBox()
        self._window_position.addItem("左侧居中", WindowPosition.LEFT_CENTER.value)
        self._window_position.addItem("居中", WindowPosition.CENTER.value)
        self._window_position.addItem("右侧居中", WindowPosition.RIGHT_CENTER.value)
        self._window_position.addItem("左上", WindowPosition.TOP_LEFT.value)
        self._window_position.addItem("右上", WindowPosition.TOP_RIGHT.value)
        self._window_position.addItem("左下", WindowPosition.LEFT_BOTTOM.value)
        self._window_position.addItem("右下", WindowPosition.RIGHT_BOTTOM.value)
        mf.addRow("窗口位置:", self._window_position)
        row_sched = QHBoxLayout()
        self._farm_interval = QSpinBox()
        self._farm_interval.setRange(1, 120)
        self._farm_interval.setSuffix("分")
        self._farm_interval.setFixedWidth(80)
        row_sched.addWidget(QLabel("农场"))
        row_sched.addWidget(self._farm_interval)
        self._friend_interval = QSpinBox()
        self._friend_interval.setRange(5, 180)
        self._friend_interval.setSuffix("分")
        self._friend_interval.setFixedWidth(80)
        row_sched.addWidget(QLabel("好友"))
        row_sched.addWidget(self._friend_interval)
        row_sched.addStretch()
        mf.addRow("检查间隔:", row_sched)
        misc_group.setLayout(mf)
        layout.addWidget(misc_group)

        layout.addStretch()

    def _connect_auto_save(self):
        self._player_level.valueChanged.connect(self._auto_save)
        self._strategy_combo.currentIndexChanged.connect(self._auto_save)
        self._crop_combo.currentIndexChanged.connect(self._auto_save)
        self._buy_quantity.valueChanged.connect(self._auto_save)
        self._window_platform.currentIndexChanged.connect(self._auto_save)
        self._window_keyword.editingFinished.connect(self._auto_save)
        self._window_position.currentIndexChanged.connect(self._auto_save)
        self._farm_interval.valueChanged.connect(self._auto_save)
        self._friend_interval.valueChanged.connect(self._auto_save)
        for cb in (self._cb_harvest, self._cb_plant, self._cb_water,
                   self._cb_weed, self._cb_bug, self._cb_sell,
                   self._cb_steal, self._cb_help, self._cb_task, self._cb_upgrade):
            cb.toggled.connect(self._auto_save)

    def _auto_save(self):
        if self._loading:
            return
        c = self.config
        c.planting.player_level = self._player_level.value()
        c.planting.buy_quantity = self._buy_quantity.value()
        c.planting.strategy = PlantMode(self._strategy_combo.currentData())
        idx = self._crop_combo.currentIndex()
        if 0 <= idx < len(self._crop_names):
            c.planting.preferred_crop = self._crop_names[idx]
        c.planting.window_platform = WindowPlatform(self._window_platform.currentData())
        c.window_title_keyword = self._window_keyword.text().strip()
        c.planting.window_position = WindowPosition(self._window_position.currentData())
        c.schedule.farm_check_minutes = self._farm_interval.value()
        c.schedule.friend_check_minutes = self._friend_interval.value()
        c.features.auto_harvest = self._cb_harvest.isChecked()
        c.features.auto_plant = self._cb_plant.isChecked()
        c.features.auto_water = self._cb_water.isChecked()
        c.features.auto_weed = self._cb_weed.isChecked()
        c.features.auto_bug = self._cb_bug.isChecked()
        c.features.auto_sell = self._cb_sell.isChecked()
        c.features.auto_steal = self._cb_steal.isChecked()
        c.features.auto_help = self._cb_help.isChecked()
        c.features.auto_task = self._cb_task.isChecked()
        c.features.auto_upgrade = self._cb_upgrade.isChecked()
        c.save()
        self.config_changed.emit(c)

    def _on_level_changed(self, level: int):
        self._loading = True
        current_crop = (self._crop_names[self._crop_combo.currentIndex()]
                        if self._crop_combo.currentIndex() >= 0 else "")
        self._crop_combo.clear()
        for name, _, req_level, grow_time, exp, _ in CROPS:
            time_str = format_grow_time(grow_time)
            if req_level <= level:
                self._crop_combo.addItem(f"{name} (Lv{req_level}, {time_str}, {exp}经验)")
            else:
                self._crop_combo.addItem(f"[锁] {name} (需Lv{req_level})")
        if current_crop in self._crop_names:
            self._crop_combo.setCurrentIndex(self._crop_names.index(current_crop))
        self._loading = False

    def _on_strategy_changed(self, index: int):
        is_manual = self._strategy_combo.itemData(index) == PlantMode.PREFERRED.value
        self._crop_combo.setEnabled(is_manual)
        self._auto_crop_label.setVisible(not is_manual)
        self._update_auto_crop_label()

    def _update_auto_crop_label(self):
        level = self._player_level.value()
        best = get_best_crop_for_level(level)
        if best:
            name, _, _, grow_time, exp, _ = best
            time_str = format_grow_time(grow_time)
            rate = exp / grow_time
            self._auto_crop_label.setText(f"{name} ({time_str}, {exp}exp, {rate:.4f}/s)")
        else:
            self._auto_crop_label.setText("无可用作物")

    def _load_config(self):
        c = self.config
        self._player_level.setValue(c.planting.player_level)
        self._buy_quantity.setValue(c.planting.buy_quantity)
        strategy_idx = 0 if c.planting.strategy == PlantMode.BEST_EXP_RATE else 1
        self._strategy_combo.setCurrentIndex(strategy_idx)
        self._on_strategy_changed(strategy_idx)
        self._update_auto_crop_label()
        if c.planting.preferred_crop in self._crop_names:
            self._crop_combo.setCurrentIndex(
                self._crop_names.index(c.planting.preferred_crop))
        self._on_level_changed(c.planting.player_level)
        for i in range(self._window_platform.count()):
            if self._window_platform.itemData(i) == c.planting.window_platform.value:
                self._window_platform.setCurrentIndex(i)
                break
        self._window_keyword.setText(c.window_title_keyword)
        for i in range(self._window_position.count()):
            if self._window_position.itemData(i) == c.planting.window_position.value:
                self._window_position.setCurrentIndex(i)
                break
        self._farm_interval.setValue(c.schedule.farm_check_minutes)
        self._friend_interval.setValue(c.schedule.friend_check_minutes)
        self._cb_harvest.setChecked(c.features.auto_harvest)
        self._cb_plant.setChecked(c.features.auto_plant)
        self._cb_water.setChecked(c.features.auto_water)
        self._cb_weed.setChecked(c.features.auto_weed)
        self._cb_bug.setChecked(c.features.auto_bug)
        self._cb_sell.setChecked(c.features.auto_sell)
        self._cb_steal.setChecked(c.features.auto_steal)
        self._cb_help.setChecked(c.features.auto_help)
        self._cb_task.setChecked(c.features.auto_task)
        self._cb_upgrade.setChecked(c.features.auto_upgrade)
