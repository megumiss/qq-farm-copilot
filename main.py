"""QQ Farm Copilot - 程序入口"""

import multiprocessing as mp
import os
import sys

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from core.instance.manager import InstanceManager
from utils.app_paths import resolve_runtime_path
from utils.logger import setup_logger


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
    log_dir = str(active.paths.logs_dir) if active is not None else 'logs'

    # 初始化日志（主进程日志）
    setup_logger(log_dir=log_dir, enable_debug=enable_debug)

    # 启动GUI
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    icon_path = _resolve_app_icon_path()
    app.setWindowIcon(QIcon(icon_path))

    # 延迟导入
    from gui.main_window import MainWindow

    window = MainWindow(instance_manager)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    mp.freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        # 调试器停止或终端中断时，直接退出，避免输出误导性的 traceback。
        sys.exit(130)
