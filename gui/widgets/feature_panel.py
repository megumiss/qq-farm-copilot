"""Fluent 任务功能面板。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QFormLayout, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    CheckBox,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
)

from gui.widgets.fluent_container import TransparentCardContainer
from models.config import AppConfig
from utils.app_paths import load_config_json_object
from utils.feature_policy import is_feature_forced_off


class _ListEditorDialog(QDialog):
    def __init__(self, title: str, values: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        self._list = ListWidget(self)
        for text in values:
            self._list.addItem(str(text))
        root.addWidget(self._list, 1)

        row = QHBoxLayout()
        self._input = LineEdit(self)
        self._input.setPlaceholderText('输入后回车或点击新增')
        add_btn = PushButton('新增', self)
        add_btn.clicked.connect(self._on_add)
        self._input.returnPressed.connect(self._on_add)
        row.addWidget(self._input, 1)
        row.addWidget(add_btn)
        root.addLayout(row)

        action = QHBoxLayout()
        action.addStretch()
        remove_btn = PushButton('删除选中', self)
        cancel_btn = PushButton('取消', self)
        ok_btn = PrimaryPushButton('保存', self)
        remove_btn.clicked.connect(self._on_remove_selected)
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        action.addWidget(remove_btn)
        action.addWidget(cancel_btn)
        action.addWidget(ok_btn)
        root.addLayout(action)

    def _on_add(self) -> None:
        text = str(self._input.text() or '').strip()
        if not text:
            return
        existed = {self._list.item(i).text().strip().lower() for i in range(self._list.count())}
        if text.lower() in existed:
            self._input.clear()
            return
        self._list.addItem(text)
        self._input.clear()

    def _on_remove_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self._list.takeItem(self._list.row(item))

    def values(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for i in range(self._list.count()):
            text = str(self._list.item(i).text() or '').strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out


class FeaturePanel(QWidget):
    """任务 features 配置。"""

    config_changed = pyqtSignal(object)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        labels = load_config_json_object('ui_labels.json', prefer_user=False).get('feature_panel', {})
        self._task_title_map = labels.get('task_titles', {})
        self._feature_label_map = labels.get('feature_labels', {})
        self._loading = True
        self._bool_widgets: dict[tuple[str, str], CheckBox] = {}
        self._list_summary: dict[tuple[str, str], BodyLabel] = {}
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

        content = TransparentCardContainer(self)
        scroll.setWidget(content)
        scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')
        scroll.viewport().setStyleSheet('background: transparent;')
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

        index = 0
        for task_name, task_cfg in self.config.tasks.items():
            feature_map = getattr(task_cfg, 'features', {}) or {}
            if not isinstance(feature_map, dict) or not feature_map:
                continue
            card = self._build_task_card(task_name, feature_map)
            target = 0 if col_heights[0] <= col_heights[1] else 1
            columns[target].addWidget(card)
            col_heights[target] += max(1, int(card.sizeHint().height()))
            index += 1

        if index == 0:
            content_layout.addWidget(BodyLabel('当前无可配置的功能项'))
        else:
            for col in columns:
                col.addStretch()
            content_layout.addLayout(waterfall)
        content_layout.addStretch()

    def _build_task_card(self, task_name: str, feature_map: dict[str, Any]) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(BodyLabel(str(self._task_title_map.get(task_name, task_name))))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        for feature_name, value in feature_map.items():
            label = str(self._feature_label_map.get(feature_name, feature_name))
            if isinstance(value, list):
                row = QWidget(card)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(8)
                summary = BodyLabel('未配置')
                self._list_summary[(task_name, feature_name)] = summary
                btn = PushButton('详情', row)
                btn.clicked.connect(
                    lambda _=False, t=task_name, f=feature_name: self._open_list_editor(t, f),
                )
                row_layout.addWidget(summary, 1)
                row_layout.addWidget(btn)
                form.addRow(CaptionLabel(f'{label}:', card), row)
                continue

            box = CheckBox('启用', card)
            box.toggled.connect(self._auto_save)
            self._bool_widgets[(task_name, feature_name)] = box
            form.addRow(CaptionLabel(f'{label}:', card), box)

        layout.addLayout(form)
        return card

    @staticmethod
    def _normalize_list_value(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            text = str(raw or '').strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _read_list(self, task_name: str, feature_name: str) -> list[str]:
        task_cfg = self.config.tasks.get(task_name)
        if task_cfg is None:
            return []
        feature_map = getattr(task_cfg, 'features', {}) or {}
        if not isinstance(feature_map, dict):
            return []
        return self._normalize_list_value(feature_map.get(feature_name, []))

    def _write_list(self, task_name: str, feature_name: str, values: list[str]) -> None:
        task_cfg = self.config.tasks.get(task_name)
        if task_cfg is None:
            return
        feature_map = dict(getattr(task_cfg, 'features', {}) or {})
        feature_map[feature_name] = self._normalize_list_value(values)
        task_cfg.features = feature_map
        self.config.save()
        self.config_changed.emit(self.config)
        self._refresh_list_summary(task_name, feature_name)

    def _refresh_list_summary(self, task_name: str, feature_name: str) -> None:
        label = self._list_summary.get((task_name, feature_name))
        if label is None:
            return
        count = len(self._read_list(task_name, feature_name))
        label.setText('未配置' if count <= 0 else f'已配置 {count} 条')

    def _open_list_editor(self, task_name: str, feature_name: str) -> None:
        title = f'{task_name}.{feature_name}'
        dialog = _ListEditorDialog(title=title, values=self._read_list(task_name, feature_name), parent=self)
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        self._write_list(task_name, feature_name, dialog.values())

    def _auto_save(self) -> None:
        if self._loading:
            return
        for (task_name, feature_name), box in self._bool_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = dict(getattr(task_cfg, 'features', {}) or {})
            if is_feature_forced_off(task_name, feature_name):
                feature_map[feature_name] = False
                box.setChecked(False)
                box.setEnabled(False)
            else:
                feature_map[feature_name] = bool(box.isChecked())
            task_cfg.features = feature_map
        self.config.save()
        self.config_changed.emit(self.config)

    def _load_config(self) -> None:
        for (task_name, feature_name), box in self._bool_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = getattr(task_cfg, 'features', {}) or {}
            forced = is_feature_forced_off(task_name, feature_name)
            box.setEnabled(not forced)
            box.setChecked(False if forced else bool(feature_map.get(feature_name, False)))
            if forced:
                box.setToolTip('该功能固定禁用')
        for task_name, feature_name in self._list_summary.keys():
            self._refresh_list_summary(task_name, feature_name)

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._loading = True
        self._load_config()
        self._loading = False
