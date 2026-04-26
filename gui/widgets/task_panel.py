"""Fluent 任务调度配置面板。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PyQt6.QtCore import QDateTime, Qt, QTime, pyqtSignal
from PyQt6.QtWidgets import (
    QDateTimeEdit,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DateTimeEdit,
    ScrollArea,
    SpinBox,
    TimeEdit,
)

from gui.widgets.fluent_container import StableElevatedCardWidget, TransparentCardContainer
from models.config import (
    DEFAULT_TASK_ENABLED_TIME_RANGE,
    DEFAULT_TASK_NEXT_RUN,
    AppConfig,
    TaskTriggerType,
    normalize_task_enabled_time_range,
    parse_executor_task_order,
)
from utils.app_paths import load_config_json_object


class TaskPanel(QWidget):
    """任务调度配置面板。"""

    config_changed = pyqtSignal(object)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        labels = load_config_json_object('ui_labels.json', prefer_user=False).get('task_panel', {})
        self._task_title_map = labels.get('task_titles', {})
        self._task_order: list[str] = []
        self._task_widgets: dict[str, dict[str, Any]] = {}
        self._loading = True
        self._build_ui()
        self._load_config()
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
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 8, 10, 8)
        content_layout.setSpacing(10)

        waterfall = QHBoxLayout()
        waterfall.setContentsMargins(0, 0, 0, 0)
        waterfall.setSpacing(10)
        left_col = QVBoxLayout()
        right_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        right_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(10)
        right_col.setSpacing(10)
        waterfall.addLayout(left_col, 1)
        waterfall.addLayout(right_col, 1)
        columns = [left_col, right_col]
        col_heights = [0, 0]
        self._task_order = self._resolve_task_order()

        for task_name in self._task_order:
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            card = self._build_task_card(task_name, task_cfg.trigger)
            target = 0 if col_heights[0] <= col_heights[1] else 1
            columns[target].addWidget(card)
            col_heights[target] += max(1, int(card.sizeHint().height()))

        for col in columns:
            col.addStretch()
        content_layout.addLayout(waterfall)
        content_layout.addStretch()

    def _resolve_task_order(self) -> list[str]:
        task_names = [str(name) for name in self.config.tasks.keys()]

        known = set(task_names)
        out: list[str] = []
        seen: set[str] = set()
        for name in parse_executor_task_order(self.config.executor.task_order):
            task_name = str(name)
            if not task_name or task_name in seen or task_name not in known:
                continue
            seen.add(task_name)
            out.append(task_name)
        for name in task_names:
            task_name = str(name)
            if not task_name or task_name in seen:
                continue
            seen.add(task_name)
            out.append(task_name)
        return out

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
        if text_value:
            label.setStyleSheet('color: #475569; font-weight: 600;')
        return label

    @staticmethod
    def _add_card_title(layout: QVBoxLayout, title_text: str) -> None:
        title = BodyLabel(str(title_text))
        title.setStyleSheet('font-weight: 700; font-size: 14px; color: #1e293b;')
        layout.addWidget(title)
        divider = QFrame()
        divider.setObjectName('taskCardTitleDivider')
        divider.setFixedHeight(1)
        divider.setStyleSheet(
            'QFrame#taskCardTitleDivider { background-color: rgba(37, 99, 235, 0.10); border: none; }'
        )
        layout.addWidget(divider)

    def _build_task_card(self, task_name: str, trigger: TaskTriggerType) -> StableElevatedCardWidget:
        card = StableElevatedCardWidget(self)
        self._apply_card_style(card, 'taskConfigCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)
        self._add_card_title(layout, str(self._task_title_map.get(task_name, task_name)))

        form = QFormLayout()
        self._style_form(form)
        widgets: dict[str, Any] = {}

        enabled = CheckBox('启用')
        enabled.toggled.connect(self._auto_save)
        form.addRow(self._field_label('开关', card), enabled)
        widgets['enabled'] = enabled

        if trigger == TaskTriggerType.DAILY:
            time_edit = TimeEdit(card)
            time_edit.setDisplayFormat('HH:mm')
            time_edit.timeChanged.connect(self._auto_save)
            form.addRow(self._field_label('每日时间', card), time_edit)
            widgets['daily_time'] = time_edit
        else:
            interval_value = SpinBox(card)
            interval_value.setRange(1, 999999)
            interval_value.setValue(60)
            interval_value.valueChanged.connect(self._auto_save)
            interval_unit = ComboBox(card)
            interval_unit.addItem('秒', userData=1)
            interval_unit.addItem('分钟', userData=60)
            interval_unit.addItem('小时', userData=3600)
            interval_unit.currentIndexChanged.connect(self._auto_save)
            row = QWidget(card)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(interval_value, 1)
            row_layout.addWidget(interval_unit)
            form.addRow(self._field_label('执行间隔', card), row)
            widgets['interval_value'] = interval_value
            widgets['interval_unit'] = interval_unit

            start = TimeEdit(card)
            start.setDisplayFormat('HH:mm:ss')
            start.setSymbolVisible(False)
            start.setMinimumWidth(0)
            start.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            start.timeChanged.connect(self._auto_save)
            end = TimeEdit(card)
            end.setDisplayFormat('HH:mm:ss')
            end.setSymbolVisible(False)
            end.setMinimumWidth(0)
            end.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            end.timeChanged.connect(self._auto_save)
            range_row = QWidget(card)
            range_layout = QHBoxLayout(range_row)
            range_layout.setContentsMargins(0, 0, 0, 0)
            range_layout.setSpacing(8)
            range_layout.addWidget(start, 1)
            range_layout.addWidget(BodyLabel('~'))
            range_layout.addWidget(end, 1)
            form.addRow(self._field_label('启用时段', card), range_row)
            widgets['enabled_time_start'] = start
            widgets['enabled_time_end'] = end

        next_run = DateTimeEdit(card)
        next_run.setSymbolVisible(False)
        next_run.setMinimumWidth(0)
        next_run.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        next_run.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
        next_run.dateTimeChanged.connect(self._auto_save)
        form.addRow(self._field_label('下次执行', card), next_run)
        widgets['next_run'] = next_run

        layout.addLayout(form)
        self._task_widgets[task_name] = widgets
        return card

    @staticmethod
    def _split_interval(seconds: int) -> tuple[int, int]:
        value = max(1, int(seconds))
        if value % 3600 == 0:
            return value // 3600, 3600
        if value % 60 == 0:
            return value // 60, 60
        return value, 1

    @staticmethod
    def _normalize_next_run(text: str) -> str | None:
        raw = str(text or '').strip().replace('T', ' ')
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                return datetime.strptime(raw, fmt).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                continue
        return None

    @staticmethod
    def _parse_enabled_time_range(text: str) -> tuple[str, str]:
        normalized = normalize_task_enabled_time_range(text or DEFAULT_TASK_ENABLED_TIME_RANGE)
        try:
            start, end = normalized.split('-', 1)
            return start, end
        except Exception:
            return '00:00:00', '23:59:59'

    @classmethod
    def _parse_next_run_datetime(cls, text: str) -> QDateTime:
        normalized = cls._normalize_next_run(text)
        if normalized is None:
            normalized = cls._normalize_next_run(DEFAULT_TASK_NEXT_RUN) or '2026-01-01 00:00:00'
        qdt = QDateTime.fromString(normalized, 'yyyy-MM-dd HH:mm:ss')
        if not qdt.isValid():
            qdt = QDateTime.fromString('2026-01-01 00:00:00', 'yyyy-MM-dd HH:mm:ss')
        return qdt

    @staticmethod
    def _set_combo_data(combo: ComboBox, value) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _load_config(self) -> None:
        c = self.config
        for task_name in self._task_order:
            task_cfg = c.tasks.get(task_name)
            if task_cfg is None:
                continue
            widgets = self._task_widgets.get(task_name, {})
            enabled = widgets.get('enabled')
            if isinstance(enabled, CheckBox):
                enabled.setChecked(bool(task_cfg.enabled))

            if 'interval_value' in widgets and 'interval_unit' in widgets:
                interval_value = widgets['interval_value']
                interval_unit = widgets['interval_unit']
                if isinstance(interval_value, SpinBox) and isinstance(interval_unit, ComboBox):
                    value, unit = self._split_interval(
                        max(int(self.config.executor.min_task_interval_seconds), task_cfg.interval_seconds)
                    )
                    interval_value.setValue(value)
                    self._set_combo_data(interval_unit, unit)
                start, end = self._parse_enabled_time_range(task_cfg.enabled_time_range)
                start_edit = widgets.get('enabled_time_start')
                end_edit = widgets.get('enabled_time_end')
                if isinstance(start_edit, TimeEdit) and isinstance(end_edit, TimeEdit):
                    start_time = QTime.fromString(start, 'HH:mm:ss')
                    end_time = QTime.fromString(end, 'HH:mm:ss')
                    if not start_time.isValid():
                        start_time = QTime(0, 0, 0)
                    if not end_time.isValid():
                        end_time = QTime(23, 59, 59)
                    start_edit.setTime(start_time)
                    end_edit.setTime(end_time)
            else:
                time_edit = widgets.get('daily_time')
                if isinstance(time_edit, TimeEdit):
                    try:
                        hh, mm = str(task_cfg.daily_time).split(':')
                        time_edit.setTime(QTime(int(hh), int(mm)))
                    except Exception:
                        time_edit.setTime(QTime(0, 1))

            next_run = widgets.get('next_run')
            if isinstance(next_run, QDateTimeEdit):
                next_run.setDateTime(self._parse_next_run_datetime(task_cfg.next_run))

    def _auto_save(self) -> None:
        if self._loading:
            return
        c = self.config

        for task_name in self._task_order:
            task_cfg = c.tasks.get(task_name)
            if task_cfg is None:
                continue
            widgets = self._task_widgets.get(task_name, {})
            enabled = widgets.get('enabled')
            if isinstance(enabled, CheckBox):
                task_cfg.enabled = bool(enabled.isChecked())

            if 'interval_value' in widgets and 'interval_unit' in widgets:
                value = int(widgets['interval_value'].value())
                factor = int(widgets['interval_unit'].currentData() or 1)
                task_cfg.trigger = TaskTriggerType.INTERVAL
                task_cfg.interval_seconds = max(
                    int(self.config.executor.min_task_interval_seconds),
                    value * max(1, factor),
                )
                start_edit = widgets.get('enabled_time_start')
                end_edit = widgets.get('enabled_time_end')
                start = '00:00:00'
                end = '23:59:59'
                if isinstance(start_edit, TimeEdit) and isinstance(end_edit, TimeEdit):
                    start = start_edit.time().toString('HH:mm:ss')
                    end = end_edit.time().toString('HH:mm:ss')
                task_cfg.enabled_time_range = normalize_task_enabled_time_range(f'{start}-{end}')
            else:
                daily_time = widgets.get('daily_time')
                if isinstance(daily_time, TimeEdit):
                    task_cfg.trigger = TaskTriggerType.DAILY
                    task_cfg.daily_time = daily_time.time().toString('HH:mm')

            next_run = widgets.get('next_run')
            if isinstance(next_run, QDateTimeEdit):
                qdt = next_run.dateTime()
                if qdt.isValid():
                    task_cfg.next_run = qdt.toString('yyyy-MM-dd HH:mm:ss')

        c.save()
        self.config_changed.emit(c)

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._loading = True
        self._task_order = self._resolve_task_order()
        self._load_config()
        self._loading = False
