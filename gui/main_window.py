"""主窗口 - 单窗口多实例布局。"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import time

import keyboard
from PIL import Image
from PyQt6.QtCore import QSettings, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.engine.bot import BotEngine
from core.instance.manager import InstanceManager, InstanceSession
from gui.widgets.feature_panel import FeaturePanel
from gui.widgets.instance_sidebar import InstanceSidebar
from gui.widgets.log_panel import LogPanel
from gui.widgets.settings_panel import SettingsPanel
from gui.widgets.status_panel import StatusPanel
from gui.widgets.task_panel import TaskPanel
from models.config import AppConfig
from utils.app_paths import resolve_runtime_path, user_app_dir
from utils.logger import setup_logger

STYLESHEET_TEMPLATE = """
QMainWindow { background-color: #f5f5f7; }
QWidget { color: #1e293b; font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif; font-size: 13px; }
QGroupBox {
    border: 1px solid #e2e8f0; border-radius: 8px;
    margin-top: 12px; padding: 14px 10px 8px 10px;
    font-weight: bold; color: #475569; background-color: #ffffff;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QCheckBox { spacing: 6px; color: #1e293b; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1.5px solid #cbd5e1; border-radius: 3px; background: #ffffff; }
QCheckBox::indicator:checked {
    background: #2563eb; border-color: #2563eb;
    image: url(__CHECK_ICON__);
}
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 5px 8px; color: #1e293b; selection-background-color: #dbeafe;
    min-height: 20px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; width: 20px; border: none; background: #f1f5f9; border-top-right-radius: 5px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; width: 20px; border: none; background: #f1f5f9; border-bottom-right-radius: 5px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: #dbeafe; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(__ARROW_UP_ICON__); width: 10px; height: 6px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(__ARROW_DOWN_ICON__); width: 10px; height: 6px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #2563eb; }
QComboBox {
    combobox-popup: 0;
    background-color: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    color: #1e293b;
    padding: 6px 36px 6px 12px;
    min-height: 24px;
}
QComboBox:hover {
    border-color: #94a3b8;
    background-color: #ffffff;
}
QComboBox:focus {
    border-color: #3b82f6;
    background-color: #ffffff;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border: none;
    border-left: 1px solid #e2e8f0;
    border-top-right-radius: 10px;
    border-bottom-right-radius: 10px;
    background: transparent;
}
QComboBox::down-arrow { image: url(__ARROW_DOWN_ICON__); width: 10px; height: 6px; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 4px;
    outline: 0;
    selection-background-color: transparent;
    selection-color: #ffffff;
}
QComboBoxPrivateContainer {
    background: transparent;
    border: none;
    padding: 0px;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 5px 10px;
    border-radius: 8px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #eef2f7;
    color: #0f172a;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #dbeafe;
    color: #1d4ed8;
    font-weight: 600;
}
QScrollBar:vertical { background: #f5f5f7; width: 6px; border-radius: 3px; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

PROJECT_URL = 'https://github.com/megumiss/qq-farm-copilot'
PROJECT_URL_TEXT = 'github.com/megumiss/qq-farm-copilot'
APP_WINDOW_TITLE = 'QQ Farm Copilot（免费软件，谨防倒卖）'
APP_SETTINGS_ORG = 'QQFarmCopilot'
APP_SETTINGS_NAME = 'QQFarmCopilot'
FREE_NOTICE_ENABLED_KEY = 'ui/free_notice_enabled'
RAIL_ROLE_INSTANCE_ID = int(Qt.ItemDataRole.UserRole)
RAIL_ROLE_INSTANCE_STATE = RAIL_ROLE_INSTANCE_ID + 1
INSTANCE_DIALOG_STYLE = """
QMessageBox, QInputDialog {
    background-color: #f8fafc;
}
QMessageBox QLabel, QInputDialog QLabel {
    color: #334155;
    font-size: 13px;
}
QInputDialog QLineEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px 8px;
    color: #0f172a;
    min-width: 220px;
}
QInputDialog QLineEdit:focus {
    border-color: #2563eb;
}
QMessageBox QPushButton, QInputDialog QPushButton {
    min-width: 84px;
    min-height: 30px;
    border-radius: 8px;
    border: 1px solid #dbe3ef;
    background: #f8fafc;
    color: #334155;
    font-weight: 600;
    padding: 2px 10px;
}
QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
    background: #eef2ff;
    border-color: #c7d2fe;
}
"""


class InstanceRailItemDelegate(QStyledItemDelegate):
    """在实例窄轨项左侧固定位置绘制状态圆点。"""

    @staticmethod
    def _state_color(state: str) -> QColor:
        state_key = str(state or 'idle').strip().lower()
        if state_key == 'running':
            return QColor('#22c55e')
        if state_key == 'paused':
            return QColor('#f59e0b')
        return QColor('#94a3b8')

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        state = str(index.data(RAIL_ROLE_INSTANCE_STATE) or 'idle')
        dot_color = self._state_color(state)
        dot_radius = 4
        cx = int(option.rect.left()) + 9
        cy = int(option.rect.center().y())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor('#ffffff'))
        painter.setBrush(dot_color)
        painter.drawEllipse(cx - dot_radius, cy - dot_radius, dot_radius * 2, dot_radius * 2)
        painter.restore()


@dataclass
class InstanceWorkspace:
    instance_id: str
    name: str
    session: InstanceSession
    container: QWidget
    engine: BotEngine
    status_panel: StatusPanel
    log_panel: LogPanel
    task_panel: TaskPanel
    feature_panel: FeaturePanel
    settings_panel: SettingsPanel
    btn_start: QPushButton
    btn_pause: QPushButton
    btn_stop: QPushButton
    btn_run_once: QPushButton
    state: str = 'idle'
    last_preview: Image.Image | None = None


def _build_stylesheet() -> str:
    """构建样式表并注入运行时图标绝对路径。"""
    check_icon = str(resolve_runtime_path('gui', 'icons', 'check.svg')).replace('\\', '/')
    arrow_up_icon = str(resolve_runtime_path('gui', 'icons', 'arrow_up.svg')).replace('\\', '/')
    arrow_down_icon = str(resolve_runtime_path('gui', 'icons', 'arrow_down.svg')).replace('\\', '/')
    return (
        STYLESHEET_TEMPLATE.replace('__CHECK_ICON__', check_icon)
        .replace('__ARROW_UP_ICON__', arrow_up_icon)
        .replace('__ARROW_DOWN_ICON__', arrow_down_icon)
    )


def _make_btn(text: str, color: str, hover: str) -> QPushButton:
    """创建统一样式的操作按钮。"""
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedHeight(36)
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {color}; color: #FFFFFF; border: none;
            border-radius: 8px; padding: 0 20px; font-weight: bold; font-size: 13px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{ background-color: #e2e8f0; color: #94a3b8; }}
    """)
    return btn


class MainWindow(QMainWindow):
    """主窗口：左预览，中实例面板，右实例栏。"""

    def __init__(self, instance_manager: InstanceManager):
        super().__init__()
        self.instance_manager = instance_manager
        self._workspaces: dict[str, InstanceWorkspace] = {}
        self._instance_state_changed_at: dict[str, float] = {}
        self._active_instance_id: str = ''
        self._last_screenshot: Image.Image | None = None
        self._last_screenshot_time = 0.0
        self._pending_free_notice = self._is_free_notice_enabled()
        self._free_notice_shown = False
        self._instance_name_re = re.compile(r'^[A-Za-z0-9]+$')

        self._init_ui()
        self._init_instances()
        keyboard.add_hotkey('F9', self._on_pause)
        keyboard.add_hotkey('F10', self._on_stop)

    def _init_ui(self):
        """构建主界面布局：左侧截图预览，右侧控制区和标签页。"""
        self.setWindowTitle(APP_WINDOW_TITLE)
        icon_path = str(resolve_runtime_path('gui', 'icons', 'app_icon.ico'))
        if not os.path.exists(icon_path):
            icon_path = str(resolve_runtime_path('gui', 'icons', 'app_icon.svg'))
        self.setWindowIcon(QIcon(icon_path))

        ratio = self.devicePixelRatioF()
        base_min_width = int(540 / ratio) + 550
        base_init_width = int(540 / ratio) + 670
        rail_width = 100
        self.setMinimumWidth(base_min_width)
        self.resize(base_init_width, 100)
        self.setStyleSheet(_build_stylesheet())

        screen = self.screen().availableGeometry()
        size = self.geometry()
        self.move((screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._screenshot_label = QLabel('启动后显示\n实时截图')
        self._screenshot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._screenshot_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._screenshot_label.setFixedWidth(int(540 / ratio))
        self._screenshot_label.setFixedHeight(int(960 / ratio))
        self._screenshot_label.setStyleSheet(
            """
            QLabel { background-color: #ffffff; border: 1px solid #e2e8f0;
                     border-radius: 10px; color: #94a3b8; font-size: 14px; }
            """
        )
        root.addWidget(self._screenshot_label)

        self._workspace_stack = QStackedWidget()
        root.addWidget(self._workspace_stack, 1)

        self._instance_rail = QFrame()
        self._instance_rail.setObjectName('instanceRail')
        self._instance_rail.setFixedWidth(rail_width)
        self._instance_rail.setStyleSheet(
            """
            QFrame#instanceRail {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
            }
            QPushButton#instanceRailToggle {
                background: #f9fafb;
                border: 1px solid #e2e8f0;
                color: #334155;
                border-radius: 7px;
                font-weight: 600;
                padding: 0 2px;
            }
            QPushButton#instanceRailToggle:hover {
                background: #f1f5f9;
                border-color: #cbd5e1;
                color: #0f172a;
            }
            QListWidget#instanceRailList {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }
            QListWidget#instanceRailList::item {
                min-height: 26px;
                border-radius: 6px;
                padding: 2px 6px 2px 15px;
                color: #334155;
                font-size: 10px;
                font-weight: 600;
                text-align: left;
            }
            QListWidget#instanceRailList::item:hover:!selected {
                background: #f1f5f9;
            }
            QListWidget#instanceRailList::item:selected {
                background: #edf2ff;
                color: #1e3a8a;
            }
            """
        )
        rail_layout = QVBoxLayout(self._instance_rail)
        rail_layout.setContentsMargins(8, 8, 8, 8)
        rail_layout.setSpacing(8)
        self._instance_rail_toggle = QPushButton('管理')
        self._instance_rail_toggle.setObjectName('instanceRailToggle')
        self._instance_rail_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._instance_rail_toggle.setFixedHeight(30)
        self._instance_rail_toggle.clicked.connect(self._toggle_instance_drawer)
        rail_layout.addWidget(self._instance_rail_toggle, 0)

        self._instance_rail_list = QListWidget()
        self._instance_rail_list.setObjectName('instanceRailList')
        self._instance_rail_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._instance_rail_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._instance_rail_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._instance_rail_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._instance_rail_list.setItemDelegate(InstanceRailItemDelegate(self._instance_rail_list))
        self._instance_rail_list.itemSelectionChanged.connect(self._on_rail_instance_selected)
        rail_layout.addWidget(self._instance_rail_list, 1)

        root.addWidget(self._instance_rail, 0)

        self._instance_sidebar = InstanceSidebar()
        self._instance_sidebar.instance_selected.connect(self._switch_instance)
        self._instance_sidebar.create_requested.connect(self._on_instance_create)
        self._instance_sidebar.delete_requested.connect(self._on_instance_delete)
        self._instance_sidebar.clone_requested.connect(self._on_instance_clone)
        self._instance_sidebar.rename_requested.connect(self._on_instance_rename)
        self._instance_drawer = QFrame(central)
        self._instance_drawer.setObjectName('instanceDrawer')
        self._instance_drawer.setStyleSheet(
            """
            QFrame#instanceDrawer {
                background: rgba(255, 255, 255, 0.98);
                border: 1px solid #dbe3ef;
                border-radius: 10px;
            }
            """
        )
        self._instance_drawer.setFixedWidth(236)
        drawer_layout = QVBoxLayout(self._instance_drawer)
        drawer_layout.setContentsMargins(6, 6, 6, 6)
        drawer_layout.setSpacing(0)
        drawer_layout.addWidget(self._instance_sidebar, 1)
        self._instance_drawer.hide()

        rail_extra = rail_width + 10
        self.setMinimumWidth(base_min_width + rail_extra)
        if self.width() < base_init_width + rail_extra:
            self.resize(base_init_width + rail_extra, self.height())
        QTimer.singleShot(0, self._layout_instance_drawer)

    @staticmethod
    def _runtime_paths(session: InstanceSession) -> dict[str, str]:
        return {
            'config_path': str(session.paths.config_file),
            'logs_dir': str(session.paths.logs_dir),
            'screenshots_dir': str(session.paths.screenshots_dir),
            'error_dir': str(session.paths.error_dir),
        }

    def _create_instance_workspace(self, session: InstanceSession) -> InstanceWorkspace:
        engine = BotEngine(
            session.config,
            runtime_paths=self._runtime_paths(session),
            instance_id=session.instance_id,
            allow_idle_prewarm=False,
        )

        container = QWidget()
        right_layout = QVBoxLayout(container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_start = _make_btn('开始', '#16a34a', '#15803d')
        btn_pause = _make_btn('暂停', '#d97706', '#b45309')
        btn_stop = _make_btn('停止', '#dc2626', '#b91c1c')
        btn_run_once = _make_btn('立即执行', '#2563eb', '#1d4ed8')
        btn_pause.setEnabled(False)
        btn_stop.setEnabled(False)

        btn_start.clicked.connect(lambda: self._on_start(session.instance_id))
        btn_pause.clicked.connect(lambda: self._on_pause(session.instance_id))
        btn_stop.clicked.connect(lambda: self._on_stop(session.instance_id))
        btn_run_once.clicked.connect(lambda: self._on_run_once(session.instance_id))
        for btn in (btn_start, btn_pause, btn_stop, btn_run_once):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                border-top-left-radius: 0px;
                background: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background: #f1f5f9;
                color: #64748b;
                padding: 8px 20px;
                border: 1px solid #e2e8f0;
                border-bottom: 1px solid #e2e8f0;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #2563eb;
                font-weight: bold;
                border-bottom-color: #ffffff;
            }
            QTabBar::tab:!selected {
                margin-top: 4px;
            }
            QTabBar::tab:hover:!selected {
                background: #e2e8f0;
                color: #1e293b;
            }
            """
        )
        status_panel = StatusPanel()
        log_panel = LogPanel()

        log_group = QGroupBox('运行日志')
        log_group.setObjectName('logGroup')
        log_group.setStyleSheet(
            """
            QGroupBox#logGroup {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                margin-top: 12px;
                padding: 0px;
                font-weight: bold;
                color: #475569;
                background-color: #f8fafc;
            }
            QGroupBox#logGroup::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            """
        )
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 14, 8, 8)
        log_layout.setSpacing(0)
        log_layout.addWidget(log_panel)

        status_page = QWidget()
        status_layout = QVBoxLayout(status_page)
        status_layout.setContentsMargins(10, 10, 10, 10)
        status_layout.setSpacing(10)
        status_layout.addWidget(status_panel, 0, Qt.AlignmentFlag.AlignTop)
        status_layout.addWidget(log_group, 1)
        tabs.addTab(status_page, '状态')

        task_panel = TaskPanel(session.config)
        feature_panel = FeaturePanel(session.config)
        settings_panel = SettingsPanel(session.config)
        tabs.addTab(task_panel, '任务调度')
        tabs.addTab(feature_panel, '任务设置')
        tabs.addTab(settings_panel, '设置')
        right_layout.addWidget(tabs)

        workspace = InstanceWorkspace(
            instance_id=session.instance_id,
            name=session.name,
            session=session,
            container=container,
            engine=engine,
            status_panel=status_panel,
            log_panel=log_panel,
            task_panel=task_panel,
            feature_panel=feature_panel,
            settings_panel=settings_panel,
            btn_start=btn_start,
            btn_pause=btn_pause,
            btn_stop=btn_stop,
            btn_run_once=btn_run_once,
        )
        self._connect_workspace_signals(workspace)
        return workspace

    def _connect_workspace_signals(self, workspace: InstanceWorkspace) -> None:
        iid = workspace.instance_id
        engine = workspace.engine
        engine.log_message.connect(lambda text, _iid=iid: self._on_workspace_log(_iid, text))
        engine.screenshot_updated.connect(lambda image, _iid=iid: self._on_workspace_screenshot(_iid, image))
        engine.detection_result.connect(lambda image, _iid=iid: self._on_workspace_screenshot(_iid, image))
        engine.state_changed.connect(lambda state, _iid=iid: self._on_workspace_state_changed(_iid, state))
        engine.stats_updated.connect(workspace.status_panel.update_stats)

        workspace.settings_panel.config_changed.connect(
            lambda config, _iid=iid: self._on_workspace_config_changed(_iid, config)
        )
        workspace.task_panel.config_changed.connect(
            lambda config, _iid=iid: self._on_workspace_config_changed(_iid, config)
        )
        workspace.feature_panel.config_changed.connect(
            lambda config, _iid=iid: self._on_workspace_config_changed(_iid, config)
        )

    def _init_instances(self) -> None:
        self.instance_manager.load()
        for session in self.instance_manager.iter_sessions():
            workspace = self._create_instance_workspace(session)
            self._workspaces[session.instance_id] = workspace
            self._workspace_stack.addWidget(workspace.container)

        self._refresh_instance_sidebar()
        active = self.instance_manager.get_active()
        if active is None and self._workspaces:
            active = next(iter(self._workspaces.values())).session
        if active is not None:
            self._switch_instance(active.instance_id)

    def _refresh_instance_sidebar(self) -> None:
        items = []
        for session in self.instance_manager.iter_sessions():
            ws = self._workspaces.get(session.instance_id)
            state = ws.state if ws else 'idle'
            self._instance_state_changed_at.setdefault(session.instance_id, time.time())
            items.append({'id': session.instance_id, 'name': session.name, 'state': state})
        self._instance_sidebar.set_instances(items)
        if self._active_instance_id:
            self._instance_sidebar.set_active_instance(self._active_instance_id)
        self._refresh_instance_rail_list()

    @staticmethod
    def _rail_short_name(name: str) -> str:
        """实例名在窄轨上的短显示。"""
        text = str(name or '').strip()
        if not text:
            return '--'
        return text[:10]

    @staticmethod
    def _state_text(state: str) -> str:
        """状态英文值转中文。"""
        return {
            'running': '运行中',
            'paused': '已暂停',
            'idle': '空闲',
        }.get(str(state or 'idle').strip().lower(), '未知')

    def _format_state_changed_time(self, instance_id: str) -> str:
        """格式化实例状态最近更新时间。"""
        ts = float(self._instance_state_changed_at.get(str(instance_id or ''), 0.0) or 0.0)
        if ts <= 0:
            return '--'
        return time.strftime('%H:%M:%S', time.localtime(ts))

    def _refresh_instance_rail_list(self) -> None:
        """刷新窄轨实例列表，支持折叠状态直接切换。"""
        self._instance_rail_list.blockSignals(True)
        self._instance_rail_list.clear()
        current_row = -1
        row = 0
        for session in self.instance_manager.iter_sessions():
            ws = self._workspaces.get(session.instance_id)
            if ws is None:
                continue
            short = self._rail_short_name(ws.name)
            item = QListWidgetItem(short)
            state_text = self._state_text(ws.state)
            updated = self._format_state_changed_time(ws.instance_id)
            item.setData(RAIL_ROLE_INSTANCE_ID, ws.instance_id)
            item.setData(RAIL_ROLE_INSTANCE_STATE, ws.state)
            item.setToolTip(f'实例: {ws.name}\n状态: {state_text}\n最近更新: {updated}')
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._instance_rail_list.addItem(item)
            if ws.instance_id == self._active_instance_id:
                current_row = row
            row += 1
        if current_row >= 0:
            self._instance_rail_list.setCurrentRow(current_row)
        self._instance_rail_list.blockSignals(False)

    def _on_rail_instance_selected(self) -> None:
        """响应窄轨实例项点击并切换实例。"""
        item = self._instance_rail_list.currentItem()
        if item is None:
            return
        target_id = str(item.data(RAIL_ROLE_INSTANCE_ID) or '')
        if not target_id or target_id == self._active_instance_id:
            return
        self._switch_instance(target_id)

    def _layout_instance_drawer(self) -> None:
        """按当前窗口尺寸定位右侧实例抽屉（覆盖主区，不挤压布局）。"""
        central = self.centralWidget()
        if central is None or not hasattr(self, '_instance_drawer'):
            return
        margin = 12
        rail_geo = self._instance_rail.geometry()
        drawer_w = int(self._instance_drawer.width())
        drawer_h = max(260, int(central.height()) - margin * 2)
        anchor_x = int(rail_geo.x()) if rail_geo.width() > 0 else int(central.width()) - margin
        x = max(margin, anchor_x - drawer_w - 8)
        y = margin
        self._instance_drawer.setGeometry(x, y, drawer_w, drawer_h)
        if self._instance_drawer.isVisible():
            self._instance_drawer.raise_()

    def _set_instance_drawer_visible(self, visible: bool) -> None:
        """显示/隐藏右侧实例抽屉。"""
        self._layout_instance_drawer()
        self._instance_drawer.setVisible(bool(visible))
        if visible:
            self._instance_drawer.raise_()

    def _toggle_instance_drawer(self) -> None:
        """切换右侧实例抽屉显隐。"""
        self._set_instance_drawer_visible(not self._instance_drawer.isVisible())

    def _set_window_title_for_active(self) -> None:
        ws = self._workspaces.get(self._active_instance_id)
        if ws is None:
            self.setWindowTitle(APP_WINDOW_TITLE)
            return
        self.setWindowTitle(f'{APP_WINDOW_TITLE} [{ws.name}]')

    def _switch_instance(self, instance_id: str) -> None:
        ws = self._workspaces.get(str(instance_id or ''))
        if ws is None:
            return
        self.instance_manager.switch_active(ws.instance_id)
        self._active_instance_id = ws.instance_id
        self._workspace_stack.setCurrentWidget(ws.container)
        self._instance_sidebar.set_active_instance(ws.instance_id)
        self._set_window_title_for_active()
        if ws.last_preview is not None:
            self._update_screenshot(ws.last_preview, force=True)
        else:
            self._screenshot_label.setText('启动后显示\n实时截图')
            self._screenshot_label.setPixmap(QPixmap())
        self._sync_buttons(ws)
        self._refresh_instance_rail_list()

    def _workspace_running(self, ws: InstanceWorkspace) -> bool:
        state = str(ws.state or 'idle')
        return state in {'running', 'paused'}

    @staticmethod
    def _style_instance_dialog(dialog: QWidget) -> None:
        dialog.setStyleSheet(INSTANCE_DIALOG_STYLE)

    def _prompt_instance_name(self, *, title: str, label: str, default_text: str = '') -> tuple[str, bool]:
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setInputMode(QInputDialog.InputMode.TextInput)
        dialog.setTextValue(str(default_text or ''))
        dialog.setOkButtonText('确定')
        dialog.setCancelButtonText('取消')
        self._style_instance_dialog(dialog)
        ok = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.textValue().strip(), ok

    def _show_instance_warning(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._style_instance_dialog(box)
        ok_btn = box.button(QMessageBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText('确定')
        box.exec()

    def _show_instance_info(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._style_instance_dialog(box)
        ok_btn = box.button(QMessageBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText('确定')
        box.exec()

    def _confirm_instance_delete(self, name: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle('确认删除')
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f'确认删除实例 `{name}` 吗？')
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._style_instance_dialog(box)
        yes_btn = box.button(QMessageBox.StandardButton.Yes)
        no_btn = box.button(QMessageBox.StandardButton.No)
        if yes_btn is not None:
            yes_btn.setText('删除')
        if no_btn is not None:
            no_btn.setText('取消')
        return box.exec() == QMessageBox.StandardButton.Yes

    def _get_active_session(self) -> InstanceWorkspace | None:
        return self._workspaces.get(self._active_instance_id)

    def _sync_buttons(self, ws: InstanceWorkspace) -> None:
        running = self._workspace_running(ws)
        ws.btn_start.setEnabled(not running)
        ws.btn_pause.setEnabled(running)
        ws.btn_stop.setEnabled(running)
        ws.btn_pause.setText('恢复' if ws.state == 'paused' else '暂停')

    def _mark_instance_state_changed(self, instance_id: str) -> None:
        """记录实例状态更新时间。"""
        iid = str(instance_id or '')
        if not iid:
            return
        self._instance_state_changed_at[iid] = time.time()

    def _reset_process_logger_to_app_scope(self) -> None:
        ws = self._get_active_session()
        enable_debug = bool(ws and ws.session.config.safety.debug_log_enabled)
        setup_logger(log_dir=str(user_app_dir() / 'logs'), enable_debug=enable_debug)

    def _on_workspace_log(self, instance_id: str, text: str) -> None:
        ws = self._workspaces.get(instance_id)
        if ws is None:
            return
        ws.log_panel.append_log(text)

    def _on_workspace_screenshot(self, instance_id: str, image: Image.Image) -> None:
        ws = self._workspaces.get(instance_id)
        if ws is None:
            return
        ws.last_preview = image.copy()
        if instance_id == self._active_instance_id:
            self._update_screenshot(image)

    def _on_workspace_state_changed(self, instance_id: str, state: str) -> None:
        ws = self._workspaces.get(instance_id)
        if ws is None:
            return
        ws.state = str(state or 'idle')
        self._mark_instance_state_changed(instance_id)
        self._instance_sidebar.update_instance_state(instance_id, ws.state, ws.name)
        self._sync_buttons(ws)
        self._refresh_instance_rail_list()

    def _on_workspace_config_changed(self, instance_id: str, config: AppConfig) -> None:
        ws = self._workspaces.get(instance_id)
        if ws is None:
            return
        ws.session.config = config
        ws.session.touch()
        ws.engine.update_config(config)
        self.instance_manager.save()

    def _on_start(self, instance_id: str | None = None) -> None:
        iid = str(instance_id or self._active_instance_id or '')
        ws = self._workspaces.get(iid)
        if ws is None:
            return
        if ws.engine.start():
            ws.state = 'running'
            self._mark_instance_state_changed(ws.instance_id)
            self._sync_buttons(ws)
            self._instance_sidebar.update_instance_state(ws.instance_id, ws.state, ws.name)
            self._refresh_instance_rail_list()

    def _on_pause(self, instance_id: str | None = None) -> None:
        iid = str(instance_id or self._active_instance_id or '')
        ws = self._workspaces.get(iid)
        if ws is None or not self._workspace_running(ws):
            return
        if ws.btn_pause.text() == '暂停':
            ws.engine.pause()
            ws.state = 'paused'
        else:
            ws.engine.resume()
            ws.state = 'running'
        self._mark_instance_state_changed(ws.instance_id)
        self._sync_buttons(ws)
        self._instance_sidebar.update_instance_state(ws.instance_id, ws.state, ws.name)
        self._refresh_instance_rail_list()

    def _on_stop(self, instance_id: str | None = None) -> None:
        iid = str(instance_id or self._active_instance_id or '')
        ws = self._workspaces.get(iid)
        if ws is None:
            return
        ws.engine.stop()
        ws.state = 'idle'
        self._mark_instance_state_changed(ws.instance_id)
        ws.status_panel.update_stats(ws.engine.scheduler.get_stats())
        self._sync_buttons(ws)
        self._instance_sidebar.update_instance_state(ws.instance_id, ws.state, ws.name)
        self._refresh_instance_rail_list()

    def _on_run_once(self, instance_id: str | None = None) -> None:
        iid = str(instance_id or self._active_instance_id or '')
        ws = self._workspaces.get(iid)
        if ws is None:
            return
        ws.engine.run_once()

    def _on_instance_create(self) -> None:
        name, ok = self._prompt_instance_name(title='新增实例', label='实例名称:')
        if not ok:
            return
        text = str(name or '').strip()
        if not text:
            return
        if not self._instance_name_re.fullmatch(text):
            self._show_instance_warning('新增失败', '实例名仅支持英文和数字。')
            return
        try:
            session = self.instance_manager.create_instance(text)
        except Exception as exc:
            self._show_instance_warning('新增失败', str(exc))
            return

        ws = self._create_instance_workspace(session)
        self._workspaces[session.instance_id] = ws
        self._workspace_stack.addWidget(ws.container)
        self._refresh_instance_sidebar()
        self._switch_instance(session.instance_id)

    def _on_instance_clone(self, source_instance_id: str) -> None:
        source = self._workspaces.get(source_instance_id)
        if source is None:
            return
        name, ok = self._prompt_instance_name(
            title='克隆实例',
            label='新实例名称:',
            default_text=f'{source.name}Copy',
        )
        if not ok:
            return
        text = str(name or '').strip()
        if not text:
            return
        if not self._instance_name_re.fullmatch(text):
            self._show_instance_warning('克隆失败', '实例名仅支持英文和数字。')
            return
        try:
            session = self.instance_manager.clone_instance(source_instance_id, text)
        except Exception as exc:
            self._show_instance_warning('克隆失败', str(exc))
            return

        ws = self._create_instance_workspace(session)
        self._workspaces[session.instance_id] = ws
        self._workspace_stack.addWidget(ws.container)
        self._refresh_instance_sidebar()
        self._switch_instance(session.instance_id)

    def _on_instance_rename(self, instance_id: str) -> None:
        ws = self._workspaces.get(instance_id)
        if ws is None:
            return
        if self._workspace_running(ws):
            self._show_instance_info('重命名受限', '请先停止该实例再重命名。')
            return
        name, ok = self._prompt_instance_name(title='重命名实例', label='新实例名称:', default_text=ws.name)
        if not ok:
            return
        text = str(name or '').strip()
        if not text:
            return
        if not self._instance_name_re.fullmatch(text):
            self._show_instance_warning('重命名失败', '实例名仅支持英文和数字。')
            return
        old_id = ws.instance_id
        self._reset_process_logger_to_app_scope()
        ws.engine.stop(keep_prewarm=False)
        try:
            session = self.instance_manager.rename_instance(old_id, text)
        except Exception as exc:
            self._show_instance_warning('重命名失败', str(exc))
            return

        ws.instance_id = session.instance_id
        ws.name = session.name
        ws.session = session
        ws.engine.instance_id = session.instance_id
        ws.engine.runtime_paths = self._runtime_paths(session)
        ws.engine.update_config(session.config)
        self._workspaces.pop(old_id, None)
        self._workspaces[ws.instance_id] = ws
        old_state_ts = float(self._instance_state_changed_at.pop(old_id, 0.0) or 0.0)
        self._instance_state_changed_at[ws.instance_id] = old_state_ts if old_state_ts > 0 else time.time()
        self._refresh_instance_sidebar()
        self._switch_instance(ws.instance_id)

    def _on_instance_delete(self, instance_id: str) -> None:
        ws = self._workspaces.get(instance_id)
        if ws is None:
            return
        if self._workspace_running(ws):
            self._show_instance_info('删除受限', '请先停止该实例再删除。')
            return
        if len(self._workspaces) <= 1:
            self._show_instance_info('删除受限', '至少保留一个实例。')
            return
        if not self._confirm_instance_delete(ws.name):
            return
        self._reset_process_logger_to_app_scope()
        ws.engine.stop(keep_prewarm=False)
        try:
            self.instance_manager.delete_instance(instance_id)
        except Exception as exc:
            self._show_instance_warning('删除失败', str(exc))
            return

        self._workspace_stack.removeWidget(ws.container)
        ws.container.deleteLater()
        self._workspaces.pop(instance_id, None)
        self._instance_state_changed_at.pop(instance_id, None)
        self._refresh_instance_sidebar()
        active = self.instance_manager.get_active()
        if active is not None:
            self._switch_instance(active.instance_id)

    def _update_screenshot(self, image: Image.Image, force: bool = False):
        now = time.time()
        if not force and now - self._last_screenshot_time < 1.0:
            return
        self._last_screenshot_time = now

        try:
            self._last_screenshot = image.copy()
            image = image.convert('RGB')
            data = image.tobytes('raw', 'RGB')
            qimg = QImage(data, image.width, image.height, 3 * image.width, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            target_size = self._screenshot_label.size()
            if target_size.width() <= 0 or target_size.height() <= 0:
                return

            scaled_w = pixmap.scaledToWidth(target_size.width(), Qt.TransformationMode.SmoothTransformation)
            if scaled_w.height() >= target_size.height():
                offset_y = (scaled_w.height() - target_size.height()) // 2
                cropped = scaled_w.copy(0, offset_y, target_size.width(), target_size.height())
            else:
                cropped = scaled_w.scaled(
                    target_size,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            rounded = QPixmap(target_size)
            rounded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0, 0, target_size.width(), target_size.height(), 10, 10)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, cropped)
            painter.end()

            self._screenshot_label.setPixmap(rounded)
        except Exception:
            pass

    def _show_free_notice(self):
        box = QMessageBox(self)
        box.setWindowTitle('使用提示')
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            '<span style="font-size:16px; font-weight:700; color:#dc2626;">本软件完全免费，若付费购买请立即退款。</span>'
        )
        box.setInformativeText(
            '<span style="font-size:13px; font-weight:600; color:#b45309;">'
            '请通过项目主页获取最新版与公告，谨防二次售卖、捆绑分发或虚假收费。'
            '</span><br><br>'
            f'<span style="font-size:12px; color:#2563eb;">项目地址：{PROJECT_URL_TEXT}</span>'
        )
        box.setStyleSheet(
            """
            QMessageBox QPushButton { min-width: 102px; min-height: 30px; padding: 2px 10px; }
            QMessageBox QCheckBox { color: #334155; font-size: 12px; font-weight: 600; }
            """
        )
        text_label = box.findChild(QLabel, 'qt_msgbox_label')
        if text_label is not None:
            text_label.setWordWrap(True)
            text_label.setMinimumWidth(360)
            text_label.setMaximumWidth(430)
        info_label = box.findChild(QLabel, 'qt_msgbox_informativelabel')
        if info_label is not None:
            info_label.setWordWrap(True)
            info_label.setMinimumWidth(360)
            info_label.setMaximumWidth(430)
        dont_remind = QCheckBox('下次不再提醒')
        box.setCheckBox(dont_remind)
        open_btn = box.addButton('打开项目地址', QMessageBox.ButtonRole.ActionRole)
        box.addButton('我已知晓', QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if dont_remind.isChecked():
            self._set_free_notice_enabled(False)
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl(PROJECT_URL))

    @staticmethod
    def _is_free_notice_enabled() -> bool:
        settings = QSettings(APP_SETTINGS_ORG, APP_SETTINGS_NAME)
        raw = settings.value(FREE_NOTICE_ENABLED_KEY, True)
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() not in {'0', 'false', 'no'}

    @staticmethod
    def _set_free_notice_enabled(enabled: bool) -> None:
        settings = QSettings(APP_SETTINGS_ORG, APP_SETTINGS_NAME)
        settings.setValue(FREE_NOTICE_ENABLED_KEY, bool(enabled))
        settings.sync()

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_instance_drawer()
        if not hasattr(self, '_centered'):
            screen = self.screen().availableGeometry()
            size = self.frameGeometry()
            self.move((screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2)
            self._centered = True
        if self._pending_free_notice and not self._free_notice_shown:
            self._free_notice_shown = True
            QTimer.singleShot(0, self._show_free_notice)

    def closeEvent(self, event):
        for ws in self._workspaces.values():
            ws.engine.stop(keep_prewarm=False)
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_instance_drawer()
        if self._last_screenshot is not None:
            self._update_screenshot(self._last_screenshot, force=True)
