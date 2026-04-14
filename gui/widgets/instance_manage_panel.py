"""Fluent 实例管理页面。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QGridLayout, QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, FluentIcon, ListWidget, PrimaryPushButton, PushButton


class InstanceManagePanel(QWidget):
    """实例管理（右侧页面版）。"""

    open_requested = pyqtSignal(str)
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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        card = CardWidget(self)
        root.addWidget(card, 1)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(BodyLabel('实例管理'))
        layout.addWidget(CaptionLabel('新增 / 删除 / 克隆 / 重命名 / 打开实例'))

        self._list = ListWidget(card)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemDoubleClicked.connect(lambda _: self._emit_open())
        self._list.itemSelectionChanged.connect(self._refresh_summary)
        layout.addWidget(self._list, 1)

        self._summary = CaptionLabel('未选择实例', card)
        layout.addWidget(self._summary)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._btn_open = PrimaryPushButton('打开实例', card)
        self._btn_create = PrimaryPushButton('新增', card)
        self._btn_delete = PushButton('删除', card)
        self._btn_clone = PushButton('克隆', card)
        self._btn_rename = PushButton('重命名', card)
        self._btn_open.setIcon(FluentIcon.PLAY)
        self._btn_create.setIcon(FluentIcon.ADD)
        self._btn_delete.setIcon(FluentIcon.DELETE)
        self._btn_clone.setIcon(FluentIcon.COPY)
        self._btn_rename.setIcon(FluentIcon.EDIT)
        for btn in (self._btn_open, self._btn_create, self._btn_delete, self._btn_clone, self._btn_rename):
            btn.setFixedHeight(34)
        grid.addWidget(self._btn_open, 0, 0)
        grid.addWidget(self._btn_create, 0, 1)
        grid.addWidget(self._btn_delete, 1, 0)
        grid.addWidget(self._btn_clone, 1, 1)
        grid.addWidget(self._btn_rename, 2, 0, 1, 2)
        layout.addLayout(grid)

        self._btn_open.clicked.connect(self._emit_open)
        self._btn_create.clicked.connect(self.create_requested.emit)
        self._btn_delete.clicked.connect(self._emit_delete)
        self._btn_clone.clicked.connect(self._emit_clone)
        self._btn_rename.clicked.connect(self._emit_rename)

    def _current_instance_id(self) -> str:
        item = self._list.currentItem()
        if item is None:
            return ''
        return str(item.data(self.ROLE_INSTANCE_ID) or '')

    @staticmethod
    def _state_tip(state: str) -> str:
        return {
            'running': '运行中',
            'paused': '已暂停',
            'idle': '空闲',
            'error': '异常',
        }.get(str(state or 'idle').lower(), '未知状态')

    def _refresh_summary(self) -> None:
        iid = self._current_instance_id()
        if not iid:
            self._summary.setText('未选择实例')
            return
        name = self._id_to_name.get(iid, iid)
        state = self._state_tip(self._id_to_state.get(iid, 'idle'))
        self._summary.setText(f'当前选择: {name} ({state})')

    def _emit_open(self) -> None:
        iid = self._current_instance_id()
        if iid:
            self.open_requested.emit(iid)

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

    def set_instances(self, instances: list[dict[str, Any]]) -> None:
        current = self._current_instance_id()
        self._list.blockSignals(True)
        self._list.clear()
        self._id_to_state.clear()
        self._id_to_name.clear()
        for data in instances:
            iid = str(data.get('id') or '')
            if not iid:
                continue
            name = str(data.get('name') or iid)
            state = str(data.get('state') or 'idle')
            self._id_to_state[iid] = state
            self._id_to_name[iid] = name
            mark = {'running': '●', 'paused': '◐', 'idle': '○', 'error': '✖'}.get(state, '○')
            item = QListWidgetItem(f'{mark} {name}')
            item.setData(self.ROLE_INSTANCE_ID, iid)
            item.setData(self.ROLE_INSTANCE_NAME, name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._list.addItem(item)
            if iid == current:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)
        self._refresh_summary()

    def set_active_instance(self, instance_id: str) -> None:
        iid = str(instance_id or '')
        if not iid:
            return
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if str(item.data(self.ROLE_INSTANCE_ID) or '') == iid:
                self._list.setCurrentItem(item)
                break
        self._list.blockSignals(False)
        self._refresh_summary()

    def update_instance_state(self, instance_id: str, state: str, name: str | None = None) -> None:
        iid = str(instance_id or '')
        if not iid:
            return
        self._id_to_state[iid] = str(state or 'idle')
        if name:
            self._id_to_name[iid] = str(name)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if str(item.data(self.ROLE_INSTANCE_ID) or '') != iid:
                continue
            display_name = self._id_to_name.get(iid, str(item.data(self.ROLE_INSTANCE_NAME) or iid))
            mark = {'running': '●', 'paused': '◐', 'idle': '○', 'error': '✖'}.get(self._id_to_state[iid], '○')
            item.setData(self.ROLE_INSTANCE_NAME, display_name)
            item.setText(f'{mark} {display_name}')
            break
        self._refresh_summary()
