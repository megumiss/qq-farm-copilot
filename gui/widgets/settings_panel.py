"""Fluent 设置面板（全新实现）。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QFormLayout, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    FluentIcon,
    LineEdit,
    PushButton,
    ScrollArea,
    SpinBox,
)

from core.platform.window_manager import DisplayInfo, WindowInfo, WindowManager
from gui.widgets.fluent_container import StableElevatedCardWidget, TransparentCardContainer
from models.config import AppConfig, PlantMode, RunMode, WindowPlatform, WindowPosition
from models.game_data import get_best_crop_for_level, get_crop_names, get_latest_crop_for_level
from utils.app_paths import user_app_dir


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
        plant_form.addRow(self._field_label('等级', plant_card), level_row)

        self.strategy = ComboBox(plant_card)
        self.strategy.addItem('自动最新', userData=PlantMode.LATEST_LEVEL.value)
        self.strategy.addItem('自动最优', userData=PlantMode.BEST_EXP_RATE.value)
        self.strategy.addItem('手动选择', userData=PlantMode.PREFERRED.value)
        plant_form.addRow(self._field_label('播种策略', plant_card), self.strategy)

        self.crop = ComboBox(plant_card)
        for crop in self._crop_names:
            self.crop.addItem(str(crop), userData=str(crop))
        plant_form.addRow(self._field_label('选择作物', plant_card), self.crop)

        self.warehouse_first = CheckBox('仓库优先', plant_card)
        plant_form.addRow(self._field_label('播种', plant_card), self.warehouse_first)
        warehouse_tip = CaptionLabel('建议开启，关闭后可能会因种子模板识别出错导致重复购买。', plant_card)
        warehouse_tip.setWordWrap(True)
        warehouse_tip.setStyleSheet('color: #d97706;')
        plant_form.addRow(self._field_label('', plant_card), warehouse_tip)
        self.skip_event_crops = CheckBox('排除活动作物', plant_card)
        plant_form.addRow(self._field_label('其他设置', plant_card), self.skip_event_crops)
        event_tip = CaptionLabel('爱心果固定排除；此选项仅控制是否额外排除其他活动作物（当前仅艾草）。', plant_card)
        event_tip.setWordWrap(True)
        event_tip.setStyleSheet('color: #d97706;')
        plant_form.addRow(self._field_label('', plant_card), event_tip)

        env_card, env_form = self._build_group_card(
            content,
            title='其他',
            object_name='settingsEnvCard',
        )
        layout.addWidget(env_card)

        self.platform = ComboBox(env_card)
        self.platform.addItem('QQ', userData=WindowPlatform.QQ.value)
        self.platform.addItem('微信', userData=WindowPlatform.WECHAT.value)
        env_form.addRow(self._field_label('平台', env_card), self.platform)

        self.run_mode = ComboBox(env_card)
        self.run_mode.addItem('后台模式', userData=RunMode.BACKGROUND.value)
        self.run_mode.addItem('前台模式', userData=RunMode.FOREGROUND.value)
        env_form.addRow(self._field_label('运行方式', env_card), self.run_mode)
        run_mode_tip = CaptionLabel('微信后台运行有可能会把窗口拉到前台', env_card)
        run_mode_tip.setWordWrap(True)
        run_mode_tip.setStyleSheet('color: #d97706;')
        env_form.addRow(self._field_label('', env_card), run_mode_tip)

        self.shortcut_path = LineEdit(env_card)
        self.shortcut_path.setPlaceholderText('请选择快捷方式')
        shortcut_row = QWidget(env_card)
        shortcut_layout = QHBoxLayout(shortcut_row)
        shortcut_layout.setContentsMargins(0, 0, 0, 0)
        shortcut_layout.setSpacing(8)
        shortcut_layout.addWidget(self.shortcut_path, 1)
        self.shortcut_browse_btn = PushButton('选择', shortcut_row)
        shortcut_btn_width = max(72, self.shortcut_browse_btn.sizeHint().width() + 8)
        self.shortcut_browse_btn.setFixedWidth(shortcut_btn_width)
        shortcut_layout.addWidget(self.shortcut_browse_btn)
        env_form.addRow(self._field_label('快捷方式', env_card), shortcut_row)
        shortcut_tip = CaptionLabel('在小程序窗口上方的菜单中选择添加到桌面，然后在此处选择。', env_card)
        shortcut_tip.setWordWrap(True)
        shortcut_tip.setStyleSheet('color: #d97706;')
        env_form.addRow(self._field_label('', env_card), shortcut_tip)

        self.shortcut_launch_delay = SpinBox(env_card)
        self.shortcut_launch_delay.setRange(0, 30)
        self.shortcut_launch_delay.setSingleStep(1)
        self.shortcut_launch_delay.setSuffix(' 秒')
        env_form.addRow(self._field_label('启动延迟', env_card), self.shortcut_launch_delay)
        shortcut_launch_delay_tip = CaptionLabel(
            '快捷方式启动后到调整窗口的等待时间，避免加载阶段与窗口调整冲突。',
            env_card,
        )
        shortcut_launch_delay_tip.setWordWrap(True)
        shortcut_launch_delay_tip.setStyleSheet('color: #d97706;')
        env_form.addRow(self._field_label('', env_card), shortcut_launch_delay_tip)

        self.window_restart_delay = SpinBox(env_card)
        self.window_restart_delay.setRange(0, 300)
        self.window_restart_delay.setSingleStep(1)
        self.window_restart_delay.setSuffix(' 秒')
        env_form.addRow(self._field_label('重启等待', env_card), self.window_restart_delay)
        window_restart_delay_tip = CaptionLabel(
            '定时重启与异常恢复重启时，关闭窗口后到重新拉起前的等待时间。',
            env_card,
        )
        window_restart_delay_tip.setWordWrap(True)
        window_restart_delay_tip.setStyleSheet('color: #d97706;')
        env_form.addRow(self._field_label('', env_card), window_restart_delay_tip)

        self.keyword = LineEdit(env_card)
        self.keyword.setPlaceholderText('窗口标题关键字')
        env_form.addRow(self._field_label('窗口关键词', env_card), self.keyword)

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
        env_form.addRow(self._field_label('选择窗口', env_card), select_row)

        self.window_screen = ComboBox(env_card)
        self.window_position = ComboBox(env_card)
        self.window_position.addItem('左中', userData=WindowPosition.LEFT_CENTER.value)
        self.window_position.addItem('居中', userData=WindowPosition.CENTER.value)
        self.window_position.addItem('右中', userData=WindowPosition.RIGHT_CENTER.value)
        self.window_position.addItem('左上', userData=WindowPosition.TOP_LEFT.value)
        self.window_position.addItem('右上', userData=WindowPosition.TOP_RIGHT.value)
        self.window_position.addItem('左下', userData=WindowPosition.LEFT_BOTTOM.value)
        self.window_position.addItem('右下', userData=WindowPosition.RIGHT_BOTTOM.value)
        window_pos_row = QWidget(env_card)
        window_pos_layout = QHBoxLayout(window_pos_row)
        window_pos_layout.setContentsMargins(0, 0, 0, 0)
        window_pos_layout.setSpacing(8)
        window_pos_layout.addWidget(CaptionLabel('屏幕', window_pos_row))
        window_pos_layout.addWidget(self.window_screen, 1)
        window_pos_layout.addWidget(CaptionLabel('位置', window_pos_row))
        window_pos_layout.addWidget(self.window_position, 1)
        env_form.addRow(self._field_label('窗口位置', env_card), window_pos_row)
        window_position_tip = CaptionLabel(
            '小程序窗口限制，只建议主屏幕和目标屏幕缩放相同时指定屏幕。',
            env_card,
        )
        window_position_tip.setWordWrap(True)
        window_position_tip.setStyleSheet('color: #d97706;')
        env_form.addRow(self._field_label('', env_card), window_position_tip)

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
        advanced_form.addRow(self._field_label('随机延迟', advanced_card), delay_row)

        self.offset = SpinBox(advanced_card)
        self.offset.setRange(0, 50)
        advanced_form.addRow(self._field_label('点击抖动', advanced_card), self.offset)

        self.max_actions = SpinBox(advanced_card)
        self.max_actions.setRange(1, 500)
        advanced_form.addRow(self._field_label('单轮点击上限', advanced_card), self.max_actions)

        self.capture_interval = DoubleSpinBox(advanced_card)
        self.capture_interval.setRange(0.0, 5.0)
        self.capture_interval.setDecimals(2)
        self.capture_interval.setSingleStep(0.05)
        self.capture_interval.setSuffix(' 秒')
        advanced_form.addRow(self._field_label('截图间隔', advanced_card), self.capture_interval)
        capture_interval_hint = CaptionLabel('限制连续截图频率（0 表示不限制，默认 0.3 秒）。', advanced_card)
        capture_interval_hint.setStyleSheet('color: #d97706;')
        advanced_form.addRow('', capture_interval_hint)

        self.planting_stable = DoubleSpinBox(advanced_card)
        self.planting_stable.setRange(0.1, 5.0)
        self.planting_stable.setDecimals(1)
        self.planting_stable.setSingleStep(0.1)
        self.planting_stable.setSuffix(' 秒')
        advanced_form.addRow(self._field_label('播种稳定时间', advanced_card), self.planting_stable)
        planting_stable_hint = CaptionLabel('如果在边缘地块无法正常播种，请适当增加这个值', advanced_card)
        planting_stable_hint.setStyleSheet('color: #d97706;')
        advanced_form.addRow('', planting_stable_hint)
        self.planting_stable_timeout = DoubleSpinBox(advanced_card)
        self.planting_stable_timeout.setRange(0.5, 30.0)
        self.planting_stable_timeout.setDecimals(1)
        self.planting_stable_timeout.setSingleStep(0.5)
        self.planting_stable_timeout.setSuffix(' 秒')
        advanced_form.addRow(self._field_label('播种稳定超时', advanced_card), self.planting_stable_timeout)
        planting_stable_timeout_hint = CaptionLabel(
            '如果提示背景树锚点稳定等待超时，请适当增加这个值',
            advanced_card,
        )
        planting_stable_timeout_hint.setStyleSheet('color: #d97706;')
        advanced_form.addRow('', planting_stable_timeout_hint)

        self.debug = CheckBox('启用 Debug 日志', advanced_card)
        advanced_form.addRow(self._field_label('调试日志', advanced_card), self.debug)
        self.logs_path_label = CaptionLabel('', advanced_card)
        self.logs_path_label.setWordWrap(True)
        self.logs_path_label.setStyleSheet('color: #64748b;')
        advanced_form.addRow(self._field_label('日志路径', advanced_card), self.logs_path_label)

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
            self.shortcut_launch_delay.valueChanged,
            self.window_restart_delay.valueChanged,
            self.window_select.currentIndexChanged,
            self.window_screen.currentIndexChanged,
            self.window_position.currentIndexChanged,
            self.delay_min.valueChanged,
            self.delay_max.valueChanged,
            self.offset.valueChanged,
            self.max_actions.valueChanged,
            self.capture_interval.valueChanged,
            self.planting_stable.valueChanged,
            self.planting_stable_timeout.valueChanged,
            self.debug.toggled,
        ):
            sig.connect(self._save)
        self.level.valueChanged.connect(self._on_level_changed)
        self.strategy.currentIndexChanged.connect(self._on_strategy_changed)
        self.shortcut_path.editingFinished.connect(self._save)
        self.shortcut_browse_btn.clicked.connect(self._choose_shortcut_path)
        self.keyword.editingFinished.connect(self._on_keyword_committed)
        self.refresh_btn.clicked.connect(self._refresh_windows)

    @staticmethod
    def _apply_card_style(card: StableElevatedCardWidget, object_name: str) -> None:
        card.setObjectName(object_name)
        card.setStyleSheet(
            f'ElevatedCardWidget#{object_name} {{'
            ' border-radius: 10px;'
            ' border: 1px solid rgba(100, 116, 139, 0.22);'
            ' }'
            f'ElevatedCardWidget#{object_name}:hover {{'
            ' background-color: rgba(37, 99, 235, 0.06);'
            ' border: 1px solid rgba(59, 130, 246, 0.32);'
            ' }'
        )

    @staticmethod
    def _style_form(form: QFormLayout) -> None:
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setHorizontalSpacing(0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def _field_label(text: str, parent: QWidget) -> CaptionLabel:
        text_value = str(text or '').strip()
        label = CaptionLabel(f'{text_value}:' if text_value else '', parent)
        if text_value:
            label.setFixedWidth(label.sizeHint().width() + label.fontMetrics().horizontalAdvance('字'))
            label.setStyleSheet('color: #475569; font-weight: 600;')
        return label

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
        card_layout.setSpacing(9)
        title_label = BodyLabel(title)
        title_label.setStyleSheet('font-weight: 700; font-size: 14px; color: #1e293b;')
        card_layout.addWidget(title_label)
        divider = QFrame(card)
        divider.setObjectName('settingsCardTitleDivider')
        divider.setFixedHeight(1)
        divider.setStyleSheet(
            'QFrame#settingsCardTitleDivider { background-color: rgba(37, 99, 235, 0.10); border: none; }'
        )
        card_layout.addWidget(divider)
        form = QFormLayout()
        self._style_form(form)
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

    def _refresh_displays(self) -> None:
        current = int(self.window_screen.currentData() or self.config.planting.window_screen_index or 0)
        self.window_screen.blockSignals(True)
        self.window_screen.clear()
        displays = self._wm.list_displays()
        primary_index = 1
        for info in displays:
            if bool(info.is_primary):
                primary_index = int(info.index)
            self.window_screen.addItem(self._format_display_option_label(info), userData=int(info.index))
        if self.window_screen.count() <= 0:
            self.window_screen.addItem('#1 0x0 100%', userData=1)
        target = int(primary_index if current <= 0 else current)
        self._set_combo_data(self.window_screen, target)
        if self.window_screen.currentIndex() < 0 and self.window_screen.count() > 0:
            self.window_screen.setCurrentIndex(0)
        self.window_screen.blockSignals(False)

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

    @staticmethod
    def _format_display_option_label(info: DisplayInfo) -> str:
        primary_text = ' 主屏' if bool(info.is_primary) else ''
        return f'#{int(info.index)} {int(info.width)}x{int(info.height)} {int(info.scale_percent)}%{primary_text}'

    def _on_keyword_committed(self) -> None:
        self._refresh_windows()
        self._save()

    def _choose_shortcut_path(self) -> None:
        raw_path = str(self.shortcut_path.text() or '').strip()
        start_dir = ''
        if raw_path:
            try:
                path = Path(raw_path)
                if path.is_file():
                    start_dir = str(path.parent)
                elif path.parent.exists():
                    start_dir = str(path.parent)
            except Exception:
                start_dir = ''
        if not start_dir:
            desktop = Path.home() / 'Desktop'
            start_dir = str(desktop if desktop.exists() else Path.home())
        selected, _ = QFileDialog.getOpenFileName(
            self,
            '选择快捷方式',
            start_dir,
            '快捷方式 (*.lnk)',
        )
        if not selected:
            return
        self.shortcut_path.setText(str(Path(selected)))
        self._save()

    def _resolve_logs_path_text(self) -> str:
        config_path = str(self.config._config_path or '').strip()
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
        self.shortcut_path.setText(str(c.window_shortcut_path or ''))
        self.shortcut_launch_delay.setValue(int(c.window_shortcut_launch_delay_seconds))
        self.window_restart_delay.setValue(int(c.window_restart_delay_seconds))
        self.keyword.setText(str(c.window_title_keyword or ''))
        self._refresh_displays()
        self._set_combo_data(self.window_screen, int(c.planting.window_screen_index))
        self._set_combo_data(self.window_position, c.planting.window_position.value)
        self.delay_min.setValue(float(c.safety.random_delay_min))
        self.delay_max.setValue(float(c.safety.random_delay_max))
        self.offset.setValue(int(c.safety.click_offset_range))
        self.max_actions.setValue(int(c.safety.max_actions_per_round))
        self.capture_interval.setValue(float(c.screenshot.capture_interval_seconds))
        self.planting_stable.setValue(float(c.planting.planting_stable_seconds))
        self.planting_stable_timeout.setValue(float(c.planting.planting_stable_timeout_seconds))
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
        c.window_shortcut_path = str(self.shortcut_path.text() or '').strip()
        c.window_shortcut_launch_delay_seconds = int(self.shortcut_launch_delay.value())
        c.window_restart_delay_seconds = int(self.window_restart_delay.value())
        c.window_title_keyword = str(self.keyword.text() or '').strip()
        c.window_select_rule = str(self.window_select.currentData() or 'auto')
        c.planting.window_screen_index = int(self.window_screen.currentData() or 0)
        c.planting.window_position = WindowPosition(
            str(self.window_position.currentData() or WindowPosition.LEFT_CENTER.value)
        )
        d_min, d_max = float(self.delay_min.value()), float(self.delay_max.value())
        c.safety.random_delay_min = min(d_min, d_max)
        c.safety.random_delay_max = max(d_min, d_max)
        c.safety.click_offset_range = int(self.offset.value())
        c.safety.max_actions_per_round = int(self.max_actions.value())
        c.screenshot.capture_interval_seconds = float(self.capture_interval.value())
        c.planting.planting_stable_seconds = float(self.planting_stable.value())
        c.planting.planting_stable_timeout_seconds = float(self.planting_stable_timeout.value())
        c.safety.debug_log_enabled = bool(self.debug.isChecked())
        c.save()
        self.config_changed.emit(c)

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._loading = True
        self._load()
        self._loading = False
