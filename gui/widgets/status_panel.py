"""状态面板 - 紧凑网格布局"""

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QGroupBox, QSizePolicy

from utils.app_paths import load_config_json_object


class StatusPanel(QWidget):
    """承载 `StatusPanel` 相关界面控件与交互逻辑。"""

    def __init__(self, parent=None):
        """初始化对象并准备运行所需状态。"""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        panel_labels = load_config_json_object('ui_labels.json', prefer_user=False).get('status_panel', {})
        self._group_titles = panel_labels.get('group_titles', {})
        self._cell_labels = panel_labels.get('labels', {})
        self._page_name_map = panel_labels.get('page_names', {})
        self._state_text_map = panel_labels.get('state_text', {})
        self._labels = {}
        self._init_ui()

    def _init_ui(self):
        """初始化 `ui` 相关状态或界面。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # 运行状态组
        status_group = QGroupBox(str(self._group_titles.get('runtime', 'Runtime')))
        status_group.setStyleSheet('QGroupBox { font-weight: bold; color: #475569; }')
        status_layout = QGridLayout()
        status_layout.setContentsMargins(0, 0, 0, 4)
        status_layout.setHorizontalSpacing(16)
        status_layout.setVerticalSpacing(8)
        self._add_cell(status_layout, 0, 0, self._cell_labels.get('state', 'State'), 'state', '● --')
        self._add_cell(status_layout, 0, 1, self._cell_labels.get('elapsed', 'Elapsed'), 'elapsed', '--')
        self._add_cell(status_layout, 0, 2, self._cell_labels.get('next_check', 'Next check'), 'next_farm', '--')
        self._add_cell(status_layout, 0, 3, self._cell_labels.get('page', 'Page'), 'current_page', '--')
        status_group.setLayout(status_layout)
        outer.addWidget(status_group)

        # 任务信息组
        task_group = QGroupBox(str(self._group_titles.get('task', 'Task')))
        task_group.setStyleSheet('QGroupBox { font-weight: bold; color: #475569; }')
        task_layout = QGridLayout()
        task_layout.setContentsMargins(0, 0, 0, 4)
        task_layout.setHorizontalSpacing(16)
        task_layout.setVerticalSpacing(8)
        self._add_cell(task_layout, 0, 0, self._cell_labels.get('current_task', 'Current task'), 'current_task', '--')
        self._add_cell(task_layout, 0, 1, self._cell_labels.get('running_tasks', 'Running'), 'running_tasks', '0')
        self._add_cell(task_layout, 0, 2, self._cell_labels.get('pending_tasks', 'Pending'), 'pending_tasks', '0')
        self._add_cell(task_layout, 0, 3, self._cell_labels.get('waiting_tasks', 'Waiting'), 'waiting_tasks', '0')
        self._add_cell(task_layout, 1, 0, self._cell_labels.get('failure_count', 'Failures'), 'failure_count', '0')
        self._add_cell(task_layout, 1, 1, self._cell_labels.get('last_tick_ms', 'Last tick'), 'last_tick_ms', '--')
        task_group.setLayout(task_layout)
        outer.addWidget(task_group)

        # 统计信息组
        stats_group = QGroupBox(str(self._group_titles.get('stats', 'Stats')))
        stats_group.setStyleSheet('QGroupBox { font-weight: bold; color: #475569; }')
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(0, 0, 0, 4)
        stats_layout.setHorizontalSpacing(16)
        stats_layout.setVerticalSpacing(8)
        self._add_cell(stats_layout, 0, 0, self._cell_labels.get('harvest', 'Harvest'), 'harvest', '0')
        self._add_cell(stats_layout, 0, 1, self._cell_labels.get('plant', 'Plant'), 'plant', '0')
        self._add_cell(stats_layout, 0, 2, self._cell_labels.get('water', 'Water'), 'water', '0')
        self._add_cell(stats_layout, 1, 0, self._cell_labels.get('weed', 'Weed'), 'weed', '0')
        self._add_cell(stats_layout, 1, 1, self._cell_labels.get('bug', 'Bug'), 'bug', '0')
        self._add_cell(stats_layout, 1, 2, self._cell_labels.get('sell', 'Sell'), 'sell', '0')
        stats_group.setLayout(stats_layout)
        outer.addWidget(stats_group)

    def _add_cell(self, grid: QGridLayout, row: int, col: int, label_text: str, key: str, default: str):
        """执行 `add cell` 相关处理。"""
        container = QHBoxLayout()
        container.setSpacing(3)
        container.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setStyleSheet('color: #94a3b8; font-size: 12px;')
        value = QLabel(default)
        value.setStyleSheet('color: #1e293b; font-size: 12px; font-weight: bold;')
        container.addWidget(label)
        container.addWidget(value)
        container.addStretch()
        wrapper = QWidget()
        wrapper.setLayout(container)
        grid.addWidget(wrapper, row, col)
        self._labels[key] = value

    def _localize_page(self, raw_page) -> str:
        """执行 `localize page` 相关处理。"""
        text = str(raw_page or '--').strip()
        if not text:
            return '--'
        return self._page_name_map.get(text, text)

    def update_stats(self, stats: dict):
        """更新 `stats` 状态。"""
        state = stats.get('state', 'idle')
        state_map = {
            'idle': (self._state_text_map.get('idle', '● idle'), '#94a3b8'),
            'running': (self._state_text_map.get('running', '● running'), '#16a34a'),
            'paused': (self._state_text_map.get('paused', '● paused'), '#d97706'),
            'error': (self._state_text_map.get('error', '● error'), '#dc2626'),
        }
        text, color = state_map.get(state, (self._state_text_map.get('default', '● running'), '#16a34a'))
        self._labels['state'].setText(text)
        self._labels['state'].setStyleSheet(f'color: {color}; font-size: 12px; font-weight: bold;')
        self._labels['elapsed'].setText(stats.get('elapsed', '--'))
        self._labels['next_farm'].setText(stats.get('next_farm_check', '--'))
        self._labels['current_page'].setText(self._localize_page(stats.get('current_page', '--')))
        self._labels['current_task'].setText(str(stats.get('current_task', '--')))
        self._labels['failure_count'].setText(str(stats.get('failure_count', 0)))
        self._labels['running_tasks'].setText(str(stats.get('running_tasks', 0)))
        self._labels['pending_tasks'].setText(str(stats.get('pending_tasks', 0)))
        self._labels['waiting_tasks'].setText(str(stats.get('waiting_tasks', 0)))
        self._labels['last_tick_ms'].setText(str(stats.get('last_tick_ms', '--')))
        for key in ('harvest', 'plant', 'water', 'weed', 'bug', 'sell'):
            self._labels[key].setText(str(stats.get(key, 0)))
