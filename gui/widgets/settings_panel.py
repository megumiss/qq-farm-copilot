"""Fluent 设置面板（全新实现）。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    FluentIcon,
    HyperlinkButton,
    LineEdit,
    PushButton,
    ScrollArea,
    SpinBox,
)

from core.platform.window_manager import WindowInfo, WindowManager
from gui.widgets.fluent_container import StableElevatedCardWidget, TransparentCardContainer
from models.config import AppConfig, PlantMode, RunMode, WindowPlatform, WindowPosition
from models.game_data import get_best_crop_for_level, get_crop_names, get_latest_crop_for_level
from utils.app_paths import user_app_dir

PROJECT_URL = 'https://github.com/megumiss/qq-farm-copilot'
FREE_NOTICE_TEXT = '本项目仅供学习测试使用，自动化操作可能违反游戏服务条款，由此产生的一切后果由使用者自行承担。'


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

        content = TransparentCardContainer(self)
        scroll.setWidget(content)
        scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')
        scroll.viewport().setStyleSheet('background: transparent;')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        plant_card, plant_form = self._build_group_card(
            content,
            title='种植',
            object_name='settingsPlantCard',
        )
        layout.addWidget(plant_card)

        self.level = SpinBox(plant_card)
        self.level.setRange(1, 100)
        self.level_ocr = CheckBox('自动同步', plant_card)
        level_row = QWidget(plant_card)
        level_layout = QHBoxLayout(level_row)
        level_layout.setContentsMargins(0, 0, 0, 0)
        level_layout.setSpacing(8)
        level_layout.addWidget(self.level)
        level_layout.addWidget(self.level_ocr)
        level_layout.addStretch()
        plant_form.addRow(CaptionLabel('等级:', plant_card), level_row)

        self.strategy = ComboBox(plant_card)
        self.strategy.addItem('自动最新', userData=PlantMode.LATEST_LEVEL.value)
        self.strategy.addItem('自动最优', userData=PlantMode.BEST_EXP_RATE.value)
        self.strategy.addItem('手动选择', userData=PlantMode.PREFERRED.value)
        plant_form.addRow(CaptionLabel('策略:', plant_card), self.strategy)

        self.crop = ComboBox(plant_card)
        for crop in self._crop_names:
            self.crop.addItem(str(crop), userData=str(crop))
        plant_form.addRow(CaptionLabel('作物:', plant_card), self.crop)

        self.warehouse_first = CheckBox('仓库优先', plant_card)
        plant_form.addRow(CaptionLabel('播种:', plant_card), self.warehouse_first)
        warehouse_tip = CaptionLabel('建议开启，关闭后可能会因种子模板识别出错导致重复购买。', plant_card)
        warehouse_tip.setWordWrap(True)
        warehouse_tip.setStyleSheet('color: #d97706;')
        plant_form.addRow(CaptionLabel('', plant_card), warehouse_tip)
        self.skip_event_crops = CheckBox('排除活动作物', plant_card)
        plant_form.addRow(CaptionLabel('其他:', plant_card), self.skip_event_crops)
        event_tip = CaptionLabel(
            '提示：爱心果固定排除；此选项仅控制是否额外排除其他活动作物（当前仅艾草）。', plant_card
        )
        event_tip.setWordWrap(True)
        event_tip.setStyleSheet('color: #d97706;')
        plant_form.addRow(CaptionLabel('', plant_card), event_tip)

        env_card, env_form = self._build_group_card(
            content,
            title='其他',
            object_name='settingsEnvCard',
        )
        layout.addWidget(env_card)

        self.platform = ComboBox(env_card)
        self.platform.addItem('QQ', userData=WindowPlatform.QQ.value)
        self.platform.addItem('微信', userData=WindowPlatform.WECHAT.value)
        env_form.addRow(CaptionLabel('平台:', env_card), self.platform)

        self.run_mode = ComboBox(env_card)
        self.run_mode.addItem('后台模式', userData=RunMode.BACKGROUND.value)
        self.run_mode.addItem('前台模式', userData=RunMode.FOREGROUND.value)
        env_form.addRow(CaptionLabel('运行方式:', env_card), self.run_mode)
        run_mode_tip = CaptionLabel('提示：微信后台运行有可能会把窗口拉到前台', env_card)
        run_mode_tip.setWordWrap(True)
        run_mode_tip.setStyleSheet('color: #d97706;')
        env_form.addRow(CaptionLabel('', env_card), run_mode_tip)

        self.keyword = LineEdit(env_card)
        self.keyword.setPlaceholderText('窗口标题关键字')
        env_form.addRow(CaptionLabel('窗口关键词:', env_card), self.keyword)

        self.window_select = ComboBox(env_card)
        select_row = QWidget(env_card)
        select_layout = QHBoxLayout(select_row)
        select_layout.setContentsMargins(0, 0, 0, 0)
        select_layout.setSpacing(8)
        select_layout.addWidget(self.window_select, 1)
        self.refresh_btn = PushButton('刷新', select_row)
        self.refresh_btn.setIcon(FluentIcon.SYNC)
        refresh_btn_width = max(72, self.refresh_btn.sizeHint().width() + 8)
        self.refresh_btn.setFixedWidth(refresh_btn_width)
        select_layout.addWidget(self.refresh_btn)
        env_form.addRow(CaptionLabel('选择窗口:', env_card), select_row)

        self.window_position = ComboBox(env_card)
        self.window_position.addItem('左中', userData=WindowPosition.LEFT_CENTER.value)
        self.window_position.addItem('居中', userData=WindowPosition.CENTER.value)
        self.window_position.addItem('右中', userData=WindowPosition.RIGHT_CENTER.value)
        self.window_position.addItem('左上', userData=WindowPosition.TOP_LEFT.value)
        self.window_position.addItem('右上', userData=WindowPosition.TOP_RIGHT.value)
        self.window_position.addItem('左下', userData=WindowPosition.LEFT_BOTTOM.value)
        self.window_position.addItem('右下', userData=WindowPosition.RIGHT_BOTTOM.value)
        env_form.addRow(CaptionLabel('窗口位置:', env_card), self.window_position)

        advanced_card, advanced_form = self._build_group_card(
            content,
            title='高级',
            object_name='settingsAdvancedCard',
        )
        layout.addWidget(advanced_card)

        delay_row = QWidget(advanced_card)
        delay_layout = QHBoxLayout(delay_row)
        delay_layout.setContentsMargins(0, 0, 0, 0)
        delay_layout.setSpacing(8)
        self.delay_min = DoubleSpinBox(delay_row)
        self.delay_min.setRange(0, 10)
        self.delay_min.setDecimals(2)
        self.delay_min.setSingleStep(0.05)
        self.delay_min.setSuffix(' 秒')
        self.delay_max = DoubleSpinBox(delay_row)
        self.delay_max.setRange(0, 10)
        self.delay_max.setDecimals(2)
        self.delay_max.setSingleStep(0.05)
        self.delay_max.setSuffix(' 秒')
        delay_left = QWidget(delay_row)
        delay_left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        delay_left_layout = QHBoxLayout(delay_left)
        delay_left_layout.setContentsMargins(0, 0, 0, 0)
        delay_left_layout.setSpacing(6)
        delay_left_label = CaptionLabel('最小', delay_left)
        delay_left_layout.addWidget(delay_left_label)
        self.delay_min.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        delay_left_layout.addWidget(self.delay_min, 1)
        delay_right = QWidget(delay_row)
        delay_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        delay_right_layout = QHBoxLayout(delay_right)
        delay_right_layout.setContentsMargins(0, 0, 0, 0)
        delay_right_layout.setSpacing(6)
        delay_right_label = CaptionLabel('最大', delay_right)
        delay_right_layout.addWidget(delay_right_label)
        self.delay_max.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        delay_right_layout.addWidget(self.delay_max, 1)
        delay_label_width = max(delay_left_label.sizeHint().width(), delay_right_label.sizeHint().width())
        delay_left_label.setFixedWidth(delay_label_width)
        delay_right_label.setFixedWidth(delay_label_width)
        delay_layout.addWidget(delay_left, 1)
        delay_layout.addWidget(delay_right, 1)
        advanced_form.addRow(CaptionLabel('随机延迟:', advanced_card), delay_row)

        self.offset = SpinBox(advanced_card)
        self.offset.setRange(0, 50)
        advanced_form.addRow(CaptionLabel('点击抖动:', advanced_card), self.offset)

        self.max_actions = SpinBox(advanced_card)
        self.max_actions.setRange(1, 500)
        advanced_form.addRow(CaptionLabel('单轮点击上限:', advanced_card), self.max_actions)

        self.debug = CheckBox('启用 Debug 日志', advanced_card)
        advanced_form.addRow(CaptionLabel('调试日志:', advanced_card), self.debug)
        self.logs_path_label = CaptionLabel('', advanced_card)
        self.logs_path_label.setWordWrap(True)
        self.logs_path_label.setStyleSheet('color: #64748b;')
        advanced_form.addRow(CaptionLabel('日志路径:', advanced_card), self.logs_path_label)

        declaration_card, declaration_form = self._build_group_card(
            content,
            title='声明',
            object_name='settingsDeclarationCard',
        )
        layout.addWidget(declaration_card)
        self.free_notice = CaptionLabel(FREE_NOTICE_TEXT, declaration_card)
        self.free_notice.setWordWrap(True)
        self.free_notice.setStyleSheet('color: #dc2626; font-weight: 700;')
        declaration_form.addRow(CaptionLabel('免费声明:', declaration_card), self.free_notice)
        self.project_link = HyperlinkButton(declaration_card)
        self.project_link.setText(PROJECT_URL)
        self.project_link.setUrl(PROJECT_URL)
        declaration_form.addRow(CaptionLabel('项目地址:', declaration_card), self.project_link)
        layout.addStretch()

        for sig in (
            self.level.valueChanged,
            self.level_ocr.toggled,
            self.strategy.currentIndexChanged,
            self.crop.currentIndexChanged,
            self.warehouse_first.toggled,
            self.skip_event_crops.toggled,
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
        self.level.valueChanged.connect(self._on_level_changed)
        self.strategy.currentIndexChanged.connect(self._on_strategy_changed)
        self.keyword.editingFinished.connect(self._on_keyword_committed)
        self.refresh_btn.clicked.connect(self._refresh_windows)

    @staticmethod
    def _apply_card_style(card: StableElevatedCardWidget, object_name: str) -> None:
        card.setObjectName(object_name)
        card.setStyleSheet(
            f'ElevatedCardWidget#{object_name} {{ border-radius: 10px; }}'
            f'ElevatedCardWidget#{object_name}:hover {{ background-color: rgba(37, 99, 235, 0.04); }}'
        )

    def _build_group_card(
        self,
        parent: QWidget,
        *,
        title: str,
        object_name: str,
    ) -> tuple[StableElevatedCardWidget, QFormLayout]:
        card = StableElevatedCardWidget(parent)
        self._apply_card_style(card, object_name)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)
        card_layout.addWidget(BodyLabel(title))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        card_layout.addLayout(form)
        return card, form

    @staticmethod
    def _set_combo_data(combo: ComboBox, value) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _set_crop_by_name(self, crop_name: str) -> bool:
        if not crop_name:
            return False
        idx = self.crop.findData(str(crop_name))
        if idx < 0:
            return False
        if self.crop.currentIndex() == idx:
            return False
        was_loading = self._loading
        self._loading = True
        self.crop.setCurrentIndex(idx)
        self._loading = was_loading
        return True

    def _sync_crop_from_strategy(self) -> bool:
        strategy_value = str(self.strategy.currentData() or PlantMode.LATEST_LEVEL.value)
        level = int(self.level.value())
        crop = None
        if strategy_value == PlantMode.BEST_EXP_RATE.value:
            crop = get_best_crop_for_level(level)
        elif strategy_value == PlantMode.LATEST_LEVEL.value:
            crop = get_latest_crop_for_level(level)
        if not crop:
            return False
        return self._set_crop_by_name(str(crop[0]))

    def _on_strategy_changed(self, *_args) -> None:
        manual = str(self.strategy.currentData() or '') == PlantMode.PREFERRED.value
        self.crop.setEnabled(manual)
        if not manual:
            self._sync_crop_from_strategy()

    def _on_level_changed(self, *_args) -> None:
        strategy_value = str(self.strategy.currentData() or PlantMode.LATEST_LEVEL.value)
        if strategy_value != PlantMode.PREFERRED.value:
            self._sync_crop_from_strategy()

    def _refresh_windows(self) -> None:
        current = str(self.window_select.currentData() or self.config.window_select_rule or 'auto')
        self.window_select.blockSignals(True)
        self.window_select.clear()
        self.window_select.addItem('自动', userData='auto')
        windows = self._wm.list_windows(str(self.keyword.text() or self.config.window_title_keyword))
        for idx, info in enumerate(windows):
            self.window_select.addItem(self._format_window_option_label(idx, info), userData=f'index:{idx}')
        self._set_combo_data(self.window_select, current)
        self.window_select.blockSignals(False)

    @staticmethod
    def _format_window_option_label(index: int, info: WindowInfo) -> str:
        title = str(info.title).replace('\n', ' ').strip()
        if len(title) > 16:
            title = f'{title[:16]}...'
        process_name = str(info.process_name or '').strip().lower()
        if process_name == 'qq.exe' or process_name.startswith('qq'):
            platform = 'QQ'
        elif process_name.startswith('wechat') or 'weixin' in process_name:
            platform = '微信'
        else:
            platform = '未知'
        return (
            f'#{index + 1} [{platform}] {title} | '
            f'{int(info.width)}x{int(info.height)} | '
            f'({int(info.left)},{int(info.top)}) | '
            f'0x{int(info.hwnd):X}'
        )

    def _on_keyword_committed(self) -> None:
        self._refresh_windows()
        self._save()

    def _resolve_logs_path_text(self) -> str:
        config_path = str(getattr(self.config, '_config_path', '') or '').strip()
        if config_path:
            try:
                cfg_path = Path(config_path).resolve()
                # 期望结构：.../instances/<instance_id>/configs/config.json
                if cfg_path.name.lower() == 'config.json' and cfg_path.parent.name == 'configs':
                    return str((cfg_path.parent.parent / 'logs').resolve())
            except Exception:
                pass
        return str((user_app_dir() / 'logs').resolve())

    def _load(self) -> None:
        c = self.config
        self.level.setValue(int(c.planting.player_level))
        self.level_ocr.setChecked(bool(c.planting.level_ocr_enabled))
        self._set_combo_data(self.strategy, c.planting.strategy.value)
        self._set_combo_data(self.crop, c.planting.preferred_crop)
        self.warehouse_first.setChecked(bool(c.planting.warehouse_first))
        self.skip_event_crops.setChecked(bool(c.planting.skip_event_crops))
        self._set_combo_data(self.platform, c.planting.window_platform.value)
        self._set_combo_data(self.run_mode, c.safety.run_mode.value)
        self.keyword.setText(str(c.window_title_keyword or ''))
        self._set_combo_data(self.window_position, c.planting.window_position.value)
        self.delay_min.setValue(float(c.safety.random_delay_min))
        self.delay_max.setValue(float(c.safety.random_delay_max))
        self.offset.setValue(int(c.safety.click_offset_range))
        self.max_actions.setValue(int(c.safety.max_actions_per_round))
        self.debug.setChecked(bool(c.safety.debug_log_enabled))
        self.logs_path_label.setText(self._resolve_logs_path_text())
        self._refresh_windows()
        self._set_combo_data(self.window_select, c.window_select_rule or 'auto')
        self._on_strategy_changed()

    def _save(self) -> None:
        if self._loading:
            return
        c = self.config
        c.planting.player_level = int(self.level.value())
        c.planting.level_ocr_enabled = bool(self.level_ocr.isChecked())
        c.planting.strategy = PlantMode(str(self.strategy.currentData() or PlantMode.LATEST_LEVEL.value))
        c.planting.preferred_crop = str(self.crop.currentData() or c.planting.preferred_crop)
        c.planting.warehouse_first = bool(self.warehouse_first.isChecked())
        c.planting.skip_event_crops = bool(self.skip_event_crops.isChecked())
        platform_value = str(self.platform.currentData() or WindowPlatform.QQ.value)
        run_mode_value = str(self.run_mode.currentData() or RunMode.BACKGROUND.value)
        c.planting.window_platform = WindowPlatform(platform_value)
        c.safety.run_mode = RunMode(run_mode_value)
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
