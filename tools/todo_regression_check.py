"""离线回归检查（对应 nklite 重构）。"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check_legacy_removed() -> None:
    """检查 `legacy_removed` 并返回结果。"""
    removed = [
        "core/scene_detector.py",
        "core/navigator.py",
        "core/page_checker.py",
        "core/page_graph.py",
        "core/ui_guard.py",
        "core/strategies",
    ]
    for rel in removed:
        assert not Path(rel).exists(), f"legacy file still exists: {rel}"


def check_nklite_pages() -> None:
    """检查 `nklite_pages` 并返回结果。"""
    src = Path("core/ui/page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    links: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "link":
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        src_page = node.func.value.id
        dest_page = None
        for kw in node.keywords:
            if kw.arg != "destination":
                continue
            if isinstance(kw.value, ast.Name):
                dest_page = kw.value.id
        if dest_page:
            links.add((src_page, dest_page))

    required = {
        ("page_unknown", "page_main"),
        ("page_friend", "page_main"),
        ("page_shop", "page_main"),
        ("page_menu", "page_main"),
        ("page_task", "page_main"),
        ("page_warehouse", "page_main"),
    }
    for route in required:
        assert route in links, f"missing page link: {route[0]} -> {route[1]}"


def check_nklite_tasks() -> None:
    """检查 `nklite_tasks` 并返回结果。"""
    task_files = [
        "core/tasks/task_farm_harvest.py",
        "core/tasks/task_farm_plant.py",
        "core/tasks/task_farm_sell.py",
        "core/tasks/task_farm_reward.py",
        "core/tasks/task_farm_friend.py",
        "core/tasks/task_farm_main.py",
    ]
    for rel in task_files:
        src = Path(rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        assert classes, f"no class in {rel}"
        fn_names = {n.name for n in ast.walk(classes[0]) if isinstance(n, ast.FunctionDef)}
        assert "run" in fn_names, f"{rel} missing run()"


def check_engine_tokens() -> None:
    """检查 `engine_tokens` 并返回结果。"""
    bot_engine = Path("core/engine/bot_engine.py").read_text(encoding="utf-8")

    task_main = Path("core/tasks/task_farm_main.py").read_text(encoding="utf-8")
    for token in ("detect_ms", "action_ms", "tick_ms", "task=farm_main page="):
        assert token in task_main, f"missing performance token: {token}"

    assert "_dispatch_scene_action" not in bot_engine, "legacy dispatcher still exists"
    assert "core.strategies" not in bot_engine, "legacy strategies import still exists"
    assert "core.scene_detector" not in bot_engine, "legacy scene detector import still exists"


def main() -> None:
    """程序主入口。"""
    check_legacy_removed()
    check_nklite_pages()
    check_nklite_tasks()
    check_engine_tokens()
    print("OK: nklite regression checks passed")


if __name__ == "__main__":
    main()


