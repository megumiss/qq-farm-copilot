"""主窗口 - 现代浅色主题

配色方案 (Clean Light):
  Background: #f5f5f7
  Card:       #ffffff
  Primary:    #2563eb (蓝)
  Success:    #16a34a (绿)
  Warning:    #d97706 (琥珀)
  Danger:     #dc2626 (红)
  Text:       #1e293b
  TextDim:    #94a3b8
  Border:     #e2e8f0
"""

import keyboard
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.bot_engine import BotEngine
from gui.widgets.log_panel import LogPanel
from gui.widgets.sell_panel import SellPanel
from gui.widgets.settings_panel import SettingsPanel
from gui.widgets.status_panel import StatusPanel
from models.config import AppConfig
from utils.logger import get_log_signal

STYLESHEET = """
QMainWindow { background-color: #f5f5f7; }
QWidget { color: #1e293b; font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif; font-size: 13px; }
QGroupBox {
    border: 1px solid #e2e8f0; border-radius: 8px;
    margin-top: 12px; padding: 14px 10px 8px 10px;
    font-weight: bold; color: #2563eb; background-color: #ffffff;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QCheckBox { spacing: 6px; color: #1e293b; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1.5px solid #cbd5e1; border-radius: 3px; background: #ffffff; }
QCheckBox::indicator:checked {
    background: #2563eb; border-color: #2563eb;
    image: url(gui/icons/check.svg);
}
QLineEdit, QSpinBox, QComboBox {
    background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 5px 8px; color: #1e293b; selection-background-color: #dbeafe;
    min-height: 20px;
}
QSpinBox::up-button { subcontrol-position: top right; width: 20px; border: none; background: #f1f5f9; border-top-right-radius: 5px; }
QSpinBox::down-button { subcontrol-position: bottom right; width: 20px; border: none; background: #f1f5f9; border-bottom-right-radius: 5px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #dbeafe; }
QSpinBox::up-arrow { image: url(gui/icons/arrow_up.svg); width: 10px; height: 6px; }
QSpinBox::down-arrow { image: url(gui/icons/arrow_down.svg); width: 10px; height: 6px; }
QComboBox::down-arrow { image: url(gui/icons/arrow_down.svg); width: 10px; height: 6px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #2563eb; }
QComboBox::drop-down { border: none; padding-right: 8px; }
QComboBox QAbstractItemView { background-color: #ffffff; color: #1e293b; border: 1px solid #e2e8f0; selection-background-color: #dbeafe; }
QScrollBar:vertical { background: #f5f5f7; width: 6px; border-radius: 3px; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def _card(widget: QWidget = None) -> QFrame:
    card = QFrame()
    card.setStyleSheet("""
        QFrame { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }
    """)
    if widget:
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
    return card


def _make_btn(text: str, color: str, hover: str) -> QPushButton:
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
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.engine = BotEngine(config)
        self._init_ui()
        self._connect_signals()
        keyboard.add_hotkey('F9', self._on_pause)
        keyboard.add_hotkey('F10', self._on_stop)

    def _init_ui(self):
        self.setWindowTitle('QQ Farm Vision Bot')
        self.setMinimumSize(960, 680)
        self.resize(1060, 740)
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ========== 左侧：截图预览（窄） ==========
        preview_card = QFrame()
        preview_card.setStyleSheet("""
            QFrame { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }
        """)
        preview_card.setFixedWidth(320)
        pv_layout = QVBoxLayout(preview_card)
        pv_layout.setContentsMargins(6, 6, 6, 6)
        self._screenshot_label = QLabel('启动后显示\n实时截图')
        self._screenshot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._screenshot_label.setStyleSheet("""
            QLabel { background-color: #f8fafc; border: 1px dashed #cbd5e1;
                     border-radius: 8px; color: #94a3b8; font-size: 14px; }
        """)
        pv_layout.addWidget(self._screenshot_label)
        root.addWidget(preview_card)

        # ========== 右侧：控制按钮 + Tab ==========
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 控制按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_start = _make_btn('开始', '#16a34a', '#15803d')
        self._btn_pause = _make_btn('暂停', '#d97706', '#b45309')
        self._btn_stop = _make_btn('停止', '#dc2626', '#b91c1c')
        self._btn_run_once = _make_btn('立即执行', '#2563eb', '#1d4ed8')
        self._btn_pause.setEnabled(False)
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_pause.clicked.connect(self._on_pause)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_run_once.clicked.connect(self._on_run_once)
        for b in (self._btn_start, self._btn_pause, self._btn_stop, self._btn_run_once):
            btn_row.addWidget(b)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        # Tab：状态 + 设置
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff; top: -1px; }
            QTabBar::tab {
                background: #f1f5f9; color: #64748b; padding: 6px 18px;
                border-top-left-radius: 8px; border-top-right-radius: 8px;
                margin-right: 2px; border: 1px solid #e2e8f0; border-bottom: none;
            }
            QTabBar::tab:selected { background: #ffffff; color: #2563eb; font-weight: bold; }
            QTabBar::tab:hover { background: #e2e8f0; }
        """)
        self._status_panel = StatusPanel()
        self._log_panel = LogPanel()
        status_page = QWidget()
        status_layout = QVBoxLayout(status_page)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        status_layout.addWidget(self._status_panel)
        status_layout.addWidget(_card(self._log_panel), 1)
        tabs.addTab(status_page, '状态')
        self._settings_panel = SettingsPanel(self.config)
        tabs.addTab(self._settings_panel, '设置')
        self._sell_panel = SellPanel(self.config)
        tabs.addTab(self._sell_panel, '出售')
        right_layout.addWidget(tabs)

        root.addWidget(right, 1)

    def _connect_signals(self):
        self.engine.log_message.connect(self._log_panel.append_log)
        self.engine.screenshot_updated.connect(self._update_screenshot)
        self.engine.detection_result.connect(self._update_screenshot)
        self.engine.state_changed.connect(self._on_state_changed)
        self.engine.stats_updated.connect(self._status_panel.update_stats)
        get_log_signal().new_log.connect(self._log_panel.append_log)
        self._settings_panel.config_changed.connect(self._on_config_changed)
        self._sell_panel.config_changed.connect(self._on_config_changed)

    def _update_screenshot(self, image: Image.Image):
        try:
            image = image.convert('RGB')
            data = image.tobytes('raw', 'RGB')
            qimg = QImage(data, image.width, image.height, 3 * image.width, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(
                self._screenshot_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._screenshot_label.setPixmap(scaled)
        except Exception:
            pass

    def _on_start(self):
        if self.engine.start():
            self._btn_start.setEnabled(False)
            self._btn_pause.setEnabled(True)
            self._btn_stop.setEnabled(True)

    def _on_pause(self):
        if self._btn_pause.text() == '暂停':
            self.engine.pause()
            self._btn_pause.setText('恢复')
        else:
            self.engine.resume()
            self._btn_pause.setText('暂停')

    def _on_stop(self):
        self.engine.stop()
        self._btn_start.setEnabled(True)
        self._btn_pause.setEnabled(False)
        self._btn_stop.setEnabled(False)
        self._btn_pause.setText('暂停')
        # 兜底刷新状态，避免线程信号时序导致面板停留在旧状态。
        self._status_panel.update_stats(self.engine.scheduler.get_stats())

    def _on_run_once(self):
        self.engine.run_once()

    def _on_state_changed(self, state: str):
        self._status_panel.update_stats(self.engine.scheduler.get_stats())

    def _on_config_changed(self, config: AppConfig):
        self.config = config
        self.engine.update_config(config)

    def closeEvent(self, event):
        self.engine.stop()
        super().closeEvent(event)
