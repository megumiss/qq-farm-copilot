"""Fluent 任务功能面板。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QTime, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    LineEdit,
    ListWidget,
    MessageBoxBase,
    PushButton,
    ScrollArea,
    SpinBox,
    SubtitleLabel,
    TimeEdit,
    TransparentToolButton,
)

from gui.widgets.fluent_container import StableElevatedCardWidget, TransparentCardContainer
from models.config import AppConfig, normalize_task_enabled_time_range, resolve_executor_task_order
from utils.app_paths import load_config_json_object
from utils.feature_policy import is_feature_forced_off

SETTINGS_HINT_COLOR = '#d97706'


class _ListEditorDialog(MessageBoxBase):
    def __init__(self, title: str, values: list[str], parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(430)
        self._title_label = SubtitleLabel(str(title or '列表编辑'), self)
        self._title_label.setWordWrap(True)
        self.viewLayout.addWidget(self._title_label)

        self._list = ListWidget(self.widget)
        self._list.setMinimumHeight(230)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setContentsMargins(4, 4, 4, 4)
        self._list.setStyleSheet(
            'ListWidget { border: 1px solid rgba(15, 23, 42, 0.12); border-radius: 8px; background: transparent; }'
            'ListWidget::item:selected { background: transparent; border: none; }'
            'ListWidget::item:hover { background: transparent; }'
        )
        for text in values:
            self._append_value_item(str(text))
        self.viewLayout.addWidget(self._list, 1)

        input_row = QWidget(self.widget)
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)
        self._input = LineEdit(input_row)
        self._input.setPlaceholderText('输入后回车或点击新增')
        add_btn = PushButton('新增', input_row)
        add_btn.clicked.connect(self._on_add)
        self._input.returnPressed.connect(self._on_add)
        input_layout.addWidget(self._input, 1)
        input_layout.addWidget(add_btn)
        self.viewLayout.addWidget(input_row)

        self.yesButton.setText('保存')
        self.cancelButton.setText('取消')
        self.yesButton.setEnabled(True)

    def _on_add(self) -> None:
        text = str(self._input.text() or '').strip()
        if not text:
            return
        existed = {value.lower() for value in self._iter_values()}
        if text.lower() in existed:
            self._input.clear()
            return
        self._append_value_item(text)
        self._input.clear()

    def _append_value_item(self, text: str) -> None:
        item = QListWidgetItem(self._list)
        item.setData(Qt.ItemDataRole.UserRole, str(text))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)

        row = QWidget(self._list)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 2, 4, 2)
        row_layout.setSpacing(8)
        label = BodyLabel(str(text), row)
        remove_btn = TransparentToolButton(FluentIcon.DELETE, row)
        remove_btn.setFixedSize(22, 22)
        remove_btn.setToolTip('删除')
        remove_btn.clicked.connect(lambda _=False, x=item: self._remove_item(x))
        row_layout.addWidget(label, 1)
        row_layout.addWidget(remove_btn, 0)

        item.setSizeHint(row.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, row)

    def _remove_item(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if row < 0:
            return
        self._list.takeItem(row)

    def _iter_values(self) -> list[str]:
        values: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            value = str(item.data(Qt.ItemDataRole.UserRole) or '').strip()
            if value:
                values.append(value)
        return values

    def values(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for text in self._iter_values():
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
        self._feature_hint_map = labels.get('feature_hints', {})
        self._loading = True
        self._bool_widgets: dict[tuple[str, str], CheckBox] = {}
        self._int_widgets: dict[tuple[str, str], SpinBox] = {}
        self._text_widgets: dict[tuple[str, str], LineEdit] = {}
        self._time_range_widgets: dict[tuple[str, str], tuple[TimeEdit, TimeEdit]] = {}
        self._interval_widgets: dict[tuple[str, str], tuple[SpinBox, ComboBox]] = {}
        self._list_summary: dict[tuple[str, str], CaptionLabel] = {}
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
        for task_name in self._resolve_task_order():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = task_cfg.features or {}
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

    def _resolve_task_order(self) -> list[str]:
        task_names = [str(name) for name in self.config.tasks.keys()]
        return resolve_executor_task_order(task_names, self.config.executor.task_order)

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

    @staticmethod
    def _style_form(form: QFormLayout) -> None:
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setHorizontalSpacing(0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def _field_label(text: str, parent: QWidget) -> CaptionLabel:
        text_value = str(text or '').strip()
        label = CaptionLabel(f'{text_value}:' if text_value else '', parent)
        if text_value:
            label.setFixedWidth(label.sizeHint().width() + label.fontMetrics().horizontalAdvance('字'))
            label.setStyleSheet('color: #475569; font-weight: 600;')
        return label

    @staticmethod
    def _add_card_title(layout: QVBoxLayout, title_text: str) -> None:
        title = BodyLabel(str(title_text))
        title.setStyleSheet('font-weight: 700; font-size: 14px; color: #1e293b;')
        layout.addWidget(title)
        divider = QFrame()
        divider.setObjectName('featureCardTitleDivider')
        divider.setFixedHeight(1)
        divider.setStyleSheet(
            'QFrame#featureCardTitleDivider { background-color: rgba(37, 99, 235, 0.10); border: none; }'
        )
        layout.addWidget(divider)

    def _build_task_card(self, task_name: str, feature_map: dict[str, Any]) -> StableElevatedCardWidget:
        card = StableElevatedCardWidget(self)
        self._apply_card_style(card, 'featureConfigCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)
        self._add_card_title(layout, str(self._task_title_map.get(task_name, task_name)))

        form = QFormLayout()
        self._style_form(form)
        for feature_name, value in feature_map.items():
            label = str(self._feature_label_map.get(feature_name, feature_name))
            hint_text = self._resolve_feature_hint(task_name, feature_name)
            if isinstance(value, list):
                row = QWidget(card)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(8)
                summary = CaptionLabel('未配置')
                summary.setStyleSheet('color: #64748b;')
                self._list_summary[(task_name, feature_name)] = summary
                btn = PushButton('详情', row)
                btn.clicked.connect(
                    lambda _=False, t=task_name, f=feature_name: self._open_list_editor(t, f),
                )
                row_layout.addWidget(summary, 1)
                row_layout.addWidget(btn)
                field = QWidget(card)
                field_layout = QVBoxLayout(field)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(2)
                field_layout.addWidget(row)
                if hint_text:
                    hint = CaptionLabel(hint_text, field)
                    hint.setWordWrap(True)
                    hint.setStyleSheet(f'color: {SETTINGS_HINT_COLOR};')
                    field_layout.addWidget(hint)
                form.addRow(self._field_label(label, card), field)
                continue

            if isinstance(value, bool):
                box = CheckBox('启用', card)
                box.toggled.connect(self._auto_save)
                self._bool_widgets[(task_name, feature_name)] = box
                field = QWidget(card)
                field_layout = QVBoxLayout(field)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(2)
                field_layout.addWidget(box)
                if hint_text:
                    hint = CaptionLabel(hint_text, field)
                    hint.setWordWrap(True)
                    hint.setStyleSheet(f'color: {SETTINGS_HINT_COLOR};')
                    field_layout.addWidget(hint)
                form.addRow(self._field_label(label, card), field)
                continue

            if isinstance(value, str):
                if feature_name.endswith('_enabled_time_range'):
                    start = self._build_time_edit(card)
                    start.timeChanged.connect(self._auto_save)
                    end = self._build_time_edit(card)
                    end.timeChanged.connect(self._auto_save)
                    row = QWidget(card)
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(8)
                    row_layout.addWidget(start, 1)
                    row_layout.addWidget(BodyLabel('~'))
                    row_layout.addWidget(end, 1)
                    self._time_range_widgets[(task_name, feature_name)] = (start, end)
                    field_widget: QWidget = row
                else:
                    text_edit = LineEdit(card)
                    text_edit.textChanged.connect(self._auto_save)
                    self._text_widgets[(task_name, feature_name)] = text_edit
                    field_widget = text_edit
                field = QWidget(card)
                field_layout = QVBoxLayout(field)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(2)
                field_layout.addWidget(field_widget)
                if hint_text:
                    hint = CaptionLabel(hint_text, field)
                    hint.setWordWrap(True)
                    hint.setStyleSheet(f'color: {SETTINGS_HINT_COLOR};')
                    field_layout.addWidget(hint)
                form.addRow(self._field_label(label, card), field)
                continue

            if isinstance(value, int):
                if feature_name.endswith('_seconds'):
                    spin = SpinBox(card)
                    spin.setRange(0, 99999)
                    spin.valueChanged.connect(self._auto_save)
                    unit = ComboBox(card)
                    unit.addItem('秒', userData=1)
                    unit.addItem('分钟', userData=60)
                    unit.addItem('小时', userData=3600)
                    unit.currentIndexChanged.connect(self._auto_save)
                    row = QWidget(card)
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(8)
                    row_layout.addWidget(spin, 1)
                    row_layout.addWidget(unit)
                    self._interval_widgets[(task_name, feature_name)] = (spin, unit)
                    field_widget: QWidget = row
                else:
                    spin = SpinBox(card)
                    spin.setRange(0, 99999)
                    spin.valueChanged.connect(self._auto_save)
                    self._int_widgets[(task_name, feature_name)] = spin
                    field_widget = spin
                field = QWidget(card)
                field_layout = QVBoxLayout(field)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(2)
                field_layout.addWidget(field_widget)
                if hint_text:
                    hint = CaptionLabel(hint_text, field)
                    hint.setWordWrap(True)
                    hint.setStyleSheet(f'color: {SETTINGS_HINT_COLOR};')
                    field_layout.addWidget(hint)
                form.addRow(self._field_label(label, card), field)
                continue

        layout.addLayout(form)
        return card

    def _resolve_feature_hint(self, task_name: str, feature_name: str) -> str:
        full_key = f'{task_name}.{feature_name}'
        text = self._feature_hint_map.get(full_key, self._feature_hint_map.get(feature_name, ''))
        return str(text or '').strip()

    @staticmethod
    def _normalize_int_feature_value(value: Any) -> int:
        """规范化整数字段值。"""
        try:
            parsed = int(value)
        except Exception:
            parsed = 0
        return max(0, parsed)

    @staticmethod
    def _split_interval(seconds: int) -> tuple[int, int]:
        value = max(0, int(seconds))
        if value > 0 and value % 3600 == 0:
            return value // 3600, 3600
        if value > 0 and value % 60 == 0:
            return value // 60, 60
        return value, 1

    @staticmethod
    def _set_combo_data(combo: ComboBox, value) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _parse_enabled_time_range(text: str) -> tuple[str, str]:
        normalized = normalize_task_enabled_time_range(text)
        start, end = normalized.split('-', 1)
        return start, end

    @staticmethod
    def _build_time_edit(parent: QWidget) -> TimeEdit:
        edit = TimeEdit(parent)
        edit.setDisplayFormat('HH:mm:ss')
        edit.setSymbolVisible(False)
        edit.setMinimumWidth(0)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return edit

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
        feature_map = task_cfg.features or {}
        if not isinstance(feature_map, dict):
            return []
        return self._normalize_list_value(feature_map.get(feature_name, []))

    def _write_list(self, task_name: str, feature_name: str, values: list[str]) -> None:
        task_cfg = self.config.tasks.get(task_name)
        if task_cfg is None:
            return
        feature_map = dict(task_cfg.features or {})
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
        task_title = str(self._task_title_map.get(task_name, task_name))
        feature_title = str(self._feature_label_map.get(feature_name, feature_name))
        title = f'{task_title} - {feature_title}'
        parent_window = self.window()
        dialog_parent = parent_window if isinstance(parent_window, QWidget) else self
        dialog = _ListEditorDialog(
            title=title,
            values=self._read_list(task_name, feature_name),
            parent=dialog_parent,
        )
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        if not bool(dialog.exec()):
            return
        self._write_list(task_name, feature_name, dialog.values())

    def _auto_save(self) -> None:
        if self._loading:
            return
        for (task_name, feature_name), box in self._bool_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = dict(task_cfg.features or {})
            if is_feature_forced_off(task_name, feature_name):
                feature_map[feature_name] = False
                box.setChecked(False)
                box.setEnabled(False)
            else:
                feature_map[feature_name] = bool(box.isChecked())
            task_cfg.features = feature_map
        for (task_name, feature_name), spin in self._int_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = dict(task_cfg.features or {})
            feature_map[feature_name] = self._normalize_int_feature_value(spin.value())
            task_cfg.features = feature_map
        for (task_name, feature_name), text_edit in self._text_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = dict(task_cfg.features or {})
            feature_map[feature_name] = str(text_edit.text() or '').strip()
            task_cfg.features = feature_map
        for (task_name, feature_name), (start, end) in self._time_range_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = dict(task_cfg.features or {})
            start_text = start.time().toString('HH:mm:ss')
            end_text = end.time().toString('HH:mm:ss')
            feature_map[feature_name] = normalize_task_enabled_time_range(f'{start_text}-{end_text}')
            task_cfg.features = feature_map
        for (task_name, feature_name), (spin, unit) in self._interval_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = dict(task_cfg.features or {})
            factor = max(1, int(unit.currentData() or 1))
            feature_map[feature_name] = max(0, int(spin.value()) * factor)
            task_cfg.features = feature_map
        self.config.save()
        self.config_changed.emit(self.config)

    def _load_config(self) -> None:
        for (task_name, feature_name), box in self._bool_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = task_cfg.features or {}
            forced = is_feature_forced_off(task_name, feature_name)
            box.setEnabled(not forced)
            box.setChecked(False if forced else bool(feature_map.get(feature_name, False)))
            if forced:
                box.setToolTip('该功能固定禁用')
        for (task_name, feature_name), spin in self._int_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = task_cfg.features or {}
            value = feature_map.get(feature_name, 0)
            if isinstance(value, bool):
                value = 0
            spin.setValue(self._normalize_int_feature_value(value))
        for (task_name, feature_name), text_edit in self._text_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = task_cfg.features or {}
            text_edit.setText(str(feature_map.get(feature_name, '') or '').strip())
        for (task_name, feature_name), (start_edit, end_edit) in self._time_range_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = task_cfg.features or {}
            start, end = self._parse_enabled_time_range(str(feature_map.get(feature_name, '')))
            start_time = QTime.fromString(start, 'HH:mm:ss')
            end_time = QTime.fromString(end, 'HH:mm:ss')
            if not start_time.isValid():
                start_time = QTime(0, 0, 0)
            if not end_time.isValid():
                end_time = QTime(23, 59, 59)
            start_edit.setTime(start_time)
            end_edit.setTime(end_time)
        for (task_name, feature_name), (spin, unit) in self._interval_widgets.items():
            task_cfg = self.config.tasks.get(task_name)
            if task_cfg is None:
                continue
            feature_map = task_cfg.features or {}
            value = feature_map.get(feature_name, 0)
            if isinstance(value, bool):
                value = 0
            try:
                parsed = int(value)
            except Exception:
                parsed = 0
            number, factor = self._split_interval(max(0, parsed))
            spin.setValue(number)
            self._set_combo_data(unit, factor)
        for task_name, feature_name in self._list_summary.keys():
            self._refresh_list_summary(task_name, feature_name)

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._loading = True
        self._load_config()
        self._loading = False
