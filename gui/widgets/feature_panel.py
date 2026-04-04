"""任务设置面板（按 tasks.<task>.features 生成）。"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from models.config import AppConfig


class FeaturePanel(QWidget):
    """承载 `FeaturePanel` 相关界面控件与交互逻辑。"""
    config_changed = pyqtSignal(object)

    TASK_TITLE_MAP = {
        'farm_main': '农场巡查任务',
        'friend': '好友巡查任务',
        'share': '分享任务',
    }

    FEATURE_LABEL_MAP = {
        'auto_harvest': '收获',
        'auto_plant': '播种',
        'auto_water': '浇水',
        'auto_weed': '除草',
        'auto_bug': '除虫',
        'auto_sell': '出售',
        'auto_upgrade': '扩建',
        'auto_help': '帮忙',
        'auto_steal': '偷菜',
        'auto_task': '任务奖励',
        'auto_fertilize': '施肥',
        'auto_bad': '坏菜处理',
    }

    def __init__(self, config: AppConfig, parent=None):
        """初始化对象并准备运行所需状态。"""
        super().__init__(parent)
        self.config = config
        self._loading = True
        self._feature_boxes: dict[tuple[str, str], QCheckBox] = {}
        self._init_ui()
        self._load_config()
        self._connect_auto_save()
        self._loading = False

    def _init_ui(self):
        """初始化 `ui` 相关状态或界面。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(10)
        idx = 0
        task_names = list(type(self.config.tasks).model_fields.keys())
        for task_name in task_names:
            task_cfg = getattr(self.config.tasks, task_name, None)
            if task_cfg is None:
                continue
            feature_map = getattr(task_cfg, 'features', {}) or {}
            if not isinstance(feature_map, dict) or not feature_map:
                continue
            group = self._build_task_group(task_name, feature_map)
            grid.addWidget(group, idx // 2, idx % 2)
            idx += 1

        if idx == 0:
            empty = QLabel('当前没有可配置的任务功能项')
            empty.setStyleSheet('color: #94a3b8;')
            root.addWidget(empty)
        else:
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            root.addLayout(grid)
        root.addStretch()

    def _build_task_group(self, task_name: str, feature_map: dict[str, bool]) -> QGroupBox:
        """构建 `task_group` 对应的结构或组件。"""
        title = self.TASK_TITLE_MAP.get(task_name, f'{task_name}任务')
        group = QGroupBox(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(10)
        for feature_name in feature_map.keys():
            label = self.FEATURE_LABEL_MAP.get(feature_name, feature_name)
            cb = QCheckBox('启用')
            self._feature_boxes[(task_name, feature_name)] = cb
            form.addRow(f'{label}:', cb)
        group.setLayout(form)
        return group

    def _connect_auto_save(self):
        """绑定 `auto_save` 相关信号或回调。"""
        for cb in self._feature_boxes.values():
            cb.toggled.connect(self._auto_save)

    def _auto_save(self):
        """执行 `auto save` 相关处理。"""
        if self._loading:
            return
        c = self.config
        for (task_name, feature_name), cb in self._feature_boxes.items():
            task_cfg = getattr(c.tasks, task_name, None)
            if task_cfg is None:
                continue
            feature_map = dict(getattr(task_cfg, 'features', {}) or {})
            feature_map[str(feature_name)] = bool(cb.isChecked())
            task_cfg.features = feature_map
        c.save()
        self.config_changed.emit(c)

    def _load_config(self):
        """加载 `config` 相关数据。"""
        c = self.config
        for (task_name, feature_name), cb in self._feature_boxes.items():
            task_cfg = getattr(c.tasks, task_name, None)
            if task_cfg is None:
                continue
            feature_map = getattr(task_cfg, 'features', {}) or {}
            cb.setChecked(bool(feature_map.get(feature_name, False)))
