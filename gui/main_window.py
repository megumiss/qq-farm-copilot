"""旧入口断路器：主窗口入口已迁移到加载器。"""

from __future__ import annotations


class MainWindow:
    """阻断旧调用路径，避免继续依赖公开实现。"""

    def __init__(self, *_args, **_kwargs):
        raise RuntimeError(
            '`gui.main_window.MainWindow` 已停用。请改用 `gui.window_loader.build_main_window(config)`。'
        )
