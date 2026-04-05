"""任务配置面板（根据 tasks 配置自动生成）。"""

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTime, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTimeEdit,
    QWidget,
)

from gui.labels import load_ui_labels
from models.config import AppConfig, TaskTriggerType


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
        panel_labels = load_ui_labels().get('task_panel', {})
        self._task_title_map = panel_labels.get('task_titles', {})
        self._switch_label = str(panel_labels.get('switch_label', 'Switch:'))
        self._enabled_text = str(panel_labels.get('enabled', 'Enable'))
        self._daily_time_label = str(panel_labels.get('daily_time_label', 'Daily time:'))
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
        self._disabled_text = str(panel_labels.get('disabled', 'Disabled'))
        self._today_text = str(panel_labels.get('today', 'Today'))
        self._tomorrow_text = str(panel_labels.get('tomorrow', 'Tomorrow'))
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
        root = QGridLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

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
            root.addWidget(card, row, col)

        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 1)
        root.setRowStretch((len(self._cards) + 1) // 2, 1)
        self._align_cards_in_rows()

    def _build_task_group(self, task_name: str, trigger: TaskTriggerType) -> QGroupBox:
        """构建单个任务的配置卡片。

        
        - 固定提供任务开关。
        - `INTERVAL` 任务显示“执行间隔（秒/分钟/小时）”。
        - `DAILY` 任务显示“每日执行时间 + 下次执行提示”。
        """
        title = self._task_title_map.get(task_name, f'{task_name}{self._task_title_suffix}')
        group = QGroupBox(title)
        group.setStyleSheet("QGroupBox { font-weight: bold; color: #475569; }")
        form = QFormLayout()
        form.setContentsMargins(10, 15, 10, 10)
        form.setSpacing(10)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        enabled = QCheckBox(self._enabled_text)
        form.addRow(self._switch_label, enabled)
        widgets: dict[str, object] = {'enabled': enabled}

        if trigger == TaskTriggerType.DAILY:
            time_edit = QTimeEdit()
            time_edit.setDisplayFormat('HH:mm')
            time_edit.setFixedWidth(96)
            time_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            time_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            time_edit.setStyleSheet(
                "QTimeEdit {"
                "background-color: #ffffff;"
                "border: 1px solid #cbd5e1;"
                "border-radius: 6px;"
                "padding: 4px 8px;"
                "font-weight: 600;"
                "}"
                "QTimeEdit:focus { border-color: #2563eb; }"
            )
            next_label = QLabel('--')

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(time_edit)
            row_layout.addStretch()

            form.addRow(self._daily_time_label, row_widget)
            form.addRow(self._next_run_label, next_label)
            widgets['daily_time'] = time_edit
            widgets['next_label'] = next_label
        else:
            interval_value = QSpinBox()
            interval_value.setRange(1, 999999)
            interval_unit = QComboBox()
            interval_unit.addItem(self._interval_unit_second, 1)
            interval_unit.addItem(self._interval_unit_minute, 60)
            interval_unit.addItem(self._interval_unit_hour, 3600)

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(interval_value)
            row_layout.addWidget(interval_unit)
            row_layout.addStretch()

            form.addRow(self._interval_label, row_widget)
            widgets['interval_value'] = interval_value
            widgets['interval_unit'] = interval_unit

        group.setLayout(form)
        self._task_widgets[task_name] = widgets
        return group

    def _build_executor_group(self) -> QGroupBox:
        """构建执行器全局配置卡片。

        
        - 配置空队列策略（停留/回主界面）。
        - 配置最大连续失败次数（影响失败退避策略）。
        """
        group = QGroupBox(self._executor_group_title)
        group.setStyleSheet("QGroupBox { font-weight: bold; color: #475569; }")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(10)
        self._empty_policy = QComboBox()
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

            daily_time = widgets.get('daily_time')
            if isinstance(daily_time, QTimeEdit):
                daily_time.timeChanged.connect(self._auto_save)

        self._empty_policy.currentIndexChanged.connect(self._auto_save)
        self._max_failures.valueChanged.connect(self._auto_save)

    def _auto_save(self):
        """将当前面板值回写到配置对象并落盘。

        行为：
        - 更新 executor 全局策略。
        - 更新每个任务的 enabled/trigger/interval/daily_time。
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
                task_cfg.interval_seconds = max(1, int(interval_value.value()) * max(1, unit_factor))

            daily_time = widgets.get('daily_time')
            if isinstance(daily_time, QTimeEdit):
                task_cfg.trigger = TaskTriggerType.DAILY
                task_cfg.daily_time = daily_time.time().toString('HH:mm')
                self._refresh_daily_next_text(task_name)

        c.save()
        self.config_changed.emit(c)

    def _refresh_daily_next_text(self, task_name: str):
        """刷新每日任务的“下次执行”文案（今天/明天 + 时间）。"""
        widgets = self._task_widgets.get(task_name, {})
        enabled = widgets.get('enabled')
        daily_time = widgets.get('daily_time')
        next_label = widgets.get('next_label')
        if not isinstance(enabled, QCheckBox) or not isinstance(daily_time, QTimeEdit) or not isinstance(next_label, QLabel):
            return

        if not enabled.isChecked():
            next_label.setText(self._disabled_text)
            return

        now = datetime.now()
        selected = daily_time.time()
        target = now.replace(hour=selected.hour(), minute=selected.minute(), second=0, microsecond=0)
        day_hint = self._today_text
        if target <= now:
            target = target + timedelta(days=1)
            day_hint = self._tomorrow_text
        next_label.setText(f'{day_hint} {target:%m-%d %H:%M}')

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
                seconds = max(1, int(task_cfg.interval_seconds))
                display_value, unit_factor = self._split_interval_for_display(seconds)
                self._set_combo_data(interval_unit, unit_factor)
                interval_value.setValue(display_value)

            daily_time = widgets.get('daily_time')
            if isinstance(daily_time, QTimeEdit):
                try:
                    hh, mm = str(task_cfg.daily_time).split(':')
                    daily_time.setTime(QTime(int(hh), int(mm)))
                except Exception:
                    daily_time.setTime(QTime(4, 0))
                self._refresh_daily_next_text(task_name)

        for i in range(self._empty_policy.count()):
            if self._empty_policy.itemData(i) == c.executor.empty_queue_policy:
                self._empty_policy.setCurrentIndex(i)
                break
        self._max_failures.setValue(max(1, int(c.executor.max_failures)))

    @staticmethod
    def _split_interval_for_display(seconds: int) -> tuple[int, int]:
        """将秒数拆分为界面可读的值与单位。"""
        value = max(1, int(seconds))
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
