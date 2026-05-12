"""Fluent 状态面板。"""

from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    StrongBodyLabel,
)

from gui.widgets.fluent_container import StableElevatedCardWidget


class StatusPanel(QWidget):
    """运行态统计显示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels: dict[str, StrongBodyLabel] = {}
        self._numeric_keys = {
            'running_tasks',
            'pending_tasks',
            'waiting_tasks',
            'harvest',
            'plant',
            'water',
            'weed',
            'bug',
            'fertilize',
            'sell',
        }
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        runtime_card, runtime_grid = self._build_card('运行状态', FluentIcon.ROBOT)
        self._add_cell(runtime_grid, 0, 0, '状态', 'state', '空闲')
        self._add_cell(runtime_grid, 0, 1, '已运行', 'elapsed', '--')
        self._add_cell(runtime_grid, 0, 2, '平台', 'platform', '--')
        self._add_cell(runtime_grid, 0, 3, '窗口ID', 'window_id', '--')
        root.addWidget(runtime_card)

        tasks_card, tasks_grid = self._build_card('任务队列', FluentIcon.CALENDAR)
        self._add_cell(tasks_grid, 0, 0, '当前任务', 'current_task', '--')
        self._add_cell(tasks_grid, 0, 1, '运行中', 'running_tasks', '0')
        self._add_cell(tasks_grid, 0, 2, '待执行', 'pending_tasks', '0')
        self._add_cell(tasks_grid, 0, 3, '等待中', 'waiting_tasks', '0')
        self._add_cell(tasks_grid, 1, 0, '下一任务', 'next_task', '--')
        self._add_cell(tasks_grid, 1, 1, '下次执行', 'next_run', '--')
        root.addWidget(tasks_card)

        stats_card, stats_grid = self._build_card('动作统计', FluentIcon.APPLICATION)
        self._add_cell(stats_grid, 0, 0, '收获', 'harvest', '0')
        self._add_cell(stats_grid, 0, 1, '播种', 'plant', '0')
        self._add_cell(stats_grid, 0, 2, '浇水', 'water', '0')
        self._add_cell(stats_grid, 1, 0, '除草', 'weed', '0')
        self._add_cell(stats_grid, 1, 1, '除虫', 'bug', '0')
        self._add_cell(stats_grid, 1, 2, '出售', 'sell', '0')
        self._add_cell(stats_grid, 2, 0, '施肥', 'fertilize', '0')
        root.addWidget(stats_card)

    def _build_card(self, title: str, icon: FluentIcon) -> tuple[StableElevatedCardWidget, QGridLayout]:
        card = StableElevatedCardWidget(self)
        card.setObjectName('statusCard')
        card.setStyleSheet(
            'ElevatedCardWidget#statusCard { border-radius: 10px; border: 1px solid rgba(100, 116, 139, 0.22); }'
            'ElevatedCardWidget#statusCard:hover {'
            ' background-color: rgba(37, 99, 235, 0.06);'
            ' border: 1px solid rgba(59, 130, 246, 0.32);'
            ' }'
        )
        wrapper = QVBoxLayout(card)
        wrapper.setContentsMargins(12, 10, 12, 10)
        wrapper.setSpacing(8)

        header = QWidget(card)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        icon_widget = IconWidget(icon, header)
        icon_widget.setFixedSize(14, 14)
        header_layout.addWidget(icon_widget)
        title_label = BodyLabel(title)
        title_label.setStyleSheet('font-weight: 700; font-size: 14px; color: #1e293b;')
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        wrapper.addWidget(header)
        divider = QWidget(card)
        divider.setFixedHeight(1)
        divider.setStyleSheet('background-color: rgba(37, 99, 235, 0.10); border: none;')
        wrapper.addWidget(divider)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        wrapper.addLayout(grid)
        return card, grid

    def _add_cell(self, grid: QGridLayout, row: int, col: int, title: str, key: str, default: str) -> None:
        row_widget = QWidget(self)
        row_widget.setObjectName('statusItem')
        row_widget.setStyleSheet('QWidget#statusItem { border: none; border-radius: 6px; background: transparent; }')
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(6, 2, 6, 2)
        row_layout.setSpacing(6)
        title_label = CaptionLabel(f'{title}:')
        title_label.setTextColor(QColor('#64748B'), QColor('#94A3B8'))
        row_layout.addWidget(title_label)
        value = StrongBodyLabel(default)
        if key in self._numeric_keys:
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setMinimumWidth(value.fontMetrics().horizontalAdvance('00000'))
        if key in {'current_task', 'next_run'}:
            value.setStyleSheet('font-weight: 700;')
        value.setTextColor(QColor('#0F172A'), QColor('#E5E7EB'))
        row_layout.addWidget(value)
        row_layout.addStretch()
        grid.addWidget(row_widget, row, col)
        self._labels[key] = value

    def _set_value(self, key: str, value: str, *, tooltip: str | None = None) -> None:
        label = self._labels[key]
        text = str(value)
        label.setText(text)
        label.setToolTip(text if tooltip is None else str(tooltip))

    @staticmethod
    def _safe_int(value) -> int:
        try:
            return int(str(value))
        except Exception:
            return 0

    @staticmethod
    def _format_seconds(seconds: int) -> str:
        sec = max(0, int(seconds))
        day, rem = divmod(sec, 86400)
        hour, rem = divmod(rem, 3600)
        minute, second = divmod(rem, 60)
        if day > 0:
            return f'{day}天{hour}小时'
        if hour > 0:
            return f'{hour}小时{minute}分'
        if minute > 0:
            return f'{minute}分{second}秒'
        return f'{second}秒'

    @classmethod
    def _format_next_run(cls, raw_value) -> tuple[str, str]:
        raw = str(raw_value or '--').strip()
        if not raw or raw == '--':
            return '--', '--'
        normalized = raw.replace('T', ' ')
        parsed = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                parsed = datetime.strptime(normalized, fmt)
                break
            except Exception:
                continue
        if parsed is None:
            # 调度面板快照默认给的是 MM-DD HH:MM:SS，需要补齐年份后再计算相对时间。
            for fmt in ('%m-%d %H:%M:%S', '%m-%d %H:%M'):
                try:
                    partial = datetime.strptime(normalized, fmt)
                    now = datetime.now()
                    parsed = partial.replace(year=now.year)
                    # 跨年边界兜底：若补齐后落到“很久以前”，按下一年处理。
                    if parsed < now - timedelta(days=180):
                        parsed = parsed.replace(year=now.year + 1)
                    break
                except Exception:
                    continue
        if parsed is None:
            return raw, raw
        now = datetime.now()
        delta = int((parsed - now).total_seconds())
        when = parsed.strftime('%H:%M:%S') if parsed.date() == now.date() else parsed.strftime('%m-%d %H:%M:%S')
        if delta >= 0:
            relative = f'{cls._format_seconds(delta)}后'
        else:
            relative = f'{cls._format_seconds(-delta)}前'
        display = f'{when}（{relative}）'
        return display, parsed.strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _short_text(raw_value, limit: int = 22) -> str:
        text = str(raw_value or '--')
        if len(text) <= limit:
            return text
        head = max(4, limit // 2 - 2)
        tail = max(4, limit - head - 3)
        return f'{text[:head]}...{text[-tail:]}'

    def _set_counter_color(self, key: str, value: int, active_light: str, active_dark: str) -> None:
        if int(value) <= 0:
            self._labels[key].setTextColor(QColor('#64748B'), QColor('#94A3B8'))
            return
        self._labels[key].setTextColor(QColor(active_light), QColor(active_dark))

    def _set_state_badge(self, state: str, state_text: str) -> None:
        fg_map = {
            'idle': QColor('#64748B'),
            'running': QColor('#16A34A'),
            'paused': QColor('#D97706'),
            'error': QColor('#DC2626'),
        }
        style_map = {
            'idle': ('rgba(100,116,139,0.10)', 'rgba(100,116,139,0.30)'),
            'running': ('rgba(22,163,74,0.12)', 'rgba(22,163,74,0.34)'),
            'paused': ('rgba(217,119,6,0.12)', 'rgba(217,119,6,0.34)'),
            'error': ('rgba(220,38,38,0.12)', 'rgba(220,38,38,0.34)'),
        }
        fg = fg_map.get(state, QColor('#2563EB'))
        bg, border = style_map.get(state, ('rgba(37,99,235,0.12)', 'rgba(37,99,235,0.34)'))
        state_label = self._labels['state']
        state_label.setText(state_text)
        state_label.setToolTip(state_text)
        state_label.setTextColor(fg, fg)
        state_label.setStyleSheet(
            'QLabel {'
            f' background-color: {bg};'
            f' border: 1px solid {border};'
            ' border-radius: 8px;'
            ' padding: 0 7px;'
            ' font-size: 12px;'
            ' font-weight: 600;'
            ' }'
        )

    def update_stats(self, stats: dict) -> None:
        state = str(stats.get('state', 'idle'))
        state_text = {
            'idle': '空闲',
            'running': '运行中',
            'paused': '已暂停',
            'error': '异常',
        }.get(state, state)
        self._set_state_badge(state, state_text)
        self._set_value('elapsed', stats.get('elapsed', '--'))
        self._set_value('platform', stats.get('current_platform', '--'))
        raw_window_id = str(stats.get('window_id', '--'))
        self._set_value('window_id', self._short_text(raw_window_id, 18), tooltip=raw_window_id)
        self._set_value('current_task', stats.get('current_task', '--'))
        running_tasks = self._safe_int(stats.get('running_tasks', 0))
        pending_tasks = self._safe_int(stats.get('pending_tasks', 0))
        waiting_tasks = self._safe_int(stats.get('waiting_tasks', 0))
        self._set_value('running_tasks', running_tasks)
        self._set_value('pending_tasks', pending_tasks)
        self._set_value('waiting_tasks', waiting_tasks)
        self._set_counter_color('running_tasks', running_tasks, '#16A34A', '#4ADE80')
        self._set_counter_color('pending_tasks', pending_tasks, '#2563EB', '#60A5FA')
        self._set_counter_color('waiting_tasks', waiting_tasks, '#D97706', '#FBBF24')
        self._set_value('next_task', stats.get('next_task', '--'))
        next_run_text, next_run_tooltip = self._format_next_run(stats.get('next_run', '--'))
        self._set_value('next_run', next_run_text, tooltip=next_run_tooltip)
        for key in ('harvest', 'plant', 'water', 'weed', 'bug', 'fertilize', 'sell'):
            value = self._safe_int(stats.get(key, 0))
            self._set_value(key, value)
            self._set_counter_color(key, value, '#0F766E', '#2DD4BF')
