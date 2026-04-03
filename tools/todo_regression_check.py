"""离线回归检查（对应 TODO.md 第 7 节）。

说明：
- 这是静态/离线 smoke 检查，不依赖游戏实机。
- 覆盖导航路由、策略契约、性能埋点三类改造。
"""
from __future__ import annotations

from pathlib import Path
import ast
import sys
import types
from enum import Enum

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _import_page_graph():
    """导入 page_graph，避免依赖完整运行环境。"""
    fake_scene = types.ModuleType("core.scene_detector")

    class Scene(str, Enum):
        FARM_OVERVIEW = "farm_overview"
        FRIEND_FARM = "friend_farm"
        PLOT_MENU = "plot_menu"
        SEED_SELECT = "seed_select"
        SHOP_PAGE = "shop_page"
        BUY_CONFIRM = "buy_confirm"
        POPUP = "popup"
        LEVEL_UP = "level_up"
        UNKNOWN = "unknown"

    fake_scene.Scene = Scene
    sys.modules.setdefault("core.scene_detector", fake_scene)

    from core.page_graph import PageGraph, PageId  # noqa

    return PageGraph, PageId


def check_navigation_routes() -> None:
    PageGraph, PageId = _import_page_graph()
    g = PageGraph()
    for src in (PageId.UNKNOWN, PageId.POPUP, PageId.SHOP, PageId.FRIEND):
        action = g.next_action(src, PageId.MAIN)
        assert action is not None, f"missing route: {src.value} -> main"


def check_strategy_contracts() -> None:
    strategy_files = [
        "core/strategies/harvest.py",
        "core/strategies/maintain.py",
        "core/strategies/popup.py",
        "core/strategies/friend.py",
        "core/strategies/expand.py",
        "core/strategies/sell.py",
        "core/strategies/task.py",
        "core/strategies/plant.py",
    ]
    for rel in strategy_files:
        src = Path(rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        assert classes, f"no class in {rel}"
        cls = classes[0]
        assign_names = set()
        fn_names = set()
        for node in cls.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        assign_names.add(t.id)
            if isinstance(node, ast.FunctionDef):
                fn_names.add(node.name)
        assert "requires_page" in assign_names, f"{rel} missing requires_page"
        assert "expected_page_after" in assign_names, f"{rel} missing expected_page_after"
        assert "run_once" in fn_names, f"{rel} missing run_once"


def check_performance_instrumentation() -> None:
    bot_engine = Path("core/bot_engine.py").read_text(encoding="utf-8")
    for token in ("detect_ms", "action_ms", "tick_ms", "task=farm_main page="):
        assert token in bot_engine, f"missing performance token: {token}"
    assert "def _categories_for_tick" in bot_engine, "missing category slicing hook"

    tree = ast.parse(bot_engine)
    fn_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_dispatch_scene_action" in fn_names, "missing scene dispatcher"


def main() -> None:
    check_navigation_routes()
    check_strategy_contracts()
    check_performance_instrumentation()
    print("OK: offline regression checks passed")


if __name__ == "__main__":
    main()
