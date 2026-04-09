"""设置面板 - 紧凑布局，实时生效"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.no_wheel_combo_box import NoWheelComboBox
from models.config import AppConfig, PlantMode, RunMode, WindowPlatform, WindowPosition
from models.game_data import CROPS, format_grow_time, get_best_crop_for_level, get_crop_names, get_latest_crop_for_level

PROJECT_URL = 'https://github.com/megumiss/qq-farm-copilot'


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
        """构建设置界面并提供滚动能力。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName('settingsScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName('settingsViewport')
        scroll.setStyleSheet("""
            QScrollArea#settingsScroll { background: transparent; border: none; border-radius: 8px; }
            QWidget#settingsViewport { background: transparent; border-radius: 8px; }
            QWidget#settingsContent { background: transparent; }
        """)
        content = QWidget()
        content.setObjectName('settingsContent')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        scroll.setWidget(content)
        root.addWidget(scroll)

        # ===== 种植设置 =====
        # 等级与策略在同一行，便于联动查看可种作物并自动同步最优作物。
        plant_group = QGroupBox('种植')
        pf = QFormLayout()
        pf.setContentsMargins(0, 0, 0, 4)
        pf.setSpacing(10)

        row_level = QHBoxLayout()
        self._player_level = QSpinBox()
        self._player_level.setRange(1, 100)
        self._player_level.setFixedWidth(80)
        row_level.addWidget(QLabel('等级'))
        row_level.addWidget(self._player_level)
        self._strategy_combo = NoWheelComboBox()
        self._strategy_combo.addItem('自动最新', PlantMode.LATEST_LEVEL.value)
        self._strategy_combo.addItem('自动最优', PlantMode.BEST_EXP_RATE.value)
        self._strategy_combo.addItem('手动选择', PlantMode.PREFERRED.value)
        row_level.addWidget(QLabel('策略'))
        row_level.addWidget(self._strategy_combo, 1)
        pf.addRow(row_level)

        self._crop_combo = NoWheelComboBox()
        self._crop_names = get_crop_names()
        pf.addRow('作物:', self._crop_combo)

        self._player_level.valueChanged.connect(self._on_level_changed)
        self._strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        plant_group.setLayout(pf)
        layout.addWidget(plant_group)

        # ===== 其他 =====
        # 窗口平台/关键词/位置统一归类为“运行环境”参数。
        misc_group = QGroupBox('其他')
        mf = QFormLayout()
        mf.setContentsMargins(0, 0, 0, 4)
        mf.setSpacing(10)
        self._window_platform = NoWheelComboBox()
        self._window_platform.addItem('QQ', WindowPlatform.QQ.value)
        self._window_platform.addItem('微信', WindowPlatform.WECHAT.value)
        mf.addRow('平台:', self._window_platform)
        self._run_mode = NoWheelComboBox()
        self._run_mode.addItem('后台模式', RunMode.BACKGROUND.value)
        self._run_mode.addItem('前台模式', RunMode.FOREGROUND.value)
        mf.addRow('运行方式:', self._run_mode)
        self._run_mode_tip = QLabel('提示：仅 QQ 平台支持后台模式，微信平台会自动使用前台模式')
        self._run_mode_tip.setWordWrap(True)
        self._run_mode_tip.setStyleSheet('color: #d97706;')
        mf.addRow('', self._run_mode_tip)
        self._window_keyword = QLineEdit()
        mf.addRow('窗口关键词:', self._window_keyword)
        self._window_position = NoWheelComboBox()
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

        # ===== 高级设置 =====
        self._advanced_group = QGroupBox('高级')
        af = QFormLayout()
        af.setContentsMargins(0, 0, 0, 0)
        af.setSpacing(10)
        # 安全参数归类到“高级”分组。
        self._random_delay_min = QDoubleSpinBox()
        self._random_delay_min.setRange(0.0, 10.0)
        self._random_delay_min.setDecimals(2)
        self._random_delay_min.setSingleStep(0.05)
        self._random_delay_min.setSuffix(' 秒')
        self._random_delay_min.setToolTip('每次操作后的最小随机停顿时间')
        self._random_delay_max = QDoubleSpinBox()
        self._random_delay_max.setRange(0.0, 10.0)
        self._random_delay_max.setDecimals(2)
        self._random_delay_max.setSingleStep(0.05)
        self._random_delay_max.setSuffix(' 秒')
        self._random_delay_max.setToolTip('每次操作后的最大随机停顿时间')
        delay_row = QWidget()
        delay_layout = QHBoxLayout(delay_row)
        delay_layout.setContentsMargins(0, 0, 0, 0)
        delay_layout.setSpacing(8)
        delay_layout.addWidget(QLabel('最小'))
        delay_layout.addWidget(self._random_delay_min)
        delay_layout.addSpacing(12)
        delay_layout.addWidget(QLabel('最大'))
        delay_layout.addWidget(self._random_delay_max)
        delay_layout.addStretch()
        af.addRow('随机延迟:', delay_row)
        self._click_offset_range = QSpinBox()
        self._click_offset_range.setRange(0, 50)
        af.addRow('点击抖动范围(像素):', self._click_offset_range)
        self._max_actions_per_round = QSpinBox()
        self._max_actions_per_round.setRange(1, 500)
        af.addRow('单轮最大点击数:', self._max_actions_per_round)
        self._debug_log_enabled = QCheckBox('输出 Debug 日志')
        self._debug_log_enabled.setToolTip('开启后，控制台、日志文件和界面日志都会输出 DEBUG 级别日志')
        af.addRow('调试日志:', self._debug_log_enabled)
        self._advanced_group.setLayout(af)
        layout.addWidget(self._advanced_group)

        declaration_group = QGroupBox('声明')
        df = QFormLayout()
        df.setContentsMargins(0, 0, 0, 4)
        df.setSpacing(10)
        self._free_notice = QLabel('本软件完全免费，若付费购买请立即退款。')
        self._free_notice.setWordWrap(True)
        self._free_notice.setStyleSheet('color: #dc2626; font-weight: bold;')
        df.addRow('免费声明:', self._free_notice)
        self._project_link = QLabel(f'<a href="{PROJECT_URL}">{PROJECT_URL}</a>')
        self._project_link.setOpenExternalLinks(True)
        self._project_link.setWordWrap(True)
        df.addRow('项目地址:', self._project_link)
        declaration_group.setLayout(df)
        layout.addWidget(declaration_group)

        layout.addStretch()

    def _connect_auto_save(self):
        """将用户改动实时写回配置文件。"""
        self._player_level.valueChanged.connect(self._auto_save)
        self._strategy_combo.currentIndexChanged.connect(self._auto_save)
        self._crop_combo.currentIndexChanged.connect(self._auto_save)
        self._window_platform.currentIndexChanged.connect(self._auto_save)
        self._run_mode.currentIndexChanged.connect(self._auto_save)
        self._random_delay_min.valueChanged.connect(self._auto_save)
        self._random_delay_max.valueChanged.connect(self._auto_save)
        self._click_offset_range.valueChanged.connect(self._auto_save)
        self._max_actions_per_round.valueChanged.connect(self._auto_save)
        self._debug_log_enabled.toggled.connect(self._auto_save)
        self._window_keyword.editingFinished.connect(self._auto_save)
        self._window_position.currentIndexChanged.connect(self._auto_save)

    def _auto_save(self):
        """从控件回填配置对象并持久化。"""
        if self._loading:
            return
        c = self.config
        c.planting.player_level = self._player_level.value()
        strategy_value = self._strategy_combo.currentData() or PlantMode.BEST_EXP_RATE.value
        c.planting.strategy = PlantMode(strategy_value)
        idx = self._crop_combo.currentIndex()
        if 0 <= idx < len(self._crop_names):
            c.planting.preferred_crop = self._crop_names[idx]
        c.planting.window_platform = WindowPlatform(self._window_platform.currentData())
        c.safety.run_mode = RunMode(self._run_mode.currentData())
        delay_min = float(self._random_delay_min.value())
        delay_max = float(self._random_delay_max.value())
        c.safety.random_delay_min = min(delay_min, delay_max)
        c.safety.random_delay_max = max(delay_min, delay_max)
        c.safety.click_offset_range = int(self._click_offset_range.value())
        c.safety.max_actions_per_round = int(self._max_actions_per_round.value())
        c.safety.debug_log_enabled = bool(self._debug_log_enabled.isChecked())
        c.window_title_keyword = self._window_keyword.text().strip()
        c.planting.window_position = WindowPosition(self._window_position.currentData())
        c.save()
        self.config_changed.emit(c)

    def _on_level_changed(self, level: int):
        """按玩家等级重建作物下拉列表，并保留已有选择。"""
        was_loading = self._loading
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
        self._loading = was_loading
        self._sync_crop_from_strategy()

    def _on_strategy_changed(self, index: int):
        """切换种植策略时同步作物控件状态与自动最优作物。"""
        is_manual = self._strategy_combo.itemData(index) == PlantMode.PREFERRED.value
        self._crop_combo.setEnabled(is_manual)
        self._sync_crop_from_strategy()

    def _sync_crop_from_strategy(self) -> bool:
        """自动策略下，将作物下拉同步到策略对应作物。"""
        strategy_value = self._strategy_combo.currentData() or PlantMode.BEST_EXP_RATE.value
        level = self._player_level.value()
        selected = None
        if strategy_value == PlantMode.BEST_EXP_RATE.value:
            selected = get_best_crop_for_level(level)
        elif strategy_value == PlantMode.LATEST_LEVEL.value:
            selected = get_latest_crop_for_level(level)
        else:
            return False

        if selected:
            crop_name = selected[0]
            if crop_name in self._crop_names:
                target_index = self._crop_names.index(crop_name)
                if self._crop_combo.currentIndex() != target_index:
                    was_loading = self._loading
                    self._loading = True
                    self._crop_combo.setCurrentIndex(target_index)
                    self._loading = was_loading
                    return True
        return False

    def _load_config(self):
        """将配置文件中的值回填到界面控件。"""
        c = self.config
        self._player_level.setValue(c.planting.player_level)
        strategy_idx = 0
        for i in range(self._strategy_combo.count()):
            if self._strategy_combo.itemData(i) == c.planting.strategy.value:
                strategy_idx = i
                break
        self._strategy_combo.setCurrentIndex(strategy_idx)
        self._on_level_changed(c.planting.player_level)
        if (
            self._strategy_combo.currentData() == PlantMode.PREFERRED.value
            and c.planting.preferred_crop in self._crop_names
        ):
            self._crop_combo.setCurrentIndex(self._crop_names.index(c.planting.preferred_crop))
        self._on_strategy_changed(strategy_idx)
        for i in range(self._window_platform.count()):
            if self._window_platform.itemData(i) == c.planting.window_platform.value:
                self._window_platform.setCurrentIndex(i)
                break
        for i in range(self._run_mode.count()):
            if self._run_mode.itemData(i) == c.safety.run_mode.value:
                self._run_mode.setCurrentIndex(i)
                break
        self._random_delay_min.setValue(float(c.safety.random_delay_min))
        self._random_delay_max.setValue(float(c.safety.random_delay_max))
        self._click_offset_range.setValue(int(c.safety.click_offset_range))
        self._max_actions_per_round.setValue(int(c.safety.max_actions_per_round))
        self._debug_log_enabled.setChecked(bool(c.safety.debug_log_enabled))
        self._window_keyword.setText(c.window_title_keyword)
        for i in range(self._window_position.count()):
            if self._window_position.itemData(i) == c.planting.window_position.value:
                self._window_position.setCurrentIndex(i)
                break

    def set_config(self, config: AppConfig):
        """替换配置对象并刷新界面。"""
        self.config = config
        self._loading = True
        self._load_config()
        self._loading = False
