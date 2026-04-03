"""状态面板 - 紧凑网格布局"""

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class StatusPanel(QWidget):
    _PAGE_NAME_MAP = {
        '--': '--',
        'unknown': '未知页面',
        'farm_overview': '农场主界面',
        'friend_farm': '好友农场',
        'plot_menu': '土地菜单',
        'seed_select': '种子选择',
        'shop_page': '商店页面',
        'buy_confirm': '购买确认',
        'popup': '弹窗',
        'level_up': '升级弹窗',
        # 兼容运行态枚举值
        'main': '农场主界面',
        'shop': '商店页面',
        'friend': '好友农场',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels = {}
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(14)

        self._add_cell(grid, 0, 0, '状态', 'state', '● 未启动')
        self._add_cell(grid, 0, 1, '已运行', 'elapsed', '--')
        self._add_cell(grid, 0, 2, '下次检查', 'next_farm', '--')
        self._add_cell(grid, 0, 3, '页面', 'current_page', '--')

        self._add_cell(grid, 1, 0, '收获', 'harvest', '0')
        self._add_cell(grid, 1, 1, '播种', 'plant', '0')
        self._add_cell(grid, 1, 2, '浇水', 'water', '0')
        self._add_cell(grid, 1, 3, '任务', 'current_task', '--')

        self._add_cell(grid, 2, 0, '除草', 'weed', '0')
        self._add_cell(grid, 2, 1, '除虫', 'bug', '0')
        self._add_cell(grid, 2, 2, '出售', 'sell', '0')
        self._add_cell(grid, 2, 3, '失败', 'failure_count', '0')

        self._add_cell(grid, 3, 0, '运行队列', 'running_tasks', '0')
        self._add_cell(grid, 3, 1, '待执行', 'pending_tasks', '0')
        self._add_cell(grid, 3, 2, '等待中', 'waiting_tasks', '0')
        self._add_cell(grid, 3, 3, '上次耗时', 'last_tick_ms', '--')
        self._add_cell(grid, 4, 0, '上次结果', 'last_result', '--')

        outer.addLayout(grid)
        outer.addStretch()

    def _add_cell(self, grid: QGridLayout, row: int, col: int, label_text: str, key: str, default: str):
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
        text = str(raw_page or '--').strip()
        if not text:
            return '--'
        return cls._PAGE_NAME_MAP.get(text, text)

    def update_stats(self, stats: dict):
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
