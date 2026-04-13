"""任务配置面板（根据 tasks 配置自动生成）。"""

from datetime import datetime

from PyQt6.QtCore import Qt, QTime, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.no_wheel_combo_box import NoWheelComboBox
from models.config import (
    DEFAULT_TASK_ENABLED_TIME_RANGE,
    DEFAULT_TASK_NEXT_RUN,
    AppConfig,
    TaskTriggerType,
    normalize_task_enabled_time_range,
    resolve_task_min_interval_seconds,
)
from utils.app_paths import load_config_json_object


class TaskPanel(QWidget):
    """任务调度配置面板。


    - 根据 `tasks` 配置动态生成任务调度表单。
    - 维护执行器策略（空队列策略、最大连续失败）。
    - 用户修改后自动写回 `config.json` 并发出 `config_changed` 信号。
    """

    config_changed = pyqtSignal(object)

    def __init__(self, config: AppConfig, parent=None):
        """初始化任务调度面板并加载配置。"""
        super().__init__(parent)
        self.config = config
        panel_labels = load_config_json_object('ui_labels.json', prefer_user=False).get('task_panel', {})
        self._task_title_map = panel_labels.get('task_titles', {})
        task_hints = panel_labels.get('task_hints', {})
        self._task_hint_map = task_hints if isinstance(task_hints, dict) else {}
        self._switch_label = str(panel_labels.get('switch_label', 'Switch:'))
        self._enabled_text = str(panel_labels.get('enabled', 'Enable'))
        self._daily_time_label = str(panel_labels.get('daily_time_label', 'Daily time:'))
        self._enabled_time_range_label = str(panel_labels.get('enabled_time_range_label', '启用时间段:'))
        self._time_range_separator = str(panel_labels.get('time_range_separator', '~'))
        self._next_run_label = str(panel_labels.get('next_run_label', 'Next run:'))
        self._interval_label = str(panel_labels.get('interval_label', 'Interval:'))
        self._interval_unit_second = str(panel_labels.get('interval_unit_second', '秒'))
        self._interval_unit_minute = str(panel_labels.get('interval_unit_minute', '分钟'))
        self._interval_unit_hour = str(panel_labels.get('interval_unit_hour', '小时'))
        self._executor_group_title = str(panel_labels.get('executor_group_title', 'Executor'))
        self._policy_label = str(panel_labels.get('policy_label', 'Empty queue policy:'))
        self._policy_stay = str(panel_labels.get('policy_stay', 'Stay'))
        self._policy_goto_main = str(panel_labels.get('policy_goto_main', 'Goto main'))
        self._max_failures_label = str(panel_labels.get('max_failures_label', 'Max failures:'))
        self._task_title_suffix = str(panel_labels.get('task_title_suffix', ' task'))
        self._loading = True
        self._task_order: list[str] = []
        self._task_widgets: dict[str, dict[str, object]] = {}
        self._cards: list[QGroupBox] = []
        self._init_ui()
        self._load_config()
        self._connect_auto_save()
        self._loading = False

    def _init_ui(self):
        """构建面板主布局并按任务配置生成卡片。

        规则：
        - 每个任务一张卡片（自动识别 interval/daily）。
        - 额外附加一张“执行器”卡片。
        - 卡片按两列排布并做同一行高度对齐。
        """
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        scroll.viewport().setAutoFillBackground(False)
        root.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet('background: transparent;')
        scroll.setWidget(content)

        grid = QGridLayout(content)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(10)

        self._task_order = [str(name) for name in getattr(self.config, 'tasks', {}).keys()]
        for task_name in self._task_order:
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            card = self._build_task_group(task_name, task_cfg.trigger)
            self._cards.append(card)

        policy_group = self._build_executor_group()
        self._cards.append(policy_group)

        for idx, card in enumerate(self._cards):
            row = idx // 2
            col = idx % 2
            grid.addWidget(card, row, col)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch((len(self._cards) + 1) // 2, 1)
        self._align_cards_in_rows()

    def _build_task_group(self, task_name: str, trigger: TaskTriggerType) -> QGroupBox:
        """构建单个任务的配置卡片。


        - 固定提供任务开关。
        - `INTERVAL` 任务显示“执行间隔（秒/分钟/小时）”。
        - `DAILY` 任务显示“每日执行时间 + 下次执行”。
        """
        title = self._task_title_map.get(task_name, f'{task_name}{self._task_title_suffix}')
        group = QGroupBox(title)
        group.setStyleSheet('QGroupBox { font-weight: bold; color: #475569; }')
        form = QFormLayout()
        form.setContentsMargins(10, 15, 10, 10)
        form.setSpacing(10)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        enabled = QCheckBox(self._enabled_text)
        widgets: dict[str, object] = {'enabled': enabled}
        hint_text = str(self._task_hint_map.get(task_name, '') or '').strip()
        if hint_text:
            switch_row = QWidget()
            switch_layout = QHBoxLayout(switch_row)
            switch_layout.setContentsMargins(0, 0, 0, 0)
            switch_layout.setSpacing(8)
            switch_layout.addWidget(enabled)
            hint_label = QLabel(hint_text)
            hint_label.setWordWrap(True)
            hint_label.setStyleSheet('color: #dc2626; font-size: 12px;')
            switch_layout.addWidget(hint_label, 1)
            form.addRow(self._switch_label, switch_row)
        else:
            form.addRow(self._switch_label, enabled)

        if trigger == TaskTriggerType.DAILY:
            time_edit = QTimeEdit()
            time_edit.setDisplayFormat('HH:mm')
            time_edit.setFixedWidth(96)
            time_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            time_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            time_edit.setStyleSheet(
                'QTimeEdit {'
                'background-color: #ffffff;'
                'border: 1px solid #cbd5e1;'
                'border-radius: 6px;'
                'padding: 4px 8px;'
                'font-weight: 600;'
                '}'
                'QTimeEdit:focus { border-color: #2563eb; }'
            )
            next_run = QLineEdit()
            # 固定模板输入，支持逐位编辑，不需要先全选。
            next_run.setInputMask('0000-00-00 00:00:00;_')
            next_run.setAlignment(Qt.AlignmentFlag.AlignCenter)
            next_run.setStyleSheet(
                'QLineEdit {'
                'background-color: #ffffff;'
                'border: 1px solid #cbd5e1;'
                'border-radius: 6px;'
                'padding: 4px 8px;'
                'font-weight: 600;'
                '}'
                'QLineEdit:focus { border-color: #2563eb; }'
            )

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(time_edit)
            row_layout.addStretch()

            form.addRow(self._daily_time_label, row_widget)
            form.addRow(self._next_run_label, next_run)
            widgets['daily_time'] = time_edit
            widgets['next_run'] = next_run
        else:
            interval_value = QSpinBox()
            interval_value.setRange(1, 999999)
            interval_value.setFixedWidth(84)
            interval_unit = NoWheelComboBox()
            interval_unit.addItem(self._interval_unit_second, 1)
            interval_unit.addItem(self._interval_unit_minute, 60)
            interval_unit.addItem(self._interval_unit_hour, 3600)
            interval_unit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            metrics = QFontMetrics(interval_unit.font())
            max_unit_text_width = max(
                metrics.horizontalAdvance(self._interval_unit_second),
                metrics.horizontalAdvance(self._interval_unit_minute),
                metrics.horizontalAdvance(self._interval_unit_hour),
            )
            # 额外预留左右内边距与下拉箭头区域，避免文本被省略号截断。
            interval_unit.setFixedWidth(max(80, max_unit_text_width + 43))
            next_run = QLineEdit()
            # 固定模板输入，支持逐位编辑，不需要先全选。
            next_run.setInputMask('0000-00-00 00:00:00;_')
            next_run.setAlignment(Qt.AlignmentFlag.AlignCenter)
            next_run.setStyleSheet(
                'QLineEdit {'
                'background-color: #ffffff;'
                'border: 1px solid #cbd5e1;'
                'border-radius: 6px;'
                'padding: 4px 8px;'
                'font-weight: 600;'
                '}'
                'QLineEdit:focus { border-color: #2563eb; }'
            )

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(interval_value)
            row_layout.addWidget(interval_unit)
            row_layout.addStretch()

            form.addRow(self._interval_label, row_widget)
            start_time = QLineEdit()
            start_time.setInputMask('00:00:00;_')
            time_metrics = QFontMetrics(start_time.font())
            time_input_width = max(75, time_metrics.horizontalAdvance('00:00:00') + 19)
            start_time.setFixedWidth(time_input_width)
            start_time.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            start_time.setStyleSheet(
                'QLineEdit {'
                'background-color: #ffffff;'
                'border: 1px solid #cbd5e1;'
                'border-radius: 6px;'
                'padding: 4px 8px;'
                'font-weight: 600;'
                '}'
                'QLineEdit:focus { border-color: #2563eb; }'
            )
            end_time = QLineEdit()
            end_time.setInputMask('00:00:00;_')
            end_time.setFixedWidth(time_input_width)
            end_time.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            end_time.setStyleSheet(
                'QLineEdit {'
                'background-color: #ffffff;'
                'border: 1px solid #cbd5e1;'
                'border-radius: 6px;'
                'padding: 4px 8px;'
                'font-weight: 600;'
                '}'
                'QLineEdit:focus { border-color: #2563eb; }'
            )
            range_widget = QWidget()
            range_layout = QHBoxLayout(range_widget)
            range_layout.setContentsMargins(0, 0, 0, 0)
            range_layout.setSpacing(8)
            range_layout.addWidget(start_time)
            sep_label = QLabel(self._time_range_separator)
            sep_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sep_label.setFixedWidth(12)
            range_layout.addWidget(sep_label)
            range_layout.addWidget(end_time)
            range_layout.addStretch()
            form.addRow(self._enabled_time_range_label, range_widget)
            form.addRow(self._next_run_label, next_run)
            widgets['interval_value'] = interval_value
            widgets['interval_unit'] = interval_unit
            widgets['enabled_time_start'] = start_time
            widgets['enabled_time_end'] = end_time
            widgets['next_run'] = next_run

        group.setLayout(form)
        self._task_widgets[task_name] = widgets
        return group

    def _build_executor_group(self) -> QGroupBox:
        """构建执行器全局配置卡片。


        - 配置空队列策略（停留/回主界面）。
        - 配置最大连续失败次数（影响失败退避策略）。
        """
        group = QGroupBox(self._executor_group_title)
        group.setStyleSheet('QGroupBox { font-weight: bold; color: #475569; }')
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(10)
        self._empty_policy = NoWheelComboBox()
        self._empty_policy.addItem(self._policy_stay, 'stay')
        self._empty_policy.addItem(self._policy_goto_main, 'goto_main')
        self._max_failures = QSpinBox()
        self._max_failures.setRange(1, 20)
        form.addRow(self._policy_label, self._empty_policy)
        form.addRow(self._max_failures_label, self._max_failures)
        group.setLayout(form)
        return group

    def _align_cards_in_rows(self):
        """统一同一行卡片的最小高度，避免两列错位。"""
        row_heights: dict[int, int] = {}
        for idx, card in enumerate(self._cards):
            row = idx // 2
            row_heights[row] = max(row_heights.get(row, 0), int(card.sizeHint().height()))
        for idx, card in enumerate(self._cards):
            row = idx // 2
            card.setMinimumHeight(row_heights[row])

    def _connect_auto_save(self):
        """绑定所有表单控件的变更事件到自动保存。"""
        for task_name in self._task_order:
            widgets = self._task_widgets.get(task_name, {})
            enabled = widgets.get('enabled')
            if isinstance(enabled, QCheckBox):
                enabled.toggled.connect(self._auto_save)

            interval_value = widgets.get('interval_value')
            if isinstance(interval_value, QSpinBox):
                interval_value.valueChanged.connect(self._auto_save)

            interval_unit = widgets.get('interval_unit')
            if isinstance(interval_unit, QComboBox):
                interval_unit.currentIndexChanged.connect(self._auto_save)

            enabled_time_start = widgets.get('enabled_time_start')
            if isinstance(enabled_time_start, QLineEdit):
                enabled_time_start.editingFinished.connect(
                    lambda name=task_name: self._on_enabled_time_range_edit_finished(name)
                )

            enabled_time_end = widgets.get('enabled_time_end')
            if isinstance(enabled_time_end, QLineEdit):
                enabled_time_end.editingFinished.connect(
                    lambda name=task_name: self._on_enabled_time_range_edit_finished(name)
                )

            daily_time = widgets.get('daily_time')
            if isinstance(daily_time, QTimeEdit):
                daily_time.timeChanged.connect(self._auto_save)

            next_run = widgets.get('next_run')
            if isinstance(next_run, QLineEdit):
                next_run.editingFinished.connect(lambda name=task_name: self._on_next_run_edit_finished(name))

        self._empty_policy.currentIndexChanged.connect(self._auto_save)
        self._max_failures.valueChanged.connect(self._auto_save)

    def _auto_save(self):
        """将当前面板值回写到配置对象并落盘。

        行为：
        - 更新 executor 全局策略。
        - 更新每个任务的 enabled/trigger/interval/enabled_time_range/daily_time/next_run。
        - 保存后发出 `config_changed`，驱动引擎热更新。
        """
        if self._loading:
            return

        c = self.config
        c.executor.empty_queue_policy = str(self._empty_policy.currentData())
        c.executor.max_failures = int(self._max_failures.value())

        for task_name in self._task_order:
            task_cfg = c.tasks.get(task_name)
            if task_cfg is None:
                continue
            widgets = self._task_widgets.get(task_name, {})
            enabled = widgets.get('enabled')
            if isinstance(enabled, QCheckBox):
                task_cfg.enabled = bool(enabled.isChecked())

            interval_value = widgets.get('interval_value')
            interval_unit = widgets.get('interval_unit')
            if isinstance(interval_value, QSpinBox) and isinstance(interval_unit, QComboBox):
                task_cfg.trigger = TaskTriggerType.INTERVAL
                unit_factor = int(interval_unit.currentData() or 1)
                min_interval = self._task_min_interval_seconds()
                task_cfg.interval_seconds = max(
                    min_interval,
                    int(interval_value.value()) * max(1, unit_factor),
                )
                enabled_time_start = widgets.get('enabled_time_start')
                enabled_time_end = widgets.get('enabled_time_end')
                if isinstance(enabled_time_start, QLineEdit) and isinstance(enabled_time_end, QLineEdit):
                    task_cfg.enabled_time_range = self._format_enabled_time_range(
                        enabled_time_start.text(),
                        enabled_time_end.text(),
                    )

            daily_time = widgets.get('daily_time')
            if isinstance(daily_time, QTimeEdit):
                task_cfg.trigger = TaskTriggerType.DAILY
                task_cfg.daily_time = daily_time.time().toString('HH:mm')

            next_run = widgets.get('next_run')
            if isinstance(next_run, QLineEdit):
                normalized = self._normalize_next_run_text(next_run.text())
                if normalized is not None:
                    task_cfg.next_run = normalized
                    if next_run.text() != normalized:
                        next_run.setText(normalized)

        c.save()
        self.config_changed.emit(c)

    def _load_config(self):
        """从配置对象加载初始值到界面控件。"""
        c = self.config

        for task_name in self._task_order:
            task_cfg = c.tasks.get(task_name)
            if task_cfg is None:
                continue
            widgets = self._task_widgets.get(task_name, {})
            enabled = widgets.get('enabled')
            if isinstance(enabled, QCheckBox):
                enabled.setChecked(bool(task_cfg.enabled))

            interval_value = widgets.get('interval_value')
            interval_unit = widgets.get('interval_unit')
            if isinstance(interval_value, QSpinBox) and isinstance(interval_unit, QComboBox):
                seconds = max(self._task_min_interval_seconds(), int(task_cfg.interval_seconds))
                display_value, unit_factor = self._split_interval_for_display(seconds)
                self._set_combo_data(interval_unit, unit_factor)
                interval_value.setValue(display_value)
                enabled_time_start = widgets.get('enabled_time_start')
                enabled_time_end = widgets.get('enabled_time_end')
                if isinstance(enabled_time_start, QLineEdit) and isinstance(enabled_time_end, QLineEdit):
                    start_time, end_time = self._parse_enabled_time_range(
                        str(getattr(task_cfg, 'enabled_time_range', DEFAULT_TASK_ENABLED_TIME_RANGE))
                    )
                    enabled_time_start.setText(start_time)
                    enabled_time_end.setText(end_time)
                next_run = widgets.get('next_run')
                if isinstance(next_run, QLineEdit):
                    normalized = self._normalize_next_run_text(str(getattr(task_cfg, 'next_run', '')))
                    if normalized is None:
                        normalized = self._normalize_next_run_text(DEFAULT_TASK_NEXT_RUN) or '2026-01-01 00:00:00'
                    next_run.setText(normalized)

            daily_time = widgets.get('daily_time')
            if isinstance(daily_time, QTimeEdit):
                try:
                    hh, mm = str(task_cfg.daily_time).split(':')
                    daily_time.setTime(QTime(int(hh), int(mm)))
                except Exception:
                    daily_time.setTime(QTime(0, 1))
                next_run = widgets.get('next_run')
                if isinstance(next_run, QLineEdit):
                    normalized = self._normalize_next_run_text(str(getattr(task_cfg, 'next_run', '')))
                    if normalized is None:
                        normalized = self._normalize_next_run_text(DEFAULT_TASK_NEXT_RUN) or '2026-01-01 00:00:00'
                    next_run.setText(normalized)

        for i in range(self._empty_policy.count()):
            if self._empty_policy.itemData(i) == c.executor.empty_queue_policy:
                self._empty_policy.setCurrentIndex(i)
                break
        self._max_failures.setValue(max(1, int(c.executor.max_failures)))

    def set_config(self, config: AppConfig):
        """替换配置对象并刷新界面。"""
        self.config = config
        self._loading = True
        self._load_config()
        self._loading = False

    def _task_min_interval_seconds(self) -> int:
        """获取当前配置生效的任务最小执行间隔（秒）。"""
        return resolve_task_min_interval_seconds(self.config.executor)

    def _split_interval_for_display(self, seconds: int) -> tuple[int, int]:
        """将秒数拆分为界面可读的值与单位。"""
        value = max(self._task_min_interval_seconds(), int(seconds))
        if value % 3600 == 0:
            return value // 3600, 3600
        if value % 60 == 0:
            return value // 60, 60
        return value, 1

    @staticmethod
    def _set_combo_data(combo: QComboBox, data: int):
        """按 itemData 选中下拉项。"""
        target = int(data)
        for idx in range(combo.count()):
            if int(combo.itemData(idx) or 0) == target:
                combo.setCurrentIndex(idx)
                return

    @staticmethod
    def _normalize_next_run_text(text: str) -> str | None:
        """将 `next_run` 文本规范化为 `YYYY-MM-DD HH:MM:SS`。"""
        raw = str(text or '').strip().replace('T', ' ')
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                parsed = datetime.strptime(raw, fmt)
                return parsed.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                continue
        return None

    @staticmethod
    def _format_enabled_time_range(start_text: str, end_text: str) -> str:
        """格式化启用时间段文本。"""
        return normalize_task_enabled_time_range(f'{start_text}-{end_text}')

    @staticmethod
    def _parse_enabled_time_range(text: str) -> tuple[str, str]:
        """解析启用时间段文本。"""
        normalized = normalize_task_enabled_time_range(text or DEFAULT_TASK_ENABLED_TIME_RANGE)
        try:
            start_text, end_text = normalized.split('-', 1)
            return start_text, end_text
        except Exception:
            return '00:00:00', '23:59:59'

    @staticmethod
    def _normalize_time_only_text(text: str) -> str | None:
        """将 `HH:MM:SS` 文本规范化。"""
        raw = str(text or '').strip()
        try:
            parsed = datetime.strptime(raw, '%H:%M:%S')
            return parsed.strftime('%H:%M:%S')
        except Exception:
            return None

    def _on_next_run_edit_finished(self, task_name: str):
        """校验并规范化任务的 `next_run` 输入。"""
        widgets = self._task_widgets.get(task_name, {})
        next_run = widgets.get('next_run')
        if not isinstance(next_run, QLineEdit):
            return
        normalized = self._normalize_next_run_text(next_run.text())
        if normalized is None:
            cfg = self.config.tasks.get(task_name)
            normalized = self._normalize_next_run_text(str(getattr(cfg, 'next_run', '')))
            if normalized is None:
                normalized = self._normalize_next_run_text(DEFAULT_TASK_NEXT_RUN) or '2026-01-01 00:00:00'
        if next_run.text() != normalized:
            next_run.setText(normalized)
        self._auto_save()

    def _on_enabled_time_range_edit_finished(self, task_name: str):
        """校验并规范化任务启用时间段输入。"""
        widgets = self._task_widgets.get(task_name, {})
        start_edit = widgets.get('enabled_time_start')
        end_edit = widgets.get('enabled_time_end')
        if not isinstance(start_edit, QLineEdit) or not isinstance(end_edit, QLineEdit):
            return

        start_text = self._normalize_time_only_text(start_edit.text())
        end_text = self._normalize_time_only_text(end_edit.text())

        cfg = self.config.tasks.get(task_name)
        fallback = str(getattr(cfg, 'enabled_time_range', DEFAULT_TASK_ENABLED_TIME_RANGE))
        fallback_start, fallback_end = self._parse_enabled_time_range(fallback)
        if start_text is None:
            start_text = fallback_start
        if end_text is None:
            end_text = fallback_end

        normalized = self._format_enabled_time_range(start_text, end_text)
        normalized_start, normalized_end = self._parse_enabled_time_range(normalized)

        if start_edit.text() != normalized_start:
            start_edit.setText(normalized_start)
        if end_edit.text() != normalized_end:
            end_edit.setText(normalized_end)
        self._auto_save()
