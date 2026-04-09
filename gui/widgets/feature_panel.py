"""任务设置面板（按 tasks.<task>.features 生成）。"""

from pathlib import Path

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
from utils.app_paths import load_config_json_object
from utils.feature_policy import is_feature_forced_off


class FeaturePanel(QWidget):
    """承载 `FeaturePanel` 相关界面控件与交互逻辑。"""

    config_changed = pyqtSignal(object)
    _FORCED_OFF_ICON = (Path(__file__).resolve().parents[1] / 'icons' / 'disabled_x.svg').as_posix()
    _FORCED_OFF_STYLE = (
        'QCheckBox { color: #9ca3af; }'
        'QCheckBox::indicator {'
        '  width: 14px; height: 14px; border: 1.5px solid #d1d5db;'
        '  border-radius: 3px; background: #f3f4f6;'
        '}'
        'QCheckBox::indicator:unchecked:disabled {'
        f'  image: url({_FORCED_OFF_ICON});'
        '}'
        'QCheckBox::indicator:checked:disabled {'
        f'  image: url({_FORCED_OFF_ICON});'
        '}'
    )

    def __init__(self, config: AppConfig, parent=None):
        """初始化对象并准备运行所需状态。"""
        super().__init__(parent)
        self.config = config
        panel_labels = load_config_json_object('ui_labels.json', prefer_user=False).get('feature_panel', {})
        self._task_title_map = panel_labels.get('task_titles', {})
        self._feature_label_map = panel_labels.get('feature_labels', {})
        self._enabled_text = str(panel_labels.get('enabled', 'Enable'))
        self._empty_text = str(panel_labels.get('empty_text', 'No configurable feature items'))
        self._task_title_suffix = str(panel_labels.get('task_title_suffix', ' task'))
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
        task_names = [str(name) for name in getattr(self.config, 'tasks', {}).keys()]
        for task_name in task_names:
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = getattr(task_cfg, 'features', {}) or {}
            if not isinstance(feature_map, dict) or not feature_map:
                continue
            group = self._build_task_group(task_name, feature_map)
            grid.addWidget(group, idx // 2, idx % 2)
            idx += 1

        if idx == 0:
            empty = QLabel(self._empty_text)
            empty.setStyleSheet('color: #94a3b8;')
            root.addWidget(empty)
        else:
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            root.addLayout(grid)
        root.addStretch()

    def _build_task_group(self, task_name: str, feature_map: dict[str, bool]) -> QGroupBox:
        """构建 `task_group` 对应的结构或组件。"""
        title = self._task_title_map.get(task_name, f'{task_name}{self._task_title_suffix}')
        group = QGroupBox(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(10)
        for feature_name in feature_map.keys():
            label = self._feature_label_map.get(feature_name, feature_name)
            cb = QCheckBox(self._enabled_text)
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
            task_cfg = c.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = dict(getattr(task_cfg, 'features', {}) or {})
            if is_feature_forced_off(task_name, feature_name):
                feature_map[str(feature_name)] = False
            else:
                feature_map[str(feature_name)] = bool(cb.isChecked())
            task_cfg.features = feature_map
        c.save()
        self.config_changed.emit(c)

    def _load_config(self):
        """加载 `config` 相关数据。"""
        c = self.config
        for (task_name, feature_name), cb in self._feature_boxes.items():
            task_cfg = c.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = getattr(task_cfg, 'features', {}) or {}
            forced = is_feature_forced_off(task_name, feature_name)
            if forced:
                cb.setChecked(False)
                cb.setEnabled(False)
                cb.setToolTip('该功能为固定禁用项')
                cb.setStyleSheet(self._FORCED_OFF_STYLE)
            else:
                cb.setEnabled(True)
                cb.setToolTip('')
                cb.setStyleSheet('')
                cb.setChecked(bool(feature_map.get(feature_name, False)))
