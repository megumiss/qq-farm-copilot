"""主窗口 - 单窗口多实例布局。"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time

import keyboard
from PIL import Image
from PyQt6.QtCore import QSettings, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
from utils.app_paths import resolve_runtime_path

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
        self._active_instance_id: str = ''
        self._last_screenshot: Image.Image | None = None
        self._last_screenshot_time = 0.0
        self._pending_free_notice = self._is_free_notice_enabled()
        self._free_notice_shown = False

        self._init_ui()
        self._init_instances()
        keyboard.add_hotkey('F9', self._on_pause)
        keyboard.add_hotkey('F10', self._on_stop)

    def _init_ui(self):
        self.setWindowTitle(APP_WINDOW_TITLE)
        icon_path = str(resolve_runtime_path('gui', 'icons', 'app_icon.ico'))
        if not os.path.exists(icon_path):
            icon_path = str(resolve_runtime_path('gui', 'icons', 'app_icon.svg'))
        self.setWindowIcon(QIcon(icon_path))

        ratio = self.devicePixelRatioF()
        self.setMinimumWidth(int(540 / ratio) + 760)
        self.resize(int(540 / ratio) + 860, 100)
        self.setStyleSheet(_build_stylesheet())

        screen = self.screen().availableGeometry()
        size = self.geometry()
        self.move((screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        from PyQt6.QtWidgets import QSizePolicy

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

        self._instance_sidebar = InstanceSidebar()
        self._instance_sidebar.instance_selected.connect(self._switch_instance)
        self._instance_sidebar.create_requested.connect(self._on_instance_create)
        self._instance_sidebar.delete_requested.connect(self._on_instance_delete)
        self._instance_sidebar.clone_requested.connect(self._on_instance_clone)
        self._instance_sidebar.rename_requested.connect(self._on_instance_rename)
        root.addWidget(self._instance_sidebar)

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
            items.append({'id': session.instance_id, 'name': session.name, 'state': state})
        self._instance_sidebar.set_instances(items)
        if self._active_instance_id:
            self._instance_sidebar.set_active_instance(self._active_instance_id)

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

    def _workspace_running(self, ws: InstanceWorkspace) -> bool:
        state = str(ws.state or 'idle')
        return state in {'running', 'paused'}

    def _get_active_session(self) -> InstanceWorkspace | None:
        return self._workspaces.get(self._active_instance_id)

    def _sync_buttons(self, ws: InstanceWorkspace) -> None:
        running = self._workspace_running(ws)
        ws.btn_start.setEnabled(not running)
        ws.btn_pause.setEnabled(running)
        ws.btn_stop.setEnabled(running)
        ws.btn_pause.setText('恢复' if ws.state == 'paused' else '暂停')

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
        self._instance_sidebar.update_instance_state(instance_id, ws.state, ws.name)
        self._sync_buttons(ws)

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
            self._sync_buttons(ws)
            self._instance_sidebar.update_instance_state(ws.instance_id, ws.state, ws.name)

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
        self._sync_buttons(ws)
        self._instance_sidebar.update_instance_state(ws.instance_id, ws.state, ws.name)

    def _on_stop(self, instance_id: str | None = None) -> None:
        iid = str(instance_id or self._active_instance_id or '')
        ws = self._workspaces.get(iid)
        if ws is None:
            return
        ws.engine.stop()
        ws.state = 'idle'
        ws.status_panel.update_stats(ws.engine.scheduler.get_stats())
        self._sync_buttons(ws)
        self._instance_sidebar.update_instance_state(ws.instance_id, ws.state, ws.name)

    def _on_run_once(self, instance_id: str | None = None) -> None:
        iid = str(instance_id or self._active_instance_id or '')
        ws = self._workspaces.get(iid)
        if ws is None:
            return
        ws.engine.run_once()

    def _on_instance_create(self) -> None:
        name, ok = QInputDialog.getText(self, '新增实例', '实例名称:')
        if not ok:
            return
        text = str(name or '').strip()
        if not text:
            return
        try:
            session = self.instance_manager.create_instance(text)
        except Exception as exc:
            QMessageBox.warning(self, '新增失败', str(exc))
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
        name, ok = QInputDialog.getText(self, '克隆实例', '新实例名称:', text=f'{source.name}-copy')
        if not ok:
            return
        text = str(name or '').strip()
        if not text:
            return
        try:
            session = self.instance_manager.clone_instance(source_instance_id, text)
        except Exception as exc:
            QMessageBox.warning(self, '克隆失败', str(exc))
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
            QMessageBox.information(self, '重命名受限', '请先停止该实例再重命名。')
            return
        name, ok = QInputDialog.getText(self, '重命名实例', '新实例名称:', text=ws.name)
        if not ok:
            return
        text = str(name or '').strip()
        if not text:
            return
        old_id = ws.instance_id
        try:
            session = self.instance_manager.rename_instance(old_id, text)
        except Exception as exc:
            QMessageBox.warning(self, '重命名失败', str(exc))
            return

        ws.engine.stop()
        ws.instance_id = session.instance_id
        ws.name = session.name
        ws.session = session
        ws.engine.instance_id = session.instance_id
        ws.engine.runtime_paths = self._runtime_paths(session)
        ws.engine.update_config(session.config)
        self._workspaces.pop(old_id, None)
        self._workspaces[ws.instance_id] = ws
        self._refresh_instance_sidebar()
        self._switch_instance(ws.instance_id)

    def _on_instance_delete(self, instance_id: str) -> None:
        ws = self._workspaces.get(instance_id)
        if ws is None:
            return
        if self._workspace_running(ws):
            QMessageBox.information(self, '删除受限', '请先停止该实例再删除。')
            return
        if len(self._workspaces) <= 1:
            QMessageBox.information(self, '删除受限', '至少保留一个实例。')
            return
        ret = QMessageBox.question(self, '确认删除', f'确认删除实例 `{ws.name}` 吗？')
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            self.instance_manager.delete_instance(instance_id)
        except Exception as exc:
            QMessageBox.warning(self, '删除失败', str(exc))
            return

        ws.engine.stop()
        self._workspace_stack.removeWidget(ws.container)
        ws.container.deleteLater()
        self._workspaces.pop(instance_id, None)
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
            ws.engine.stop()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._last_screenshot is not None:
            self._update_screenshot(self._last_screenshot, force=True)
