"""土地详情面板。"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QSignalBlocker, QTimer, Qt
from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionGroupBox,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.no_wheel_combo_box import NoWheelComboBox


@dataclass(frozen=True)
class LandStateMeta:
    """地块状态元数据。"""

    value: str
    label: str
    bg_color: str
    border_color: str
    text_color: str = '#1f2937'


LAND_STATE_META: dict[str, LandStateMeta] = {
    # 颜色参考 templates/qq/land 下模板：
    # black=(92,67,42) red=(223,87,55) gold=(249,203,50) stand=(178,131,74)
    # 目录无“未扩建”模板，使用 stand 同色系浅化色，并以无背景+虚线框表现。
    'unbuilt': LandStateMeta('unbuilt', '未扩建', '#D9C3A5', '#B2834A', '#5C432A'),
    'normal': LandStateMeta('normal', '普通', '#C39A64', '#7A552D', '#F9F2E7'),
    'red': LandStateMeta('red', '红', '#DF5737', '#9D3E27', '#FFF7F3'),
    'black': LandStateMeta('black', '黑', '#5C432A', '#3B2B1C', '#F8F5EF'),
    'gold': LandStateMeta('gold', '金', '#F9CB32', '#B78918', '#3C2B05'),
}

LAND_STATE_ORDER: list[str] = ['unbuilt', 'normal', 'red', 'black', 'gold']
LAND_STATE_ALIASES: dict[str, str] = {
    '未扩建': 'unbuilt',
    '普通': 'normal',
    '红': 'red',
    '黑': 'black',
    '金': 'gold',
}
LAND_STATE_RANK: dict[str, int] = {
    'unbuilt': 0,
    'normal': 1,
    'red': 2,
    'black': 3,
    'gold': 4,
}


class LandCell(QWidget):
    """单个地块格子。"""

    def __init__(self, plot_id: str, parent=None):
        super().__init__(parent)
        self.plot_id = plot_id
        self._init_ui()
        self.set_data({'state': 'unbuilt'})
        self.set_editable(False)

    def _init_ui(self) -> None:
        self.setObjectName('landCell')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(90)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)
        header.addStretch()
        self._plot_label = QLabel(self.plot_id)
        self._plot_label.setObjectName('plotLabel')
        header.addWidget(self._plot_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        root.addStretch()

        self._state_view = QLabel('')
        self._state_view.setObjectName('stateView')
        self._state_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_view.setFixedHeight(24)
        root.addWidget(self._state_view)

        self._state_combo = NoWheelComboBox()
        self._state_combo.setObjectName('stateCombo')
        self._state_combo.setFixedHeight(24)
        self._state_combo.setMaxVisibleItems(len(LAND_STATE_ORDER))
        for state in LAND_STATE_ORDER:
            meta = LAND_STATE_META[state]
            self._state_combo.addItem(meta.label, state)
        self._state_combo.currentIndexChanged.connect(self._on_state_changed)
        self._state_combo.view().setSpacing(2)
        root.addWidget(self._state_combo)

    @staticmethod
    def _normalize_state(raw: object) -> str:
        value = str(raw or '').strip()
        if not value:
            return 'unbuilt'
        key = value.lower()
        if key in LAND_STATE_META:
            return key
        return LAND_STATE_ALIASES.get(value, 'unbuilt')

    def _current_state(self) -> str:
        return self._normalize_state(self._state_combo.currentData())

    def _on_state_changed(self, _index: int) -> None:
        state = self._current_state()
        self._apply_state_style(state)
        self._state_view.setText(LAND_STATE_META.get(state, LAND_STATE_META['unbuilt']).label)

    def _apply_state_style(self, state: str) -> None:
        meta = LAND_STATE_META.get(state, LAND_STATE_META['unbuilt'])
        if state == 'unbuilt':
            cell_style = (
                'background-color: transparent;'
                'border-color: #cbd5e1;'
                'border-width: 2px;'
                'border-style: dashed;'
                'border-radius: 10px;'
            )
        else:
            cell_style = f'background-color: {meta.bg_color};border: 1px solid {meta.border_color};border-radius: 10px;'
        self.setStyleSheet(cell_style)
        self._plot_label.setStyleSheet(
            f'color: {meta.text_color}; font-size: 12px; font-weight: 700; border: none; background: transparent;'
        )
        self._state_view.setStyleSheet(
            'background: rgba(255, 255, 255, 0.90);'
            'border: 1px solid rgba(15, 23, 42, 0.22);'
            'border-radius: 4px;'
            'color: #0f172a; font-size: 12px; font-weight: 600; padding: 1px 6px;'
        )
        self._state_combo.setStyleSheet(
            'QComboBox {'
            'combobox-popup: 0;'
            'background: rgba(255, 255, 255, 0.90);'
            'border: 1px solid rgba(15, 23, 42, 0.22);'
            'border-radius: 4px;'
            'color: #0f172a; font-size: 12px; font-weight: 600; padding: 1px 24px 1px 6px;'
            '}'
            'QComboBox::drop-down {'
            'subcontrol-origin: padding; subcontrol-position: top right; width: 20px; border: none;'
            '}'
            'QComboBox QAbstractItemView {'
            'background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px;'
            'outline: 0;'
            '}'
            'QComboBox QAbstractItemView::item {'
            'min-height: 24px; padding: 4px 8px; margin: 1px 0;'
            '}'
            'QComboBox QAbstractItemView::item:selected {'
            'background: #dbeafe; color: #1d4ed8;'
            '}'
        )

    def set_data(self, data: dict[str, object]) -> None:
        state = self._normalize_state(data.get('state', 'unbuilt'))

        state_index = self._state_combo.findData(state)
        if state_index < 0:
            state_index = 0

        with QSignalBlocker(self._state_combo):
            self._state_combo.setCurrentIndex(state_index)

        self._state_view.setText(LAND_STATE_META.get(state, LAND_STATE_META['unbuilt']).label)
        self._apply_state_style(state)

    def get_data(self) -> dict[str, object]:
        return {
            'plot_id': self.plot_id,
            'state': self._current_state(),
        }

    def set_editable(self, editable: bool) -> None:
        is_edit = bool(editable)
        self._state_combo.setVisible(is_edit)
        self._state_combo.setEnabled(is_edit)
        self._state_view.setVisible(False)


class LandDetailPanel(QWidget):
    """土地详情标签页。"""

    COL_COUNT = 6
    ROW_COUNT = 4
    CELL_GAP = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cells: dict[str, LandCell] = {}
        self._editing = False
        self._init_ui()
        self.load_mock_data()
        self._set_edit_mode(False)

    @staticmethod
    def _plot_id_at(row_index: int, col_index: int) -> str:
        # 视觉从左到右显示为 6 -> 1，确保右上角是 1-1、左上角是 6-1。
        display_col = 6 - col_index
        return f'{display_col}-{row_index + 1}'

    @classmethod
    def _plot_ids_visual_order(cls) -> list[str]:
        return [cls._plot_id_at(row, col) for row in range(cls.ROW_COUNT) for col in range(cls.COL_COUNT)]

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._board_group = QGroupBox('土地信息')
        self._board_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._edit_btn = QPushButton('编辑', self._board_group)
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.clicked.connect(self._on_toggle_edit)
        self._edit_btn.raise_()

        board_layout = QVBoxLayout(self._board_group)
        board_layout.setContentsMargins(self.CELL_GAP, self.CELL_GAP, self.CELL_GAP, self.CELL_GAP)
        board_layout.setSpacing(0)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self.CELL_GAP)
        self._grid.setVerticalSpacing(self.CELL_GAP)

        for row in range(self.ROW_COUNT):
            for col in range(self.COL_COUNT):
                plot_id = self._plot_id_at(row, col)
                cell = LandCell(plot_id)
                self._grid.addWidget(cell, row, col)
                self._cells[plot_id] = cell

        for col in range(self.COL_COUNT):
            self._grid.setColumnStretch(col, 1)

        board_layout.addLayout(self._grid)
        root.addWidget(self._board_group, 0)
        root.addStretch(1)
        self._update_edit_button_size()
        self._apply_edit_button_style()
        QTimer.singleShot(0, self._position_edit_button)

    def _update_edit_button_size(self) -> None:
        text = self._edit_btn.text()
        fm = self._edit_btn.fontMetrics()
        text_w = fm.horizontalAdvance(text)
        text_h = fm.height()
        # 文本宽度自适应，留白放大，避免中文两侧被裁切。
        self._edit_btn.setFixedWidth(max(54, text_w + 24))
        # 增加上下边框到文字间距（垂直留白）。
        self._edit_btn.setFixedHeight(max(22, text_h + 10))

    def _apply_edit_button_style(self) -> None:
        if self._editing:
            base_bg = '#22c55e'
            hover_bg = '#16a34a'
            pressed_bg = '#15803d'
            border = '#15803d'
            text = '#ffffff'
        else:
            base_bg = '#3b82f6'
            hover_bg = '#2563eb'
            pressed_bg = '#1d4ed8'
            border = '#1d4ed8'
            text = '#ffffff'
        self._edit_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {base_bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {hover_bg};
                border-color: {hover_bg};
            }}
            QPushButton:pressed {{
                background: {pressed_bg};
                border-color: {pressed_bg};
            }}
            """
        )

    def _position_edit_button(self) -> None:
        option = QStyleOptionGroupBox()
        option.initFrom(self._board_group)
        option.text = self._board_group.title()
        title_rect = self._board_group.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox,
            option,
            QStyle.SubControl.SC_GroupBoxLabel,
            self._board_group,
        )
        right = self._board_group.width() - self._edit_btn.width() - 12
        # 纵向按标题行居中对齐。
        y = max(0, int(title_rect.center().y() - self._edit_btn.height() / 2))
        self._edit_btn.move(max(12, right), y)
        self._edit_btn.raise_()

    def _set_edit_mode(self, editable: bool) -> None:
        self._editing = bool(editable)
        self._edit_btn.setText('保存' if self._editing else '编辑')
        self._update_edit_button_size()
        self._apply_edit_button_style()
        self._position_edit_button()
        for cell in self._cells.values():
            cell.set_editable(self._editing)

    @staticmethod
    def _plot_logic_key(plot_id: str) -> tuple[int, int]:
        # 逻辑排序：1-1 1-2 1-3 1-4 2-1 ...
        left, _, right = str(plot_id or '').partition('-')
        try:
            return int(left), int(right)
        except Exception:
            return 999, 999

    def _validate_before_save(self) -> tuple[bool, str]:
        ordered = sorted(self._cells.values(), key=lambda c: self._plot_logic_key(c.plot_id))
        prev_cell: LandCell | None = None
        prev_rank = -1
        for cell in ordered:
            state = str(cell.get_data().get('state', 'unbuilt'))
            rank = int(LAND_STATE_RANK.get(state, 0))
            if prev_cell is not None and prev_rank < rank:
                prev_state = str(prev_cell.get_data().get('state', 'unbuilt'))
                prev_label = LAND_STATE_META.get(prev_state, LAND_STATE_META['unbuilt']).label
                curr_label = LAND_STATE_META.get(state, LAND_STATE_META['unbuilt']).label
                return (
                    False,
                    f'排序不合法：{prev_cell.plot_id}({prev_label}) < {cell.plot_id}({curr_label})\n'
                    '请保证前面的地块等级不低于后面的地块。',
                )
            prev_cell = cell
            prev_rank = rank
        return True, ''

    def _on_toggle_edit(self) -> None:
        if self._editing:
            ok, message = self._validate_before_save()
            if not ok:
                QMessageBox.warning(self, '保存失败', message)
                return
        self._set_edit_mode(not self._editing)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_edit_button()

    def set_land_data(self, items: list[dict[str, object]]) -> None:
        """按 `plot_id` 批量设置地块数据。"""
        for item in items:
            if not isinstance(item, dict):
                continue
            plot_id = str(item.get('plot_id', '')).strip()
            cell = self._cells.get(plot_id)
            if cell is None:
                continue
            cell.set_data(item)

    def get_land_data(self) -> list[dict[str, object]]:
        """读取当前全部地块数据。"""
        return [self._cells[plot_id].get_data() for plot_id in self._plot_ids_visual_order() if plot_id in self._cells]

    def load_mock_data(self) -> None:
        """初始化一份 24 格假数据，用于 UI 预览。"""
        mock_states = [
            'black',
            'black',
            'black',
            'gold',
            'gold',
            'normal',
            'black',
            'black',
            'black',
            'black',
            'gold',
            'gold',
            'red',
            'black',
            'black',
            'black',
            'gold',
            'unbuilt',
            'red',
            'black',
            'black',
            'black',
            'normal',
            'gold',
        ]
        payload: list[dict[str, object]] = []
        for idx, plot_id in enumerate(self._plot_ids_visual_order()):
            payload.append(
                {
                    'plot_id': plot_id,
                    'state': mock_states[idx % len(mock_states)],
                }
            )
        self.set_land_data(payload)
