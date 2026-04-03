"""nklite 页面图。"""

from __future__ import annotations

import traceback

from core.nklite.base.button import Button
from core.nklite.ui.assets import *

# nklite 项目约定：未知页面回主界面统一点击固定坐标 (270, 20)。
GOTO_MAIN = Button(
    area=(270, 20, 271, 21),
    color=(128, 128, 128),
    button=(270, 20, 271, 21),
    file=None,
    name='goto_main',
)


class Page:
    parent = None

    def __init__(self, check_button, cn_name: str = ''):
        self.check_button = check_button
        self.links = {}
        (_filename, _line, _function, text) = traceback.extract_stack()[-2]
        self.name = text[: text.find('=')].strip()
        self.cn_name = cn_name or self.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name

    def link(self, button, destination):
        self.links[destination] = button


page_main = Page((TASK_CHECK, MAIN_GOTO_MENU), cn_name='主页')

# Unknown
page_unknown = Page(None, cn_name='未知页面')
page_unknown.link(button=GOTO_MAIN, destination=page_main)

page_menu = Page(SETTING_CHECK, cn_name='菜单')
page_shop = Page(SHOP_CHECK, cn_name='商店')
page_friend = Page(FRIEND_CHECK, cn_name='好友')
page_mall = Page(MALL_CHECK, cn_name='商城')
page_pet = Page(PET_CHECK, cn_name='宠物')
page_task = Page(TASK_CHECK, cn_name='任务')
page_warehouse = Page(WAREHOUSE_CHECK, cn_name='仓库')
page_wiki = Page(WIKI_CHECK, cn_name='图鉴')

page_main.link(button=MAIN_GOTO_FRIEND, destination=page_friend)
page_friend.link(button=BTN_CLOSE, destination=page_main)

page_main.link(button=MAIN_GOTO_SHOP, destination=page_shop)
page_shop.link(button=BTN_CLOSE, destination=page_main)

page_main.link(button=MAIN_GOTO_MALL, destination=page_mall)
page_mall.link(button=MALL_GOTO_MAIN, destination=page_main)

page_main.link(button=MAIN_GOTO_PET, destination=page_pet)
page_pet.link(button=BTN_CLOSE, destination=page_main)

page_main.link(button=MAIN_GOTO_TASK, destination=page_task)
page_task.link(button=BTN_CLOSE, destination=page_main)

page_main.link(button=MAIN_GOTO_WAREHOUSE, destination=page_warehouse)
page_warehouse.link(button=BTN_CLOSE, destination=page_main)

page_main.link(button=MAIN_GOTO_WIKI, destination=page_wiki)
page_wiki.link(button=BTN_CLOSE, destination=page_main)

page_main.link(button=MAIN_GOTO_MENU, destination=page_menu)
page_menu.link(button=MENU_GOTO_MAIN, destination=page_main)
