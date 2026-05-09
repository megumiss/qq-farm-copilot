"""数据统计图表面板。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QWheelEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QToolTip, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, FluentIcon, ScrollArea, SegmentedWidget, ToolButton, isDarkTheme

from utils.daily_action_stats import load_daily_actions
from utils.steal_stats import load_stats


def _format_count(value: int) -> str:
    if value >= 100_000_000:
        text = f'{value / 100_000_000:.2f}'.rstrip('0').rstrip('.')
        return f'{text}亿'
    if value >= 10_000:
        text = f'{value / 10_000:.2f}'.rstrip('0').rstrip('.')
        return f'{text}万'
    return str(value)


def _format_date_label(date_text: str) -> str:
    return date_text[5:] if len(date_text) >= 10 else date_text


class _BarChart(QWidget):
    def __init__(self, on_wheel: Callable[[int], None], *, bar_color: str, parent=None):
        super().__init__(parent)
        self._on_wheel = on_wheel
        self._bar_color = QColor(bar_color)
        self._data: list[tuple[str, int]] = []
        self._hover_idx = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(140)

    def set_data(self, data: list[tuple[str, int]]):
        self._data = data
        self.update()

    def _index_at(self, x: float) -> int:
        if not self._data:
            return -1
        pad_l, pad_r = 56, 16
        w = self.width() - pad_l - pad_r
        n = len(self._data)
        if w <= 0:
            return -1
        idx = int((x - pad_l) * n / w)
        return idx if 0 <= idx < n else -1

    def mouseMoveEvent(self, event):
        x = event.position().x()
        idx = self._index_at(x)
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        if idx >= 0:
            d, v = self._data[idx]
            QToolTip.showText(self.mapToGlobal(event.position().toPoint()), f'{d}\n{_format_count(v)}', self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):
        if self._hover_idx >= 0:
            self._hover_idx = -1
            self.update()
        QToolTip.hideText()

    def paintEvent(self, event):
        if not self._data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        pad_l, pad_r, pad_t, pad_b = 56, 16, 16, 52
        w = self.width() - pad_l - pad_r
        h = self.height() - pad_t - pad_b
        n = len(self._data)
        max_val = max(v for _, v in self._data) or 1

        dark = isDarkTheme()
        fg = QColor('#e2e8f0' if dark else '#1e293b')
        grid_c = QColor('#334155' if dark else '#e2e8f0')
        bar_c = self._bar_color

        font = QFont()
        font.setPointSize(8)
        p.setFont(font)

        for i in range(5):
            y = pad_t + h - i * h // 4
            p.setPen(QPen(grid_c, 1, Qt.PenStyle.DashLine))
            p.drawLine(pad_l, y, pad_l + w, y)
            p.setPen(fg)
            p.drawText(
                QRectF(0, y - 10, pad_l - 4, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _format_count(int(max_val * i / 4)),
            )

        bar_w = max(4, w // n - 4)
        for i, (_, v) in enumerate(self._data):
            bh = int(v / max_val * h)
            x = pad_l + i * w // n + (w // n - bar_w) // 2
            y = pad_t + h - bh
            if i == self._hover_idx:
                highlight = QColor(bar_c)
                highlight.setAlpha(60)
                p.setBrush(highlight)
                p.setPen(QPen(bar_c.lighter(130), 1.5))
            else:
                p.setBrush(bar_c)
                p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, y, bar_w, bh), 3, 3)

        sample_step = max(1, n // 6)
        for i, (d, _) in enumerate(self._data):
            if i != 0 and i != n - 1 and i % sample_step != 0:
                continue
            x = pad_l + i * w // n + w // n // 2
            p.setPen(grid_c)
            p.drawLine(x, pad_t + h, x, pad_t + h + 4)
            p.setPen(fg)
            p.drawText(
                QRectF(x - 22, pad_t + h + 6, 44, 20),
                Qt.AlignmentFlag.AlignHCenter,
                _format_date_label(d),
            )
        p.end()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta:
            self._on_wheel(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


class _DualBarChart(QWidget):
    def __init__(
        self,
        on_wheel: Callable[[int], None],
        *,
        left_color: str,
        right_color: str,
        left_label: str = '',
        right_label: str = '',
        parent=None,
    ):
        super().__init__(parent)
        self._on_wheel = on_wheel
        self._left_color = QColor(left_color)
        self._right_color = QColor(right_color)
        self._left_label = left_label
        self._right_label = right_label
        self._data: list[tuple[str, int, int]] = []
        self._hover_idx = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(170)

    def set_data(self, data: list[tuple[str, int, int]]):
        self._data = data
        self.update()

    def _index_at(self, x: float) -> int:
        if not self._data:
            return -1
        pad_l, pad_r = 56, 16
        w = self.width() - pad_l - pad_r
        n = len(self._data)
        if w <= 0:
            return -1
        idx = int((x - pad_l) * n / w)
        return idx if 0 <= idx < n else -1

    def mouseMoveEvent(self, event):
        x = event.position().x()
        idx = self._index_at(x)
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        if idx >= 0:
            d, lv, rv = self._data[idx]
            l_label = self._left_label or '左'
            r_label = self._right_label or '右'
            text = f'{d}\n{l_label}: {_format_count(lv)}\n{r_label}: {_format_count(rv)}'
            QToolTip.showText(self.mapToGlobal(event.position().toPoint()), text, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):
        if self._hover_idx >= 0:
            self._hover_idx = -1
            self.update()
        QToolTip.hideText()

    def paintEvent(self, event):
        if not self._data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        pad_l, pad_r, pad_t, pad_b = 56, 16, 16, 52
        w = self.width() - pad_l - pad_r
        h = self.height() - pad_t - pad_b
        n = len(self._data)
        max_val = max(max(left, right) for _, left, right in self._data) or 1

        dark = isDarkTheme()
        fg = QColor('#e2e8f0' if dark else '#1e293b')
        grid_c = QColor('#334155' if dark else '#e2e8f0')

        font = QFont()
        font.setPointSize(8)
        p.setFont(font)

        for i in range(5):
            y = pad_t + h - i * h // 4
            p.setPen(QPen(grid_c, 1, Qt.PenStyle.DashLine))
            p.drawLine(pad_l, y, pad_l + w, y)
            p.setPen(fg)
            p.drawText(
                QRectF(0, y - 10, pad_l - 4, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _format_count(int(max_val * i / 4)),
            )

        slot_w = max(10, w // n)
        bar_w = max(3, min(10, (slot_w - 4) // 2))
        for i, (_, left_v, right_v) in enumerate(self._data):
            x_center = pad_l + i * w // n + slot_w // 2
            left_bh = int(left_v / max_val * h)
            right_bh = int(right_v / max_val * h)
            left_x = x_center - bar_w - 1
            right_x = x_center + 1
            base_y = pad_t + h
            p.setPen(Qt.PenStyle.NoPen)
            if i == self._hover_idx:
                h_left = QColor(self._left_color)
                h_left.setAlpha(60)
                p.setBrush(h_left)
                p.setPen(QPen(self._left_color.lighter(130), 1.5))
            else:
                p.setBrush(self._left_color)
            p.drawRoundedRect(QRectF(left_x, base_y - left_bh, bar_w, left_bh), 2, 2)
            p.setPen(Qt.PenStyle.NoPen)
            if i == self._hover_idx:
                h_right = QColor(self._right_color)
                h_right.setAlpha(60)
                p.setBrush(h_right)
                p.setPen(QPen(self._right_color.lighter(130), 1.5))
            else:
                p.setBrush(self._right_color)
            p.drawRoundedRect(QRectF(right_x, base_y - right_bh, bar_w, right_bh), 2, 2)

        sample_step = max(1, n // 6)
        for i, (d, _, _) in enumerate(self._data):
            if i != 0 and i != n - 1 and i % sample_step != 0:
                continue
            x = pad_l + i * w // n + slot_w // 2
            p.setPen(grid_c)
            p.drawLine(x, pad_t + h, x, pad_t + h + 4)
            p.setPen(fg)
            p.drawText(
                QRectF(x - 22, pad_t + h + 6, 44, 20),
                Qt.AlignmentFlag.AlignHCenter,
                _format_date_label(d),
            )
        p.end()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta:
            self._on_wheel(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


class StealChartPanel(QWidget):
    _MIN_DAY_WINDOW = 1
    _MAX_DAY_WINDOW = 120
    _MIN_WEEK_WINDOW = 1
    _MAX_WEEK_WINDOW = 52

    def __init__(self, instance_id: str = 'default', parent=None):
        super().__init__(parent)
        self._instance_id = instance_id
        self._day_window = 15
        self._week_window = 8

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(scroll, 1)

        container = QWidget(scroll)
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        ctrl = QHBoxLayout()
        self._seg = SegmentedWidget()
        self._seg.addItem('day', '天视图')
        self._seg.addItem('week', '周视图')
        self._seg.setCurrentItem('day')
        self._seg.currentItemChanged.connect(lambda _: self._refresh())
        ctrl.addWidget(self._seg)
        ctrl.addStretch()
        self._refresh_btn = ToolButton()
        self._refresh_btn.setIcon(FluentIcon.SYNC)
        self._refresh_btn.setToolTip('刷新统计数据')
        self._refresh_btn.setFixedSize(32, 32)
        self._refresh_btn.clicked.connect(self._refresh)
        ctrl.addWidget(self._refresh_btn)
        layout.addLayout(ctrl)

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)

        coin_title = BodyLabel('偷取金币')
        coin_title.setStyleSheet('font-weight: 700;')
        self._coin_chart = _BarChart(self._adjust_window, bar_color='#f59e0b')

        bean_title = BodyLabel('偷取金豆')
        bean_title.setStyleSheet('font-weight: 700;')
        self._bean_chart = _BarChart(self._adjust_window, bar_color='#22c55e')

        harvest_operation_title = BodyLabel('收获 / 操作')
        harvest_operation_title.setStyleSheet('font-weight: 700;')
        self._harvest_operation_chart = _DualBarChart(
            self._adjust_window,
            left_color='#0ea5e9',
            right_color='#8b5cf6',
            left_label='收获',
            right_label='操作',
        )

        friend_title = BodyLabel('偷菜 / 帮忙')
        friend_title.setStyleSheet('font-weight: 700;')
        self._friend_chart = _DualBarChart(
            self._adjust_window,
            left_color='#f43f5e',
            right_color='#14b8a6',
            left_label='偷菜',
            right_label='帮忙',
        )

        card_layout.addWidget(coin_title)
        card_layout.addWidget(self._coin_chart)
        card_layout.addWidget(bean_title)
        card_layout.addWidget(self._bean_chart)
        card_layout.addWidget(harvest_operation_title)
        card_layout.addWidget(self._harvest_operation_chart)
        card_layout.addWidget(friend_title)
        card_layout.addWidget(self._friend_chart)
        layout.addWidget(card, 1)

        self._refresh()

    def _adjust_window(self, delta: int):
        if delta == 0:
            return
        is_week = self._seg.currentRouteKey() == 'week'
        if is_week:
            self._week_window = min(
                self._MAX_WEEK_WINDOW,
                max(self._MIN_WEEK_WINDOW, self._week_window + delta),
            )
        else:
            self._day_window = min(
                self._MAX_DAY_WINDOW,
                max(self._MIN_DAY_WINDOW, self._day_window + delta),
            )
        self._refresh()

    def _refresh(self):
        is_week = self._seg.currentRouteKey() == 'week'
        if is_week:
            today = date.today()
            current_monday = today - timedelta(days=today.weekday())
            first_monday = current_monday - timedelta(weeks=self._week_window - 1)
            days = (today - first_monday).days + 1
            day_data = load_stats(self._instance_id, days)
            action_data = load_daily_actions(self._instance_id, days)
            day_map = {d: (coin, bean) for d, coin, bean in day_data}
            action_map = {
                d: (harvest, operation, friend_steal, friend_help)
                for d, harvest, operation, friend_steal, friend_help in action_data
            }

            mondays = [first_monday + timedelta(weeks=i) for i in range(self._week_window)]
            data: list[tuple[str, int, int, int, int, int, int]] = []
            for monday in mondays:
                week_coin_sum = 0
                week_bean_sum = 0
                week_harvest_sum = 0
                week_operation_sum = 0
                week_friend_steal_sum = 0
                week_friend_help_sum = 0
                for offset in range(7):
                    current_day = monday + timedelta(days=offset)
                    if current_day > today:
                        break
                    day_key = current_day.isoformat()
                    day_coin, day_bean = day_map.get(day_key, (0, 0))
                    day_harvest, day_operation, day_friend_steal, day_friend_help = action_map.get(
                        day_key, (0, 0, 0, 0)
                    )
                    week_coin_sum += day_coin
                    week_bean_sum += day_bean
                    week_harvest_sum += day_harvest
                    week_operation_sum += day_operation
                    week_friend_steal_sum += day_friend_steal
                    week_friend_help_sum += day_friend_help
                data.append(
                    (
                        monday.isoformat(),
                        week_coin_sum,
                        week_bean_sum,
                        week_harvest_sum,
                        week_operation_sum,
                        week_friend_steal_sum,
                        week_friend_help_sum,
                    )
                )
        else:
            day_data = load_stats(self._instance_id, self._day_window)
            action_data = load_daily_actions(self._instance_id, self._day_window)
            action_map = {
                d: (harvest, operation, friend_steal, friend_help)
                for d, harvest, operation, friend_steal, friend_help in action_data
            }
            data = []
            for d, coin, bean in day_data:
                harvest, operation, friend_steal, friend_help = action_map.get(d, (0, 0, 0, 0))
                data.append((d, coin, bean, harvest, operation, friend_steal, friend_help))

        self._coin_chart.set_data([(d, coin) for d, coin, _, _, _, _, _ in data])
        self._bean_chart.set_data([(d, bean) for d, _, bean, _, _, _, _ in data])
        self._harvest_operation_chart.set_data([(d, harvest, operation) for d, _, _, harvest, operation, _, _ in data])
        self._friend_chart.set_data(
            [(d, friend_steal, friend_help) for d, _, _, _, _, friend_steal, friend_help in data]
        )

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()
