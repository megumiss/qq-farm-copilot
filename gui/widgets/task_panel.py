"""Fluent 任务调度配置面板。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PyQt6.QtCore import QTime, pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    CompactSpinBox,
    LineEdit,
    ScrollArea,
    SpinBox,
    TimeEdit,
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
    """任务 + 执行器策略配置。"""

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

        content = QWidget(self)
        scroll.setWidget(content)
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
        self._task_order = [str(name) for name in getattr(self.config, 'tasks', {}).keys()]

        for task_name in self._task_order:
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            card = self._build_task_card(task_name, task_cfg.trigger)
            target = 0 if col_heights[0] <= col_heights[1] else 1
            columns[target].addWidget(card)
            col_heights[target] += max(1, int(card.sizeHint().height()))

        exec_card = self._build_executor_card()
        target = 0 if col_heights[0] <= col_heights[1] else 1
        columns[target].addWidget(exec_card)
        for col in columns:
            col.addStretch()

        content_layout.addLayout(waterfall)
        content_layout.addStretch()

    def _build_task_card(self, task_name: str, trigger: TaskTriggerType) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(BodyLabel(str(self._task_title_map.get(task_name, task_name))))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        widgets: dict[str, Any] = {}

        enabled = CheckBox('启用')
        enabled.toggled.connect(self._auto_save)
        form.addRow('开关:', enabled)
        widgets['enabled'] = enabled

        if trigger == TaskTriggerType.DAILY:
            time_edit = TimeEdit(card)
            time_edit.setDisplayFormat('HH:mm')
            time_edit.timeChanged.connect(self._auto_save)
            form.addRow('每日时间:', time_edit)
            widgets['daily_time'] = time_edit
        else:
            interval_value = SpinBox(card)
            interval_value.setRange(1, 999999)
            interval_value.setValue(60)
            interval_value.valueChanged.connect(self._auto_save)
            interval_unit = NoWheelComboBox(card)
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
            form.addRow('执行间隔:', row)
            widgets['interval_value'] = interval_value
            widgets['interval_unit'] = interval_unit

            start = LineEdit(card)
            start.setInputMask('00:00:00;_')
            start.editingFinished.connect(lambda n=task_name: self._on_time_range_edit_finished(n))
            end = LineEdit(card)
            end.setInputMask('00:00:00;_')
            end.editingFinished.connect(lambda n=task_name: self._on_time_range_edit_finished(n))
            range_row = QWidget(card)
            range_layout = QHBoxLayout(range_row)
            range_layout.setContentsMargins(0, 0, 0, 0)
            range_layout.setSpacing(8)
            range_layout.addWidget(start, 1)
            range_layout.addWidget(BodyLabel('~'))
            range_layout.addWidget(end, 1)
            form.addRow('启用时段:', range_row)
            widgets['enabled_time_start'] = start
            widgets['enabled_time_end'] = end

        next_run = LineEdit(card)
        next_run.setInputMask('0000-00-00 00:00:00;_')
        next_run.editingFinished.connect(lambda n=task_name: self._on_next_run_edit_finished(n))
        form.addRow('下次执行:', next_run)
        widgets['next_run'] = next_run

        layout.addLayout(form)
        self._task_widgets[task_name] = widgets
        return card

    def _build_executor_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(BodyLabel('执行器'))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self._empty_policy = NoWheelComboBox(card)
        self._empty_policy.addItem('停留当前页', userData='stay')
        self._empty_policy.addItem('回到主页面', userData='goto_main')
        self._empty_policy.currentIndexChanged.connect(self._auto_save)
        self._max_failures = CompactSpinBox(card)
        self._max_failures.setRange(1, 20)
        self._max_failures.valueChanged.connect(self._auto_save)
        form.addRow('空队列策略:', self._empty_policy)
        form.addRow('最大连续失败:', self._max_failures)
        layout.addLayout(form)
        return card

    def _task_min_interval_seconds(self) -> int:
        return resolve_task_min_interval_seconds(self.config.executor)

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

    @staticmethod
    def _set_combo_data(combo: NoWheelComboBox, value) -> None:
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
                if isinstance(interval_value, SpinBox) and isinstance(interval_unit, NoWheelComboBox):
                    value, unit = self._split_interval(
                        max(self._task_min_interval_seconds(), task_cfg.interval_seconds)
                    )
                    interval_value.setValue(value)
                    self._set_combo_data(interval_unit, unit)
                start, end = self._parse_enabled_time_range(getattr(task_cfg, 'enabled_time_range', ''))
                widgets['enabled_time_start'].setText(start)
                widgets['enabled_time_end'].setText(end)
            else:
                time_edit = widgets.get('daily_time')
                if isinstance(time_edit, TimeEdit):
                    try:
                        hh, mm = str(task_cfg.daily_time).split(':')
                        time_edit.setTime(QTime(int(hh), int(mm)))
                    except Exception:
                        time_edit.setTime(QTime(0, 1))

            next_run = widgets.get('next_run')
            if isinstance(next_run, LineEdit):
                normalized = self._normalize_next_run(str(getattr(task_cfg, 'next_run', '')))
                next_run.setText(
                    normalized or (self._normalize_next_run(DEFAULT_TASK_NEXT_RUN) or '2026-01-01 00:00:00')
                )

        self._set_combo_data(self._empty_policy, c.executor.empty_queue_policy)
        self._max_failures.setValue(max(1, int(c.executor.max_failures)))

    def _auto_save(self) -> None:
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
            if isinstance(enabled, CheckBox):
                task_cfg.enabled = bool(enabled.isChecked())

            if 'interval_value' in widgets and 'interval_unit' in widgets:
                value = int(widgets['interval_value'].value())
                factor = int(widgets['interval_unit'].currentData() or 1)
                task_cfg.trigger = TaskTriggerType.INTERVAL
                task_cfg.interval_seconds = max(self._task_min_interval_seconds(), value * max(1, factor))
                start = str(widgets['enabled_time_start'].text() or '')
                end = str(widgets['enabled_time_end'].text() or '')
                task_cfg.enabled_time_range = normalize_task_enabled_time_range(f'{start}-{end}')
            else:
                daily_time = widgets.get('daily_time')
                if isinstance(daily_time, TimeEdit):
                    task_cfg.trigger = TaskTriggerType.DAILY
                    task_cfg.daily_time = daily_time.time().toString('HH:mm')

            next_run = widgets.get('next_run')
            if isinstance(next_run, LineEdit):
                normalized = self._normalize_next_run(next_run.text())
                if normalized:
                    next_run.setText(normalized)
                    task_cfg.next_run = normalized

        c.save()
        self.config_changed.emit(c)

    def _on_next_run_edit_finished(self, task_name: str) -> None:
        widgets = self._task_widgets.get(task_name, {})
        next_run = widgets.get('next_run')
        if not isinstance(next_run, LineEdit):
            return
        normalized = self._normalize_next_run(next_run.text())
        if normalized is None:
            cfg = self.config.tasks.get(task_name)
            normalized = self._normalize_next_run(str(getattr(cfg, 'next_run', '')))
            if normalized is None:
                normalized = self._normalize_next_run(DEFAULT_TASK_NEXT_RUN) or '2026-01-01 00:00:00'
        next_run.setText(normalized)
        self._auto_save()

    def _on_time_range_edit_finished(self, task_name: str) -> None:
        widgets = self._task_widgets.get(task_name, {})
        start_edit = widgets.get('enabled_time_start')
        end_edit = widgets.get('enabled_time_end')
        if not isinstance(start_edit, LineEdit) or not isinstance(end_edit, LineEdit):
            return
        normalized = normalize_task_enabled_time_range(f'{start_edit.text()}-{end_edit.text()}')
        start, end = self._parse_enabled_time_range(normalized)
        start_edit.setText(start)
        end_edit.setText(end)
        self._auto_save()

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._loading = True
        self._load_config()
        self._loading = False
