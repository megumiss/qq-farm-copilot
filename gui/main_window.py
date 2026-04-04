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

import os

import keyboard
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.engine.bot_engine import BotEngine
from gui.widgets.feature_panel import FeaturePanel
from gui.widgets.log_panel import LogPanel
from gui.widgets.settings_panel import SettingsPanel
from gui.widgets.status_panel import StatusPanel
from gui.widgets.task_panel import TaskPanel
from models.config import AppConfig
from utils.logger import get_log_signal

STYLESHEET = """
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
    """创建统一卡片容器，并可选包裹一个子控件。"""
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
    """主窗口：组合预览、日志、任务面板并驱动 BotEngine。"""
    def __init__(self, config: AppConfig):
        """初始化主窗口与引擎，并注册全局热键。"""
        super().__init__()
        self.config = config
        self.engine = BotEngine(config)
        self._init_ui()
        self._connect_signals()
        keyboard.add_hotkey('F9', self._on_pause)
        keyboard.add_hotkey('F10', self._on_stop)

    def _init_ui(self):
        """构建主界面布局：左侧截图预览，右侧控制区和标签页。"""
        self.setWindowTitle('QQ Farm Vision Bot')
        icon_path = os.path.join(os.path.dirname(__file__), 'icons', 'app_icon.svg')
        self.setWindowIcon(QIcon(icon_path))
        
        # 动态获取当前屏幕的 DPI 缩放比例
        ratio = self.devicePixelRatioF()
        
        self.setMinimumSize(int(540 / ratio) + 500, int(960 / ratio) + 40)
        self.resize(int(540 / ratio) + 620, int(960 / ratio) + 80)
        self.setStyleSheet(STYLESHEET)

        # 根容器：左右分栏，左窄右宽。
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ========== 左侧：截图预览 ==========
        from PyQt6.QtWidgets import QSizePolicy
        self._screenshot_label = QLabel('启动后显示\n实时截图')
        self._screenshot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._screenshot_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # 保持物理宽度为 540 像素，高度随窗口自由拉伸，使得左右两边永远对齐
        self._screenshot_label.setFixedWidth(int(540 / ratio))
        self._screenshot_label.setStyleSheet("""
            QLabel { background-color: #ffffff; border: 1px solid #e2e8f0;
                     border-radius: 10px; color: #94a3b8; font-size: 14px; }
        """)
        root.addWidget(self._screenshot_label)

        # ========== 右侧：控制按钮 + Tab ==========
        # 顶部放运行控制按钮，底部放状态与配置标签页。
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
        # 标签页顺序按“运行信息 -> 调度 -> 任务设置 -> 程序设置”组织。
        tabs = QTabWidget()
        tabs.setStyleSheet("""
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
        """)
        self._status_panel = StatusPanel()
        self._log_panel = LogPanel()
        
        log_group = QGroupBox("运行日志")
        log_group.setObjectName("logGroup")
        log_group.setStyleSheet("""
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
        """)
        log_layout = QVBoxLayout(log_group)
        # 给标题区和日志正文留出间隔，避免标题被内容区域“贴住”。
        log_layout.setContentsMargins(8, 14, 8, 8)
        log_layout.setSpacing(0)
        log_layout.addWidget(self._log_panel)

        status_page = QWidget()
        status_layout = QVBoxLayout(status_page)
        status_layout.setContentsMargins(10, 10, 10, 10)
        status_layout.setSpacing(10)
        status_layout.addWidget(self._status_panel, 0, Qt.AlignmentFlag.AlignTop)
        status_layout.addWidget(log_group, 1)
        tabs.addTab(status_page, '状态')
        self._task_panel = TaskPanel(self.config)
        tabs.addTab(self._task_panel, '任务调度')
        self._feature_panel = FeaturePanel(self.config)
        tabs.addTab(self._feature_panel, '任务设置')
        self._settings_panel = SettingsPanel(self.config)
        tabs.addTab(self._settings_panel, '设置')
        right_layout.addWidget(tabs)

        root.addWidget(right, 1)

    def _connect_signals(self):
        """连接引擎信号与各面板更新逻辑。"""
        self.engine.log_message.connect(self._log_panel.append_log)
        self.engine.screenshot_updated.connect(self._update_screenshot)
        self.engine.detection_result.connect(self._update_screenshot)
        self.engine.state_changed.connect(self._on_state_changed)
        self.engine.stats_updated.connect(self._status_panel.update_stats)
        get_log_signal().new_log.connect(self._log_panel.append_log)
        self._settings_panel.config_changed.connect(self._on_config_changed)
        self._task_panel.config_changed.connect(self._on_config_changed)
        self._feature_panel.config_changed.connect(self._on_config_changed)

    def _update_screenshot(self, image: Image.Image):
        """将 PIL 图像转为 QPixmap 并按预览区尺寸缩放显示。"""
        try:
            image = image.convert('RGB')
            data = image.tobytes('raw', 'RGB')
            qimg = QImage(data, image.width, image.height, 3 * image.width, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            target_size = self._screenshot_label.size()
            if target_size.width() <= 0 or target_size.height() <= 0:
                return

            # 先按“填满”缩放，再中心裁剪到控件尺寸，避免上下留白。
            scaled = pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset_x = max((scaled.width() - target_size.width()) // 2, 0)
            offset_y = max((scaled.height() - target_size.height()) // 2, 0)
            cropped = scaled.copy(offset_x, offset_y, target_size.width(), target_size.height())

            # 再对最终图像做圆角裁剪：图片依然充满，仅圆角重叠部分被遮挡。
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

    def _on_start(self):
        """点击“开始”后启动引擎并更新按钮可用状态。"""
        if self.engine.start():
            self._btn_start.setEnabled(False)
            self._btn_pause.setEnabled(True)
            self._btn_stop.setEnabled(True)

    def _on_pause(self):
        """在暂停/恢复之间切换执行状态。"""
        if self._btn_pause.text() == '暂停':
            self.engine.pause()
            self._btn_pause.setText('恢复')
        else:
            self.engine.resume()
            self._btn_pause.setText('暂停')

    def _on_stop(self):
        """停止引擎并立即刷新界面状态。"""
        self.engine.stop()
        self._btn_start.setEnabled(True)
        self._btn_pause.setEnabled(False)
        self._btn_stop.setEnabled(False)
        self._btn_pause.setText('暂停')
        # 兜底刷新状态，避免线程信号时序导致面板停留在旧状态。
        self._status_panel.update_stats(self.engine.scheduler.get_stats())

    def _on_run_once(self):
        """触发一次立即执行。"""
        self.engine.run_once()

    def _on_state_changed(self, state: str):
        """状态变化时刷新状态统计。"""
        self._status_panel.update_stats(self.engine.scheduler.get_stats())

    def _on_config_changed(self, config: AppConfig):
        """接收子面板配置变更并同步到引擎。"""
        self.config = config
        self.engine.update_config(config)

    def closeEvent(self, event):
        """窗口关闭时执行收尾清理。"""
        self.engine.stop()
        super().closeEvent(event)

