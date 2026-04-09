"""最右侧竖向实例栏。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class InstanceSidebar(QWidget):
    """实例列表与实例操作栏。"""

    instance_selected = pyqtSignal(str)
    create_requested = pyqtSignal()
    delete_requested = pyqtSignal(str)
    clone_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._id_to_state: dict[str, str] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel('实例')
        title.setStyleSheet('font-weight: 700; color: #334155;')
        root.addWidget(title)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.setMinimumWidth(220)
        root.addWidget(self._list, 1)

        actions = QVBoxLayout()
        actions.setSpacing(6)

        self._btn_create = QPushButton('新增')
        self._btn_delete = QPushButton('删除')
        self._btn_clone = QPushButton('克隆')
        self._btn_rename = QPushButton('重命名')

        self._btn_create.clicked.connect(self.create_requested.emit)
        self._btn_delete.clicked.connect(self._emit_delete)
        self._btn_clone.clicked.connect(self._emit_clone)
        self._btn_rename.clicked.connect(self._emit_rename)

        for btn in (self._btn_create, self._btn_delete, self._btn_clone, self._btn_rename):
            btn.setFixedHeight(32)
            actions.addWidget(btn)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addLayout(actions)
        root.addLayout(row)

    def _current_instance_id(self) -> str:
        item = self._list.currentItem()
        if item is None:
            return ''
        return str(item.data(0x0100) or '')

    def _emit_delete(self) -> None:
        iid = self._current_instance_id()
        if iid:
            self.delete_requested.emit(iid)

    def _emit_clone(self) -> None:
        iid = self._current_instance_id()
        if iid:
            self.clone_requested.emit(iid)

    def _emit_rename(self) -> None:
        iid = self._current_instance_id()
        if iid:
            self.rename_requested.emit(iid)

    def _on_selection_changed(self) -> None:
        iid = self._current_instance_id()
        if iid:
            self.instance_selected.emit(iid)

    @staticmethod
    def _display_name(name: str, state: str) -> str:
        state_text = {
            'running': '●',
            'paused': '◐',
            'idle': '○',
        }.get(str(state or 'idle').lower(), '○')
        return f'{state_text} {name}'

    def set_instances(self, instances: list[dict[str, Any]]) -> None:
        """刷新实例列表。"""
        current = self._current_instance_id()
        self._list.blockSignals(True)
        self._list.clear()
        self._id_to_state.clear()
        for item in instances:
            iid = str(item.get('id') or '')
            if not iid:
                continue
            name = str(item.get('name') or iid)
            state = str(item.get('state') or 'idle')
            self._id_to_state[iid] = state
            ui_item = QListWidgetItem(self._display_name(name, state))
            ui_item.setData(0x0100, iid)
            self._list.addItem(ui_item)
            if iid == current:
                self._list.setCurrentItem(ui_item)
        self._list.blockSignals(False)

    def set_active_instance(self, instance_id: str) -> None:
        """高亮当前实例。"""
        iid = str(instance_id or '')
        if not iid:
            return
        self._list.blockSignals(True)
        for index in range(self._list.count()):
            item = self._list.item(index)
            if str(item.data(0x0100) or '') == iid:
                self._list.setCurrentItem(item)
                break
        self._list.blockSignals(False)

    def update_instance_state(self, instance_id: str, state: str, name: str | None = None) -> None:
        """更新实例状态显示。"""
        iid = str(instance_id or '')
        if not iid:
            return
        self._id_to_state[iid] = str(state or 'idle')
        for index in range(self._list.count()):
            item = self._list.item(index)
            if str(item.data(0x0100) or '') != iid:
                continue
            text = item.text()
            current_name = text[2:] if len(text) > 2 else text
            display_name = str(name or current_name).strip()
            item.setText(self._display_name(display_name, self._id_to_state[iid]))
            break
