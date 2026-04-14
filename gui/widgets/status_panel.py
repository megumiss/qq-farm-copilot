"""Fluent 状态面板。"""

from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, StrongBodyLabel


class StatusPanel(QWidget):
    """运行态统计显示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels: dict[str, StrongBodyLabel] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        runtime_card, runtime_grid = self._build_card('运行状态')
        self._add_cell(runtime_grid, 0, 0, '状态', 'state', '● idle')
        self._add_cell(runtime_grid, 0, 1, '已运行', 'elapsed', '--')
        self._add_cell(runtime_grid, 0, 2, '平台', 'platform', '--')
        self._add_cell(runtime_grid, 0, 3, '窗口ID', 'window_id', '--')
        root.addWidget(runtime_card)

        tasks_card, tasks_grid = self._build_card('任务队列')
        self._add_cell(tasks_grid, 0, 0, '当前任务', 'current_task', '--')
        self._add_cell(tasks_grid, 0, 1, '运行中', 'running_tasks', '0')
        self._add_cell(tasks_grid, 0, 2, '待执行', 'pending_tasks', '0')
        self._add_cell(tasks_grid, 0, 3, '等待中', 'waiting_tasks', '0')
        self._add_cell(tasks_grid, 1, 0, '下一任务', 'next_task', '--')
        self._add_cell(tasks_grid, 1, 1, '下次执行', 'next_run', '--')
        root.addWidget(tasks_card)

        stats_card, stats_grid = self._build_card('动作统计')
        self._add_cell(stats_grid, 0, 0, '收获', 'harvest', '0')
        self._add_cell(stats_grid, 0, 1, '播种', 'plant', '0')
        self._add_cell(stats_grid, 0, 2, '浇水', 'water', '0')
        self._add_cell(stats_grid, 1, 0, '除草', 'weed', '0')
        self._add_cell(stats_grid, 1, 1, '除虫', 'bug', '0')
        self._add_cell(stats_grid, 1, 2, '出售', 'sell', '0')
        root.addWidget(stats_card)

    def _build_card(self, title: str) -> tuple[CardWidget, QGridLayout]:
        card = CardWidget(self)
        wrapper = QVBoxLayout(card)
        wrapper.setContentsMargins(12, 10, 12, 10)
        wrapper.setSpacing(8)
        wrapper.addWidget(BodyLabel(title))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        wrapper.addLayout(grid)
        return card, grid

    def _add_cell(self, grid: QGridLayout, row: int, col: int, title: str, key: str, default: str) -> None:
        row_widget = QWidget(self)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        row_layout.addWidget(BodyLabel(f'{title}:'))
        value = StrongBodyLabel(default)
        row_layout.addWidget(value)
        row_layout.addStretch()
        grid.addWidget(row_widget, row, col)
        self._labels[key] = value

    def update_stats(self, stats: dict) -> None:
        state = str(stats.get('state', 'idle'))
        color = {
            'idle': '#6b7280',
            'running': '#16a34a',
            'paused': '#d97706',
            'error': '#dc2626',
        }.get(state, '#2563eb')
        self._labels['state'].setText(f'● {state}')
        self._labels['state'].setStyleSheet(f'color: {color};')
        self._labels['elapsed'].setText(str(stats.get('elapsed', '--')))
        self._labels['platform'].setText(str(stats.get('current_platform', '--')))
        self._labels['window_id'].setText(str(stats.get('window_id', '--')))
        self._labels['current_task'].setText(str(stats.get('current_task', '--')))
        self._labels['running_tasks'].setText(str(stats.get('running_tasks', 0)))
        self._labels['pending_tasks'].setText(str(stats.get('pending_tasks', 0)))
        self._labels['waiting_tasks'].setText(str(stats.get('waiting_tasks', 0)))
        self._labels['next_task'].setText(str(stats.get('next_task', '--')))
        self._labels['next_run'].setText(str(stats.get('next_run', '--')))
        for key in ('harvest', 'plant', 'water', 'weed', 'bug', 'sell'):
            self._labels[key].setText(str(stats.get(key, 0)))
