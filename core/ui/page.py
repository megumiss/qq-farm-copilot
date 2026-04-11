"""nklite 页面图。"""

from __future__ import annotations

from core.base.button import Button
from core.ui.assets import *

# nklite 项目约定：未知页面回主界面统一点击固定坐标 (270, 20)。
GOTO_MAIN = Button(
    area=(270, 20, 271, 21),
    color=(128, 128, 128),
    button=(270, 20, 271, 21),
    file=None,
    name='goto_main',
)


class Page:
    """封装 `Page` 相关的数据与行为。"""

    parent = None

    def __init__(self, name: str, check_button, cn_name: str = ''):
        """初始化对象并准备运行所需状态。"""
        self.name = str(name).strip()
        if not self.name:
            raise ValueError('Page.name 不能为空')
        self.check_button = check_button
        self.links = {}
        self.cn_name = cn_name or self.name

    def __eq__(self, other):
        """定义对象相等比较逻辑。"""
        if not isinstance(other, Page):
            return False
        return self.name == other.name

    def __hash__(self):
        """定义对象哈希值，支持集合与字典键。"""
        return hash(self.name)

    def __str__(self):
        """返回对象的可读字符串表示。"""
        return self.name

    def link(self, button, destination):
        """执行 `link` 相关处理。"""
        self.links[destination] = button


page_main = Page('page_main', (MAIN_GOTO_FRIEND, MAIN_GOTO_MENU), cn_name='主页')

# Unknown
page_unknown = Page('page_unknown', None, cn_name='未知页面')
page_unknown.link(button=GOTO_MAIN, destination=page_main)

page_menu = Page('page_menu', SETTING_CHECK, cn_name='菜单')
page_mail = Page('page_mail', MAIL_CHECK, cn_name='邮箱')
page_shop = Page('page_shop', SHOP_CHECK, cn_name='商店')
page_friend_list = Page('page_friend_list', FRIEND_CHECK, cn_name='好友列表')
page_friend_farm = Page('page_friend_farm', BTN_HOME, cn_name='好友农场')
page_mall = Page('page_mall', MALL_CHECK, cn_name='商城')
page_pet = Page('page_pet', PET_CHECK, cn_name='宠物')
page_task = Page('page_task', TASK_CHECK, cn_name='任务')
page_warehouse = Page('page_warehouse', WAREHOUSE_CHECK, cn_name='仓库')
page_wiki = Page('page_wiki', WIKI_CHECK, cn_name='图鉴')

page_main.link(button=MAIN_GOTO_FRIEND, destination=page_friend_list)
page_friend_list.link(button=BTN_CLOSE, destination=page_main)

page_friend_farm.link(button=BTN_HOME, destination=page_main)

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

page_menu.link(button=MENU_GOTO_MAIL, destination=page_mail)
page_mail.link(button=BTN_CLOSE, destination=page_main)
