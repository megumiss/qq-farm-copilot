"""最右侧竖向实例栏。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
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
    ROLE_INSTANCE_ID = 0x0100
    ROLE_INSTANCE_NAME = 0x0101

    def __init__(self, parent=None):
        super().__init__(parent)
        self._id_to_state: dict[str, str] = {}
        self._id_to_name: dict[str, str] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName('instanceSidebar')
        self.setStyleSheet(
            """
            QWidget#instanceSidebar {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
            }
            QLabel#instanceTitle {
                color: #334155;
                font-weight: 700;
                font-size: 13px;
            }
            QListWidget#instanceList {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background: #ffffff;
                padding: 4px;
                outline: none;
            }
            QListWidget#instanceList::item {
                min-height: 28px;
                border-radius: 6px;
                padding: 4px 8px;
                color: #334155;
                text-align: left;
            }
            QListWidget#instanceList::item:selected {
                background: #dbeafe;
                color: #1d4ed8;
                font-weight: 600;
            }
            QListWidget#instanceList::item:hover:!selected {
                background: #eef2f7;
            }
            QFrame#actionsWrap {
                border-top: 1px solid #eef2f7;
                padding-top: 6px;
            }
            QPushButton#instanceActionBtn {
                background: #f8fafc;
                border: 1px solid #dbe3ef;
                color: #334155;
                border-radius: 8px;
                font-weight: 600;
                padding: 0 6px;
            }
            QPushButton#instanceActionBtn:hover {
                background: #eef2ff;
                border-color: #c7d2fe;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._title = QLabel('实例')
        self._title.setObjectName('instanceTitle')
        root.addWidget(self._title)

        self._list = QListWidget()
        self._list.setObjectName('instanceList')
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._list, 1)

        self._actions_wrap = QFrame()
        self._actions_wrap.setObjectName('actionsWrap')
        actions = QVBoxLayout(self._actions_wrap)
        actions.setContentsMargins(0, 0, 0, 0)
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
            btn.setObjectName('instanceActionBtn')
            btn.setFixedHeight(30)
            actions.addWidget(btn)

        root.addWidget(self._actions_wrap, 0)

    def _current_instance_id(self) -> str:
        item = self._list.currentItem()
        if item is None:
            return ''
        return str(item.data(self.ROLE_INSTANCE_ID) or '')

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
    def _state_tip(state: str) -> str:
        return {
            'running': '运行中',
            'paused': '已暂停',
            'idle': '空闲',
        }.get(str(state or 'idle').lower(), '未知状态')

    def set_instances(self, instances: list[dict[str, Any]]) -> None:
        """刷新实例列表。"""
        current = self._current_instance_id()
        self._list.blockSignals(True)
        self._list.clear()
        self._id_to_state.clear()
        self._id_to_name.clear()
        for item in instances:
            iid = str(item.get('id') or '')
            if not iid:
                continue
            name = str(item.get('name') or iid)
            state = str(item.get('state') or 'idle')
            self._id_to_state[iid] = state
            self._id_to_name[iid] = name
            ui_item = QListWidgetItem(name)
            ui_item.setData(self.ROLE_INSTANCE_ID, iid)
            ui_item.setData(self.ROLE_INSTANCE_NAME, name)
            ui_item.setToolTip(f'{name} - {self._state_tip(state)}')
            ui_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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
            if str(item.data(self.ROLE_INSTANCE_ID) or '') == iid:
                self._list.setCurrentItem(item)
                break
        self._list.blockSignals(False)

    def update_instance_state(self, instance_id: str, state: str, name: str | None = None) -> None:
        """更新实例状态显示。"""
        iid = str(instance_id or '')
        if not iid:
            return
        self._id_to_state[iid] = str(state or 'idle')
        if name:
            self._id_to_name[iid] = str(name)
        for index in range(self._list.count()):
            item = self._list.item(index)
            if str(item.data(self.ROLE_INSTANCE_ID) or '') != iid:
                continue
            display_name = str(self._id_to_name.get(iid) or item.data(self.ROLE_INSTANCE_NAME) or iid)
            item.setData(self.ROLE_INSTANCE_NAME, display_name)
            item.setText(display_name)
            item.setToolTip(f'{display_name} - {self._state_tip(self._id_to_state[iid])}')
            break
