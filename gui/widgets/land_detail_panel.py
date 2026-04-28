"""土地详情面板。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PyQt6.QtCore import QSignalBlocker, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    IconWidget,
    MessageBox,
    ScrollArea,
    StrongBodyLabel,
    ToolButton,
)

from gui.widgets.fluent_container import StableElevatedCardWidget, TransparentCardContainer
from models.config import AppConfig


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
LAND_COUNTDOWN_PATTERN = re.compile(r'^(\d{2}):(\d{2}):(\d{2})$')


class LandCell(QWidget):
    """单个地块格子。"""

    state_changed = pyqtSignal(str, str)

    def __init__(self, plot_id: str, parent=None):
        super().__init__(parent)
        self.plot_id = str(plot_id)
        self._countdown_seconds = 0
        self._need_upgrade = False
        self._need_planting = False
        self._init_ui()
        self.set_data(
            {
                'level': 'unbuilt',
                'maturity_countdown': '',
                'need_upgrade': False,
                'need_planting': False,
            }
        )
        self.set_editable(False)

    def _init_ui(self) -> None:
        self.setObjectName('landCell')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(96)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16.0)
        shadow.setOffset(0.0, 2.0)
        shadow.setColor(QColor(15, 23, 42, 60))
        self.setGraphicsEffect(shadow)
        self._shadow_effect = shadow

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        badge_col = QVBoxLayout()
        badge_col.setContentsMargins(0, 0, 0, 0)
        badge_col.setSpacing(3)
        self._need_planting_badge = CaptionLabel('待播种', self)
        self._need_planting_badge.setObjectName('needPlantingBadge')
        self._need_planting_badge.setStyleSheet(
            'background: rgba(22, 163, 74, 0.92);'
            'border: 1px solid rgba(21, 128, 61, 0.95);'
            'border-radius: 6px;'
            'color: #f0fdf4; font-size: 10px; font-weight: 700;'
            'padding: 1px 4px;'
        )
        self._need_planting_badge.setVisible(False)
        badge_col.addWidget(self._need_planting_badge, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._need_upgrade_badge = CaptionLabel('待升级', self)
        self._need_upgrade_badge.setObjectName('needUpgradeBadge')
        self._need_upgrade_badge.setStyleSheet(
            'background: rgba(220, 38, 38, 0.92);'
            'border: 1px solid rgba(153, 27, 27, 0.95);'
            'border-radius: 6px;'
            'color: #fff7ed; font-size: 10px; font-weight: 700;'
            'padding: 1px 4px;'
        )
        self._need_upgrade_badge.setVisible(False)
        badge_col.addWidget(self._need_upgrade_badge, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        header.addLayout(badge_col)
        header.addStretch()
        self._plot_label = CaptionLabel(self.plot_id, self)
        self._plot_label.setObjectName('plotLabel')
        self._plot_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        header.addWidget(self._plot_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        root.addStretch(1)

        self._state_view = BodyLabel('', self)
        self._state_view.setObjectName('stateView')
        self._state_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_view.setFixedHeight(26)
        root.addWidget(self._state_view)

        self._state_combo = ComboBox(self)
        self._state_combo.setObjectName('stateCombo')
        self._state_combo.setFixedHeight(30)
        self._state_combo.setMaxVisibleItems(len(LAND_STATE_ORDER))
        for state in LAND_STATE_ORDER:
            meta = LAND_STATE_META[state]
            self._state_combo.addItem(meta.label, userData=state)
        self._state_combo.currentIndexChanged.connect(self._on_state_changed)
        root.addWidget(self._state_combo)

        self._countdown_view = CaptionLabel('--:--:--', self)
        self._countdown_view.setObjectName('countdownView')
        self._countdown_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown_view.setStyleSheet(
            'background: rgba(255, 255, 255, 0.85);'
            'border: 1px solid rgba(15, 23, 42, 0.12);'
            'border-radius: 6px;'
            'color: #0f172a; font-size: 11px; font-weight: 600;'
            'padding: 2px 4px;'
        )
        root.addWidget(self._countdown_view)

    @staticmethod
    def _normalize_state(raw: object) -> str:
        value = str(raw or '').strip()
        if not value:
            return 'unbuilt'
        key = value.lower()
        if key in LAND_STATE_META:
            return key
        return LAND_STATE_ALIASES.get(value, 'unbuilt')

    @staticmethod
    def _normalize_need_upgrade(raw: object) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return False
        text = str(raw).strip().lower()
        if not text:
            return False
        return text in {'1', 'true', 'yes', 'y', 'on', '是'}

    @staticmethod
    def _normalize_need_planting(raw: object) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return False
        text = str(raw).strip().lower()
        if not text:
            return False
        return text in {'1', 'true', 'yes', 'y', 'on', '是'}

    def _current_state(self) -> str:
        return self._normalize_state(self._state_combo.currentData())

    def _on_state_changed(self, _index: int) -> None:
        state = self._current_state()
        self._apply_state_style(state)
        self._state_view.setText(LAND_STATE_META.get(state, LAND_STATE_META['unbuilt']).label)
        self.state_changed.emit(self.plot_id, state)

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
            cell_style = f'background-color: {meta.bg_color};border: none;border-radius: 10px;'
        self.setStyleSheet(cell_style)
        self._plot_label.setStyleSheet(
            f'color: {meta.text_color}; font-size: 12px; font-weight: 700; border: none; background: transparent;'
        )
        self._state_view.setStyleSheet(
            'background: rgba(255, 255, 255, 0.92);'
            'border: 1px solid rgba(15, 23, 42, 0.20);'
            'border-radius: 6px;'
            'color: #0f172a; font-size: 12px; font-weight: 600;'
            'padding: 2px 6px;'
        )

    @staticmethod
    def _normalize_countdown_text(raw: object) -> str:
        text = str(raw or '').strip()
        match = LAND_COUNTDOWN_PATTERN.match(text)
        if not match:
            return ''
        hour = int(match.group(1))
        minute = int(match.group(2))
        second = int(match.group(3))
        if hour < 0 or hour > 99 or minute < 0 or minute > 59 or second < 0 or second > 59:
            return ''
        return f'{hour:02d}:{minute:02d}:{second:02d}'

    @staticmethod
    def _countdown_to_seconds(text: str) -> int:
        match = LAND_COUNTDOWN_PATTERN.match(str(text or '').strip())
        if not match:
            return 0
        hour = int(match.group(1))
        minute = int(match.group(2))
        second = int(match.group(3))
        return hour * 3600 + minute * 60 + second

    @staticmethod
    def _seconds_to_countdown(seconds: int) -> str:
        value = max(0, int(seconds))
        hour = min(99, value // 3600)
        remain = value % 3600
        minute = remain // 60
        second = remain % 60
        return f'{hour:02d}:{minute:02d}:{second:02d}'

    def _current_countdown_text(self) -> str:
        if self._countdown_seconds <= 0:
            return ''
        return self._seconds_to_countdown(self._countdown_seconds)

    def set_data(self, data: dict[str, object]) -> None:
        state = self._normalize_state(data.get('level', 'unbuilt'))
        countdown_raw = data.get('maturity_countdown', self._current_countdown_text())
        countdown = self._normalize_countdown_text(countdown_raw)
        need_upgrade_raw = data.get('need_upgrade', self._need_upgrade)
        self._need_upgrade = self._normalize_need_upgrade(need_upgrade_raw)
        need_planting_raw = data.get('need_planting', self._need_planting)
        self._need_planting = self._normalize_need_planting(need_planting_raw)
        self._countdown_seconds = self._countdown_to_seconds(countdown)
        state_index = self._state_combo.findData(state)
        if state_index < 0:
            state_index = 0
        with QSignalBlocker(self._state_combo):
            self._state_combo.setCurrentIndex(state_index)
        self._state_view.setText(LAND_STATE_META.get(state, LAND_STATE_META['unbuilt']).label)
        self._countdown_view.setText(countdown or '--:--:--')
        self._need_upgrade_badge.setVisible(self._need_upgrade)
        self._need_planting_badge.setVisible(self._need_planting)
        self._apply_state_style(state)

    def get_data(self) -> dict[str, object]:
        return {
            'plot_id': self.plot_id,
            'level': self._current_state(),
            'maturity_countdown': self._current_countdown_text(),
            'need_upgrade': bool(self._need_upgrade),
            'need_planting': bool(self._need_planting),
        }

    def tick_countdown(self) -> bool:
        """每秒递减一次成熟倒计时，返回是否有变更。"""
        if self._countdown_seconds <= 0:
            return False
        self._countdown_seconds = max(0, int(self._countdown_seconds) - 1)
        self._countdown_view.setText(self._current_countdown_text() or '--:--:--')
        return True

    def set_editable(self, editable: bool) -> None:
        is_edit = bool(editable)
        self._state_combo.setVisible(is_edit)
        self._state_combo.setEnabled(is_edit)
        self._state_view.setVisible(False)


class LandDetailPanel(QWidget):
    """土地详情标签页。"""

    config_changed = pyqtSignal(object)

    COL_COUNT = 6
    ROW_COUNT = 4
    CELL_GAP = 8

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._cells: dict[str, LandCell] = {}
        self._profile_value_labels: dict[str, StrongBodyLabel] = {}
        self._editing = False
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._init_ui()
        self._load_from_config()
        self._set_edit_mode(False)
        self._countdown_timer.start()

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

        self._profile_card = StableElevatedCardWidget(self)
        self._profile_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._apply_card_style(self._profile_card, 'landProfileCard')
        content_layout.addWidget(self._profile_card)

        profile_layout = QVBoxLayout(self._profile_card)
        profile_layout.setContentsMargins(12, 10, 12, 10)
        profile_layout.setSpacing(9)

        profile_header = QWidget(self._profile_card)
        profile_header_layout = QHBoxLayout(profile_header)
        profile_header_layout.setContentsMargins(0, 0, 0, 0)
        profile_header_layout.setSpacing(8)
        profile_icon = IconWidget(FluentIcon.PEOPLE, profile_header)
        profile_icon.setFixedSize(14, 14)
        profile_header_layout.addWidget(profile_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        profile_title = BodyLabel('个人信息', profile_header)
        profile_title.setStyleSheet('font-weight: 700; font-size: 14px; color: #1e293b;')
        profile_header_layout.addWidget(profile_title, 0, Qt.AlignmentFlag.AlignVCenter)
        profile_header_layout.addStretch(1)
        profile_layout.addWidget(profile_header)

        profile_divider = QFrame(self._profile_card)
        profile_divider.setObjectName('landProfileCardDivider')
        profile_divider.setFixedHeight(1)
        profile_divider.setStyleSheet(
            'QFrame#landProfileCardDivider { background-color: rgba(37, 99, 235, 0.10); border: none; }'
        )
        profile_layout.addWidget(profile_divider)

        profile_grid = QGridLayout()
        profile_grid.setContentsMargins(0, 2, 0, 0)
        profile_grid.setHorizontalSpacing(8)
        profile_grid.setVerticalSpacing(6)
        profile_fields = [
            ('level', '等级'),
            ('gold', '金币'),
            ('coupon', '点券'),
            ('exp', '经验'),
        ]
        for idx, (field_key, field_title) in enumerate(profile_fields):
            profile_grid.addWidget(self._build_profile_cell(field_key, field_title), 0, idx)
            profile_grid.setColumnStretch(idx, 1)
        profile_layout.addLayout(profile_grid)

        self._board_card = StableElevatedCardWidget(self)
        self._board_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._apply_card_style(self._board_card, 'landDetailCard')
        content_layout.addWidget(self._board_card)
        content_layout.addStretch()

        board_layout = QVBoxLayout(self._board_card)
        board_layout.setContentsMargins(12, 10, 12, 10)
        board_layout.setSpacing(9)

        card_header = QWidget(self._board_card)
        card_header_layout = QHBoxLayout(card_header)
        card_header_layout.setContentsMargins(0, 0, 0, 0)
        card_header_layout.setSpacing(8)

        title_icon = IconWidget(FluentIcon.LEAF, card_header)
        title_icon.setFixedSize(14, 14)
        card_header_layout.addWidget(title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        card_title = BodyLabel('土地信息', card_header)
        card_title.setStyleSheet('font-weight: 700; font-size: 14px; color: #1e293b;')
        card_header_layout.addWidget(card_title, 0, Qt.AlignmentFlag.AlignVCenter)
        card_subtitle = CaptionLabel('管理 24 格地块状态，保存后写入当前实例配置。', card_header)
        card_subtitle.setStyleSheet('color: #64748b;')
        card_header_layout.addWidget(card_subtitle, 0, Qt.AlignmentFlag.AlignVCenter)
        card_header_layout.addStretch(1)
        self._edit_btn = ToolButton(card_header)
        self._edit_btn.setFixedSize(36, 30)
        self._edit_btn.setIconSize(QSize(16, 16))
        self._edit_btn.clicked.connect(self._on_toggle_edit)
        card_header_layout.addWidget(self._edit_btn, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        board_layout.addWidget(card_header)

        divider = QFrame(self._board_card)
        divider.setObjectName('landDetailCardDivider')
        divider.setFixedHeight(1)
        divider.setStyleSheet(
            'QFrame#landDetailCardDivider { background-color: rgba(37, 99, 235, 0.10); border: none; }'
        )
        board_layout.addWidget(divider)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self.CELL_GAP)
        self._grid.setVerticalSpacing(self.CELL_GAP)

        for row in range(self.ROW_COUNT):
            for col in range(self.COL_COUNT):
                plot_id = self._plot_id_at(row, col)
                cell = LandCell(plot_id, self._board_card)
                cell.state_changed.connect(self._on_cell_state_changed)
                self._grid.addWidget(cell, row, col)
                self._cells[plot_id] = cell

        for col in range(self.COL_COUNT):
            self._grid.setColumnStretch(col, 1)

        board_layout.addLayout(self._grid)

    @staticmethod
    def _apply_card_style(card: StableElevatedCardWidget, object_name: str) -> None:
        card.setObjectName(object_name)
        card.setStyleSheet(
            f'ElevatedCardWidget#{object_name} {{'
            ' border-radius: 10px;'
            ' border: 1px solid rgba(100, 116, 139, 0.22);'
            ' }'
            f'ElevatedCardWidget#{object_name}:hover {{'
            ' background-color: rgba(37, 99, 235, 0.06);'
            ' border: 1px solid rgba(59, 130, 246, 0.32);'
            ' }'
        )

    def _build_profile_cell(self, field_key: str, field_title: str) -> QWidget:
        row_widget = QWidget(self._profile_card)
        row_widget.setObjectName('profileItem')
        row_widget.setStyleSheet('QWidget#profileItem { border: none; border-radius: 6px; background: transparent; }')
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(6, 2, 6, 2)
        row_layout.setSpacing(6)

        title_label = CaptionLabel(f'{field_title}:', row_widget)
        title_label.setTextColor(QColor('#64748B'), QColor('#94A3B8'))
        row_layout.addWidget(title_label)

        value_label = StrongBodyLabel('--', row_widget)
        value_label.setTextColor(QColor('#0F172A'), QColor('#E5E7EB'))
        if field_key in {'level', 'coupon'}:
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_label.setMinimumWidth(value_label.fontMetrics().horizontalAdvance('00000'))
        self._profile_value_labels[field_key] = value_label
        row_layout.addWidget(value_label)
        row_layout.addStretch()
        return row_widget

    def _set_edit_mode(self, editable: bool) -> None:
        self._editing = bool(editable)
        self._edit_btn.setIcon(
            FluentIcon.SAVE.icon(color=QColor('#ffffff'))
            if self._editing
            else FluentIcon.EDIT.icon(color=QColor('#ffffff'))
        )
        self._edit_btn.setToolTip('保存' if self._editing else '编辑')
        if self._editing:
            self._edit_btn.setStyleSheet(
                'QToolButton {'
                ' background-color: #16a34a;'
                ' border: 1px solid #15803d;'
                ' border-radius: 8px;'
                ' padding: 0;'
                '}'
                'QToolButton:hover {'
                ' background-color: #15803d;'
                ' border-color: #166534;'
                '}'
                'QToolButton:pressed {'
                ' background-color: #166534;'
                ' border-color: #14532d;'
                '}'
            )
        else:
            self._edit_btn.setStyleSheet(
                'QToolButton {'
                ' background-color: #2563eb;'
                ' border: 1px solid #1d4ed8;'
                ' border-radius: 8px;'
                ' padding: 0;'
                '}'
                'QToolButton:hover {'
                ' background-color: #1d4ed8;'
                ' border-color: #1e40af;'
                '}'
                'QToolButton:pressed {'
                ' background-color: #1e40af;'
                ' border-color: #1e3a8a;'
                '}'
            )
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

    def _on_cell_state_changed(self, plot_id: str, state: str) -> None:
        """编辑状态下：将当前地块之前且等级更低的地块级联提升到相同状态。"""
        if not self._editing:
            return
        target_key = self._plot_logic_key(plot_id)
        target_rank = int(LAND_STATE_RANK.get(str(state), 0))

        for cell in self._cells.values():
            if self._plot_logic_key(cell.plot_id) >= target_key:
                continue
            prev_state = str(cell.get_data().get('level', 'unbuilt'))
            prev_rank = int(LAND_STATE_RANK.get(prev_state, 0))
            if prev_rank >= target_rank:
                continue
            cell.set_data({'level': state})
        ok, message = self._validate_adjacent_continuity()
        if not ok:
            self._show_tip('编辑提示', message)

    def _validate_before_save(self) -> tuple[bool, str]:
        ordered = sorted(self._cells.values(), key=lambda c: self._plot_logic_key(c.plot_id))
        prev_cell: LandCell | None = None
        prev_rank = -1
        for cell in ordered:
            state = str(cell.get_data().get('level', 'unbuilt'))
            rank = int(LAND_STATE_RANK.get(state, 0))
            if prev_cell is not None and prev_rank < rank:
                prev_state = str(prev_cell.get_data().get('level', 'unbuilt'))
                prev_label = LAND_STATE_META.get(prev_state, LAND_STATE_META['unbuilt']).label
                curr_label = LAND_STATE_META.get(state, LAND_STATE_META['unbuilt']).label
                return (
                    False,
                    f'排序不合法：{prev_cell.plot_id}({prev_label}) < {cell.plot_id}({curr_label})\n'
                    '请保证前面的地块等级不低于后面的地块。',
                )
            prev_cell = cell
            prev_rank = rank
        return self._validate_adjacent_continuity()

    def _validate_adjacent_continuity(self) -> tuple[bool, str]:
        """校验相邻地块等级连续（仅可相同或下降一级）。"""
        ordered = sorted(self._cells.values(), key=lambda c: self._plot_logic_key(c.plot_id))
        prev_cell: LandCell | None = None
        prev_rank = -1
        for cell in ordered:
            state = str(cell.get_data().get('level', 'unbuilt'))
            rank = int(LAND_STATE_RANK.get(state, 0))
            if prev_cell is not None and prev_rank - rank > 1:
                prev_state = str(prev_cell.get_data().get('level', 'unbuilt'))
                prev_label = LAND_STATE_META.get(prev_state, LAND_STATE_META['unbuilt']).label
                curr_label = LAND_STATE_META.get(state, LAND_STATE_META['unbuilt']).label
                return (
                    False,
                    f'等级不连续：{prev_cell.plot_id}({prev_label}) 与 {cell.plot_id}({curr_label}) 不是相邻等级\n'
                    '请保证相邻地块状态仅可相同或下降一级。',
                )
            prev_cell = cell
            prev_rank = rank
        return True, ''

    def _show_save_error(self, message: str) -> None:
        box = MessageBox('保存失败', str(message or '').strip(), self._dialog_parent())
        box.yesButton.setText('确定')
        box.cancelButton.hide()
        box.exec()

    def _show_tip(self, title: str, message: str) -> None:
        box = MessageBox(str(title or '').strip() or '提示', str(message or '').strip(), self._dialog_parent())
        box.yesButton.setText('确定')
        box.cancelButton.hide()
        box.exec()

    def _dialog_parent(self) -> QWidget:
        parent_window = self.window()
        return parent_window if isinstance(parent_window, QWidget) else self

    def _save_to_config(self) -> bool:
        try:
            self.config.land.plots = self.get_land_data()
            self.config.save()
        except Exception as exc:
            self._show_save_error(f'写入配置失败：{exc}')
            return False
        self.config_changed.emit(self.config)
        return True

    def _load_from_config(self) -> None:
        profile_cfg = self.config.land.profile
        level_value = int(profile_cfg.level)
        if level_value <= 0:
            level_value = int(self.config.planting.player_level)
        profile_level_text = str(level_value) if level_value > 0 else '--'
        profile_gold_text = str(profile_cfg.gold or '').strip() or '--'
        profile_coupon_text = str(profile_cfg.coupon or '').strip() or '--'
        profile_exp_text = str(profile_cfg.exp or '').strip() or '--'

        value_map = {
            'level': profile_level_text,
            'gold': profile_gold_text,
            'coupon': profile_coupon_text,
            'exp': profile_exp_text,
        }
        for key, label in self._profile_value_labels.items():
            label.setText(value_map.get(key, '--'))

        items = self.config.land.plots
        if not isinstance(items, list):
            items = []
        self.set_land_data(items)

    def _on_toggle_edit(self) -> None:
        if self._editing:
            ok, message = self._validate_before_save()
            if not ok:
                self._show_save_error(message)
                return
            if not self._save_to_config():
                return
        self._set_edit_mode(not self._editing)

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

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._set_edit_mode(False)
        self._load_from_config()

    def _on_countdown_tick(self) -> None:
        changed = False
        for cell in self._cells.values():
            if cell.tick_countdown():
                changed = True
        if not changed:
            return
