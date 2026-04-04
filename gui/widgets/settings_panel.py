"""设置面板 - 紧凑布局，实时生效"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from models.config import AppConfig, PlantMode, WindowPlatform, WindowPosition
from models.game_data import CROPS, format_grow_time, get_best_crop_for_level, get_crop_names


class SettingsPanel(QWidget):
    """承载 `SettingsPanel` 相关界面控件与交互逻辑。"""
    config_changed = pyqtSignal(object)

    def __init__(self, config: AppConfig, parent=None):
        """初始化设置面板并加载现有配置。"""
        super().__init__(parent)
        self.config = config
        self._loading = True
        self._init_ui()
        self._load_config()
        self._connect_auto_save()
        self._loading = False

    def _init_ui(self):
        """构建“种植 + 其他”两组配置项界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ===== 种植设置 =====
        # 等级与策略在同一行，便于联动查看“可种作物”和“推荐作物”。
        plant_group = QGroupBox('种植')
        pf = QFormLayout()
        pf.setSpacing(5)

        row_level = QHBoxLayout()
        self._player_level = QSpinBox()
        self._player_level.setRange(1, 100)
        self._player_level.setFixedWidth(80)
        row_level.addWidget(QLabel('等级'))
        row_level.addWidget(self._player_level)
        self._strategy_combo = QComboBox()
        self._strategy_combo.addItem('自动最优', PlantMode.BEST_EXP_RATE.value)
        self._strategy_combo.addItem('手动指定', PlantMode.PREFERRED.value)
        row_level.addWidget(QLabel('策略'))
        row_level.addWidget(self._strategy_combo, 1)
        pf.addRow(row_level)

        self._auto_crop_label = QLabel()
        self._auto_crop_label.setStyleSheet('color: #16a34a; font-weight: bold; font-size: 12px;')
        pf.addRow('推荐:', self._auto_crop_label)

        self._crop_combo = QComboBox()
        self._crop_names = get_crop_names()
        pf.addRow('作物:', self._crop_combo)

        self._player_level.valueChanged.connect(self._on_level_changed)
        self._player_level.valueChanged.connect(self._update_auto_crop_label)
        self._strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        plant_group.setLayout(pf)
        layout.addWidget(plant_group)

        # ===== 其他 =====
        # 窗口平台/关键词/位置统一归类为“运行环境”参数。
        misc_group = QGroupBox('其他')
        mf = QFormLayout()
        mf.setSpacing(5)
        self._window_platform = QComboBox()
        self._window_platform.addItem('QQ', WindowPlatform.QQ.value)
        self._window_platform.addItem('微信', WindowPlatform.WECHAT.value)
        mf.addRow('平台:', self._window_platform)
        self._window_keyword = QLineEdit()
        mf.addRow('窗口关键词:', self._window_keyword)
        self._window_position = QComboBox()
        self._window_position.addItem('左侧居中', WindowPosition.LEFT_CENTER.value)
        self._window_position.addItem('居中', WindowPosition.CENTER.value)
        self._window_position.addItem('右侧居中', WindowPosition.RIGHT_CENTER.value)
        self._window_position.addItem('左上', WindowPosition.TOP_LEFT.value)
        self._window_position.addItem('右上', WindowPosition.TOP_RIGHT.value)
        self._window_position.addItem('左下', WindowPosition.LEFT_BOTTOM.value)
        self._window_position.addItem('右下', WindowPosition.RIGHT_BOTTOM.value)
        mf.addRow('窗口位置:', self._window_position)
        misc_group.setLayout(mf)
        layout.addWidget(misc_group)

        layout.addStretch()

    def _connect_auto_save(self):
        """将用户改动实时写回配置文件。"""
        self._player_level.valueChanged.connect(self._auto_save)
        self._strategy_combo.currentIndexChanged.connect(self._auto_save)
        self._crop_combo.currentIndexChanged.connect(self._auto_save)
        self._window_platform.currentIndexChanged.connect(self._auto_save)
        self._window_keyword.editingFinished.connect(self._auto_save)
        self._window_position.currentIndexChanged.connect(self._auto_save)

    def _auto_save(self):
        """从控件回填配置对象并持久化。"""
        if self._loading:
            return
        c = self.config
        c.planting.player_level = self._player_level.value()
        c.planting.strategy = PlantMode(self._strategy_combo.currentData())
        idx = self._crop_combo.currentIndex()
        if 0 <= idx < len(self._crop_names):
            c.planting.preferred_crop = self._crop_names[idx]
        c.planting.window_platform = WindowPlatform(self._window_platform.currentData())
        c.window_title_keyword = self._window_keyword.text().strip()
        c.planting.window_position = WindowPosition(self._window_position.currentData())
        c.save()
        self.config_changed.emit(c)

    def _on_level_changed(self, level: int):
        """按玩家等级重建作物下拉列表，并保留已有选择。"""
        self._loading = True
        current_crop = self._crop_names[self._crop_combo.currentIndex()] if self._crop_combo.currentIndex() >= 0 else ''
        self._crop_combo.clear()
        # 所有作物都展示出来：可种的显示收益信息，不可种的标记“锁定”。
        for name, _, req_level, grow_time, exp, _ in CROPS:
            time_str = format_grow_time(grow_time)
            if req_level <= level:
                self._crop_combo.addItem(f'{name} (Lv{req_level}, {time_str}, {exp}经验)')
            else:
                self._crop_combo.addItem(f'[锁] {name} (需Lv{req_level})')
        # 仅当旧作物仍在列表中时恢复选择，避免等级变化后索引错位。
        if current_crop in self._crop_names:
            self._crop_combo.setCurrentIndex(self._crop_names.index(current_crop))
        self._loading = False

    def _on_strategy_changed(self, index: int):
        """切换种植策略时同步手动作物控件与推荐提示可见性。"""
        is_manual = self._strategy_combo.itemData(index) == PlantMode.PREFERRED.value
        self._crop_combo.setEnabled(is_manual)
        self._auto_crop_label.setVisible(not is_manual)
        self._update_auto_crop_label()

    def _update_auto_crop_label(self):
        """刷新“自动最优”策略下的推荐作物说明。"""
        level = self._player_level.value()
        best = get_best_crop_for_level(level)
        if best:
            name, _, _, grow_time, exp, _ = best
            time_str = format_grow_time(grow_time)
            rate = exp / grow_time
            self._auto_crop_label.setText(f'{name} ({time_str}, {exp}exp, {rate:.4f}/s)')
        else:
            self._auto_crop_label.setText('无可用作物')

    def _load_config(self):
        """将配置文件中的值回填到界面控件。"""
        c = self.config
        self._player_level.setValue(c.planting.player_level)
        strategy_idx = 0 if c.planting.strategy == PlantMode.BEST_EXP_RATE else 1
        self._strategy_combo.setCurrentIndex(strategy_idx)
        # 先设置策略，再同步推荐文案与作物列表，保证控件状态一致。
        self._on_strategy_changed(strategy_idx)
        self._update_auto_crop_label()
        if c.planting.preferred_crop in self._crop_names:
            self._crop_combo.setCurrentIndex(self._crop_names.index(c.planting.preferred_crop))
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
