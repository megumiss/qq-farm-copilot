"""状态面板 - 紧凑网格布局"""

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QGroupBox, QSizePolicy


class StatusPanel(QWidget):
    """承载 `StatusPanel` 相关界面控件与交互逻辑。"""
    _PAGE_NAME_MAP = {
        '--': '--',
        'unknown': '未知页面',
    }

    def __init__(self, parent=None):
        """初始化对象并准备运行所需状态。"""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._labels = {}
        self._init_ui()

    def _init_ui(self):
        """初始化 `ui` 相关状态或界面。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # 运行状态组
        status_group = QGroupBox("运行状态")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; color: #475569; }")
        status_layout = QGridLayout()
        status_layout.setContentsMargins(0, 0, 0, 4)
        status_layout.setHorizontalSpacing(16)
        status_layout.setVerticalSpacing(8)
        self._add_cell(status_layout, 0, 0, '状态', 'state', '● 未启动')
        self._add_cell(status_layout, 0, 1, '已运行', 'elapsed', '--')
        self._add_cell(status_layout, 0, 2, '下次检查', 'next_farm', '--')
        self._add_cell(status_layout, 0, 3, '页面', 'current_page', '--')
        status_group.setLayout(status_layout)
        outer.addWidget(status_group)

        # 任务信息组
        task_group = QGroupBox("任务信息")
        task_group.setStyleSheet("QGroupBox { font-weight: bold; color: #475569; }")
        task_layout = QGridLayout()
        task_layout.setContentsMargins(0, 0, 0, 4)
        task_layout.setHorizontalSpacing(16)
        task_layout.setVerticalSpacing(8)
        self._add_cell(task_layout, 0, 0, '当前任务', 'current_task', '--')
        self._add_cell(task_layout, 0, 1, '运行队列', 'running_tasks', '0')
        self._add_cell(task_layout, 0, 2, '待执行', 'pending_tasks', '0')
        self._add_cell(task_layout, 0, 3, '等待中', 'waiting_tasks', '0')
        self._add_cell(task_layout, 1, 0, '失败次数', 'failure_count', '0')
        self._add_cell(task_layout, 1, 1, '上次耗时', 'last_tick_ms', '--')
        self._add_cell(task_layout, 1, 2, '上次结果', 'last_result', '--')
        task_group.setLayout(task_layout)
        outer.addWidget(task_group)

        # 统计信息组
        stats_group = QGroupBox("统计信息")
        stats_group.setStyleSheet("QGroupBox { font-weight: bold; color: #475569; }")
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(0, 0, 0, 4)
        stats_layout.setHorizontalSpacing(16)
        stats_layout.setVerticalSpacing(8)
        self._add_cell(stats_layout, 0, 0, '收获', 'harvest', '0')
        self._add_cell(stats_layout, 0, 1, '播种', 'plant', '0')
        self._add_cell(stats_layout, 0, 2, '浇水', 'water', '0')
        self._add_cell(stats_layout, 1, 0, '除草', 'weed', '0')
        self._add_cell(stats_layout, 1, 1, '除虫', 'bug', '0')
        self._add_cell(stats_layout, 1, 2, '出售', 'sell', '0')
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

    @classmethod
    def _localize_page(cls, raw_page) -> str:
        """执行 `localize page` 相关处理。"""
        text = str(raw_page or '--').strip()
        if not text:
            return '--'
        return cls._PAGE_NAME_MAP.get(text, text)

    def update_stats(self, stats: dict):
        """更新 `stats` 状态。"""
        state = stats.get('state', 'idle')
        state_map = {
            'idle': ('● 未启动', '#94a3b8'),
            'running': ('● 运行中', '#16a34a'),
            'paused': ('● 已暂停', '#d97706'),
            'error': ('● 异常', '#dc2626'),
        }
        text, color = state_map.get(state, ('● 运行中', '#16a34a'))
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
        self._labels['last_result'].setText(str(stats.get('last_result', '--')))
        for key in ('harvest', 'plant', 'water', 'weed', 'bug', 'sell'):
            self._labels[key].setText(str(stats.get(key, 0)))
