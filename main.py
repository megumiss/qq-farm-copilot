"""QQ Farm Copilot - 程序入口"""

import multiprocessing as mp
import os
import sys

DPI_SCALE_ENV = 'QQFARM_DPI_SCALE'
DEFAULT_DPI_SCALE = 'Auto'


def _apply_qt_dpi_env_early() -> None:
    """在导入 PyQt 前应用 DPI 配置，确保 Qt 能读取到环境变量。"""
    dpi_scale = str(os.environ.get(DPI_SCALE_ENV, DEFAULT_DPI_SCALE)).strip()
    if not dpi_scale or dpi_scale.lower() == 'auto':
        return
    os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '0'
    os.environ['QT_SCALE_FACTOR'] = dpi_scale


_apply_qt_dpi_env_early()

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QWidget

from core.instance.manager import InstanceManager
from utils.app_paths import resolve_runtime_path, user_app_dir
from utils.logger import cleanup_expired_logs, load_log_retention_days, setup_logger


class _NoWheelSpinBoxFilter(QObject):
    """全局拦截数字输入框滚轮事件，避免悬停时误改值。"""

    @staticmethod
    def _spin_ancestor(widget: QWidget | None) -> QAbstractSpinBox | None:
        current = widget
        while current is not None:
            if isinstance(current, QAbstractSpinBox):
                return current
            current = current.parentWidget()
        return None

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        widget = watched if isinstance(watched, QWidget) else None
        if widget is None:
            return False
        if self._spin_ancestor(widget) is None:
            return False
        event.ignore()
        return True


def _resolve_app_icon_path() -> str:
    """优先使用 ico 图标，找不到时回退 svg。"""
    ico = resolve_runtime_path('gui', 'icons', 'app_icon.ico')
    if ico.exists():
        return str(ico)
    return str(resolve_runtime_path('gui', 'icons', 'app_icon.svg'))


def _set_windows_app_id() -> None:
    """设置 Windows AppUserModelID，确保任务栏图标与分组正确。"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('QQFarmCopilot')
    except Exception:
        pass


def main():
    # 初始化实例管理器
    instance_manager = InstanceManager()
    instance_manager.load()
    active = instance_manager.get_active()
    enable_debug = bool(active and active.config.safety.debug_log_enabled)
    log_retention_days = load_log_retention_days()
    log_dir = str(user_app_dir() / 'logs')

    # 初始化日志（主进程日志）
    setup_logger(log_dir=log_dir, enable_debug=enable_debug, retention_days=log_retention_days)
    cleanup_expired_logs(user_app_dir(), retention_days=log_retention_days)

    # 启动GUI
    _set_windows_app_id()
    app = QApplication(sys.argv)
    try:
        from qfluentwidgets import Theme, setTheme, setThemeColor

        setTheme(Theme.AUTO)
        setThemeColor('#2563eb')
    except Exception:
        app.setStyle('Fusion')
    wheel_filter = _NoWheelSpinBoxFilter(app)
    app.installEventFilter(wheel_filter)
    app._no_wheel_spin_box_filter = wheel_filter
    icon_path = _resolve_app_icon_path()
    app.setWindowIcon(QIcon(icon_path))

    # 延迟导入 GUI 加载器
    from gui.window_loader import build_main_window

    window = build_main_window(instance_manager)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    mp.freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        # 在调试器或终端主动中断时静默退出，避免额外抛出 SystemExit 干扰开发体验。
        pass
