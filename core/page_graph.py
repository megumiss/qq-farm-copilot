"""页面图定义与最短下一跳计算。"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

from core.scene_detector import Scene


class PageId(str, Enum):
    MAIN = "main"
    POPUP = "popup"
    SHOP = "shop"
    BUY_CONFIRM = "buy_confirm"
    PLOT_MENU = "plot_menu"
    SEED_SELECT = "seed_select"
    FRIEND = "friend"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class NavAction:
    name: str
    description: str
    candidates: tuple[str, ...] = ()
    candidate_prefixes: tuple[str, ...] = ()
    click_blank: bool = False


class PageGraph:
    """页面图：仅负责路由，不做识别/点击。"""

    def __init__(self):
        self._edges: dict[PageId, dict[PageId, NavAction]] = {
            PageId.MAIN: {
                PageId.SHOP: NavAction(
                    name="open_shop",
                    description="打开商店",
                    candidates=("btn_shop",),
                ),
                PageId.FRIEND: NavAction(
                    name="goto_friend",
                    description="好友求助",
                    candidates=("btn_friend_help",),
                ),
            },
            PageId.SHOP: {
                PageId.MAIN: NavAction(
                    name="close_shop",
                    description="关闭商店",
                    candidates=("btn_shop_close", "btn_close"),
                ),
            },
            PageId.FRIEND: {
                PageId.MAIN: NavAction(
                    name="back_home",
                    description="回家",
                    candidates=("btn_home",),
                ),
            },
            PageId.POPUP: {
                PageId.MAIN: NavAction(
                    name="close_popup",
                    description="关闭弹窗",
                    candidates=("btn_claim", "btn_confirm", "btn_close", "btn_cancel"),
                ),
            },
            PageId.BUY_CONFIRM: {
                PageId.MAIN: NavAction(
                    name="close_confirm",
                    description="关闭购买弹窗",
                    candidates=("btn_confirm", "btn_close", "btn_cancel"),
                ),
            },
            PageId.PLOT_MENU: {
                PageId.SEED_SELECT: NavAction(
                    name="open_seed_select",
                    description="打开种子列表",
                    candidates=("btn_plant",),
                ),
                PageId.MAIN: NavAction(
                    name="dismiss_plot_menu",
                    description="点击空白处",
                    click_blank=True,
                ),
            },
            PageId.SEED_SELECT: {
                PageId.PLOT_MENU: NavAction(
                    name="pick_seed",
                    description="选择种子",
                    candidate_prefixes=("seed_",),
                ),
                PageId.MAIN: NavAction(
                    name="dismiss_seed_select",
                    description="点击空白处",
                    click_blank=True,
                ),
            },
            PageId.UNKNOWN: {
                PageId.MAIN: NavAction(
                    name="recover_unknown",
                    description="点击空白处",
                    click_blank=True,
                ),
            },
        }

    def next_action(self, current: PageId, target: PageId) -> NavAction | None:
        """返回 current 到 target 的最短路径第一跳动作。"""
        if current == target:
            return None

        queue: deque[PageId] = deque([current])
        visited: set[PageId] = {current}
        parent: dict[PageId, PageId] = {}

        while queue:
            node = queue.popleft()
            for nxt in self._edges.get(node, {}):
                if nxt in visited:
                    continue
                visited.add(nxt)
                parent[nxt] = node
                if nxt == target:
                    queue.clear()
                    break
                queue.append(nxt)

        if target not in parent:
            return None

        cur = target
        while parent[cur] != current:
            cur = parent[cur]
        return self._edges[current][cur]


def scene_to_page(scene: Scene) -> PageId:
    if scene == Scene.FARM_OVERVIEW:
        return PageId.MAIN
    if scene in (Scene.POPUP, Scene.LEVEL_UP):
        return PageId.POPUP
    if scene == Scene.SHOP_PAGE:
        return PageId.SHOP
    if scene == Scene.BUY_CONFIRM:
        return PageId.BUY_CONFIRM
    if scene == Scene.PLOT_MENU:
        return PageId.PLOT_MENU
    if scene == Scene.SEED_SELECT:
        return PageId.SEED_SELECT
    if scene == Scene.FRIEND_FARM:
        return PageId.FRIEND
    return PageId.UNKNOWN
