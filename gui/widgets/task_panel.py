"""任务配置面板（根据 tasks 配置自动生成）。"""

from datetime import datetime, timedelta

from PyQt6.QtCore import QTime, Qt, pyqtSignal
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

from models.config import AppConfig, TaskTriggerType


class TaskPanel(QWidget):
    """任务调度配置面板。

    
    - 根据 `tasks` 配置动态生成任务调度表单。
    - 维护执行器策略（空队列策略、最大连续失败）。
    - 用户修改后自动写回 `config.json` 并发出 `config_changed` 信号。
    """
    config_changed = pyqtSignal(object)

    TASK_TITLE_MAP = {
        'farm_main': '农场巡查任务',
        'friend': '好友巡查任务',
        'share': '分享任务（每日）',
    }

    def __init__(self, config: AppConfig, parent=None):
        """初始化任务调度面板并加载配置。"""
        super().__init__(parent)
        self.config = config
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

        self._task_order = list(type(self.config.tasks).model_fields.keys())
        for task_name in self._task_order:
            task_cfg = getattr(self.config.tasks, task_name)
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
        - `INTERVAL` 任务显示“执行间隔(秒)”。
        - `DAILY` 任务显示“每日执行时间 + 下次执行提示”。
        """
        title = self.TASK_TITLE_MAP.get(task_name, f'{task_name}任务')
        group = QGroupBox(title)
        group.setStyleSheet("QGroupBox { font-weight: bold; color: #475569; }")
        form = QFormLayout()
        form.setContentsMargins(10, 15, 10, 10)
        form.setSpacing(10)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        enabled = QCheckBox('启用')
        form.addRow('开关:', enabled)
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
            hint = QLabel('24小时制')
            hint.setStyleSheet("color: #94a3b8;")
            next_label = QLabel('--')

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(time_edit)
            row_layout.addWidget(hint)
            row_layout.addStretch()

            form.addRow('每日执行时间:', row_widget)
            form.addRow('下次执行:', next_label)
            widgets['daily_time'] = time_edit
            widgets['next_label'] = next_label
        else:
            interval = QSpinBox()
            interval.setRange(1, 86400)
            interval.setSuffix(' 秒')
            form.addRow('执行间隔:', interval)
            widgets['interval_seconds'] = interval

        group.setLayout(form)
        self._task_widgets[task_name] = widgets
        return group

    def _build_executor_group(self) -> QGroupBox:
        """构建执行器全局配置卡片。

        
        - 配置空队列策略（停留/回主界面）。
        - 配置最大连续失败次数（影响失败退避策略）。
        """
        group = QGroupBox('执行器')
        group.setStyleSheet("QGroupBox { font-weight: bold; color: #475569; }")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(10)
        self._empty_policy = QComboBox()
        self._empty_policy.addItem('空队列停留', 'stay')
        self._empty_policy.addItem('空队列回主界面', 'goto_main')
        self._max_failures = QSpinBox()
        self._max_failures.setRange(1, 20)
        form.addRow('空队列策略:', self._empty_policy)
        form.addRow('最大连续失败:', self._max_failures)
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

            interval = widgets.get('interval_seconds')
            if isinstance(interval, QSpinBox):
                interval.valueChanged.connect(self._auto_save)

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
            task_cfg = getattr(c.tasks, task_name, None)
            if task_cfg is None:
                continue
            widgets = self._task_widgets.get(task_name, {})
            enabled = widgets.get('enabled')
            if isinstance(enabled, QCheckBox):
                task_cfg.enabled = bool(enabled.isChecked())

            interval = widgets.get('interval_seconds')
            if isinstance(interval, QSpinBox):
                task_cfg.trigger = TaskTriggerType.INTERVAL
                task_cfg.interval_seconds = int(interval.value())

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
            next_label.setText('未启用')
            return

        now = datetime.now()
        selected = daily_time.time()
        target = now.replace(hour=selected.hour(), minute=selected.minute(), second=0, microsecond=0)
        day_hint = '今天'
        if target <= now:
            target = target + timedelta(days=1)
            day_hint = '明天'
        next_label.setText(f'{day_hint} {target:%m-%d %H:%M}')

    def _load_config(self):
        """从配置对象加载初始值到界面控件。"""
        c = self.config

        for task_name in self._task_order:
            task_cfg = getattr(c.tasks, task_name, None)
            if task_cfg is None:
                continue
            widgets = self._task_widgets.get(task_name, {})
            enabled = widgets.get('enabled')
            if isinstance(enabled, QCheckBox):
                enabled.setChecked(bool(task_cfg.enabled))

            interval = widgets.get('interval_seconds')
            if isinstance(interval, QSpinBox):
                interval.setValue(max(1, int(task_cfg.interval_seconds)))

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
