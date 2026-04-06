"""好友求助任务。"""

from __future__ import annotations

from loguru import logger

from core.base.button import Button
from core.base.timer import Timer
from core.engine.task.registry import TaskResult
from core.ui.assets import (
    BTN_BUG,
    BTN_HOME,
    BTN_STEAL,
    BTN_VISIT_FIRST,
    BTN_WATER,
    BTN_WEED,
    ICON_BUG_IN_FRIEND_DETAIL,
    ICON_BUG_IN_FRIEND_LIST,
    ICON_STEAL_IN_FRIEND_DETAIL,
    ICON_STEAL_IN_FRIEND_LIST,
    ICON_WATER_IN_FRIEND_DETAIL,
    ICON_WATER_IN_FRIEND_LIST,
    ICON_WEED_IN_FRIEND_DETAIL,
    ICON_WEED_IN_FRIEND_LIST,
    MAIN_GOTO_FRIEND,
)
from core.ui.page import page_friend
from models.farm_state import ActionType
from tasks.base import TaskBase

FRIEND_DETAIL_ICON_X_RANGE = (70, 540)
FRIEND_DETAIL_ICON_Y_RANGE = (815, 855)
FRIEND_PAGE_ICON_X_RANGE = (105, 410)
FRIEND_PAGE_ICON_Y_RANGE = (260, 800)


class TaskFriend(TaskBase):
    """封装 `TaskFriend` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行主流程：递进遍历可操作好友，直到没有可继续目标。"""
        _ = rect
        features = self.get_features('friend')
        enable_steal = self.has_feature(features, 'auto_steal')
        enable_help = self.has_feature(features, 'auto_help')
        logger.info('好友流程: 开始 | 偷菜={} 帮忙={}', enable_steal, enable_help)
        if not enable_steal and not enable_help:
            logger.info('好友流程: 未启用任何功能，结束')
            return self.ok()

        # 进入好友列表页
        self.ui.ui_ensure(page_friend)
        # 等待列表加载
        self.wait_list_loading()

        actions = self._run_friend_progressive(enable_help=enable_help, enable_steal=enable_steal)
        actions = self._compact_actions(actions)
        # 返回主页
        self.back_to_home()
        logger.info('好友流程: 结束 | 动作={}', '、'.join(actions) if actions else '无动作')

        return self.ok(actions=actions)

    def _run_friend_progressive(self, *, enable_help: bool, enable_steal: bool) -> list[str]:
        """好友任务递进流程：进入详情后执行动作，再切到下一个可操作好友。"""
        actions: list[str] = []
        if not self._enter_friend_detail():
            return actions

        self._run_friend_recursive(enable_help=enable_help, enable_steal=enable_steal, actions=actions)
        return actions

    @staticmethod
    def _compact_actions(actions: list[str]) -> list[str]:
        """压缩好友任务动作，避免日志中出现过长明细。"""
        if not actions:
            return []

        steal_count = sum(1 for item in actions if '偷好友果实' in item)
        help_count = sum(1 for item in actions if item.startswith('好友帮忙'))

        compact: list[str] = []
        if steal_count > 0:
            compact.append(f'好友偷菜×{steal_count}')
        if help_count > 0:
            compact.append(f'好友帮忙×{help_count}')
        if not compact:
            compact.append('好友互动')
        return compact

    def _run_friend_recursive(self, *, enable_help: bool, enable_steal: bool, actions: list[str]):
        """递归处理当前好友并切换到下一位可操作好友。"""

        if enable_steal:
            action = self._run_feature_steal()
            if action:
                actions.append(action)

        if enable_help:
            action = self._run_feature_help()
            if action:
                actions.append(action)

        if not self._goto_next_operable_friend(enable_help=enable_help, enable_steal=enable_steal):
            return

        self._run_friend_recursive(enable_help=enable_help, enable_steal=enable_steal, actions=actions)

    def _enter_friend_detail(self) -> bool:
        """从好友列表页进入某个好友详情页。"""
        # 查找列表上的操作图标
        self.ui.device.screenshot()
        features = self.get_features('friend')
        list_steal = self._collect_operable_friend_list_icons(
            enable_steal=self.has_feature(features, 'auto_steal'),
        )
        list_help = self._collect_operable_friend_list_icons(
            enable_help=self.has_feature(features, 'auto_help'),
        )
        logger.info('好友流程: 列表可操作目标 | 偷菜={} 帮忙={}', len(list_steal), len(list_help))

        # 进入详情页
        if list_steal or list_help:
            while 1:
                self.ui.device.screenshot()
                if self.ui.appear_then_click(BTN_VISIT_FIRST, offset=30, interval=1):
                    continue
                if self.ui.appear(BTN_HOME, offset=30):
                    logger.info('好友流程: 已进入好友详情页')
                    return True

        logger.info('好友流程: 未进入好友详情页，结束本轮')
        return False

    def _goto_next_operable_friend(self, *, enable_help: bool, enable_steal: bool) -> bool:
        """点击下一个可执行操作的好友。"""
        self.ui.device.stuck_record_clear()
        self.ui.device.click_record_clear()

        self.ui.device.screenshot()

        candidates = self._collect_operable_friend_icons(enable_help=enable_help, enable_steal=enable_steal)
        if candidates:
            if self.ui.device.click_button(candidates[0]):
                logger.info('好友流程: 切换下一位好友')
                self.ui.device.sleep(0.5)
                return True

        logger.info('好友流程: 未找到下一位可操作好友')
        return False

    def _collect_operable_friend_icons(self, *, enable_help: bool, enable_steal: bool) -> list[Button]:
        """按启用功能收集下方横向列表中的可操作 icon（detail 模板）。"""
        icons: list[Button] = []
        if enable_steal:
            icons.extend(self.ui.match_icon_multi(ICON_STEAL_IN_FRIEND_DETAIL, threshold=0.75))
        if enable_help:
            icons.extend(self.ui.match_icon_multi(ICON_WATER_IN_FRIEND_DETAIL, threshold=0.75))
            icons.extend(self.ui.match_icon_multi(ICON_WEED_IN_FRIEND_DETAIL, threshold=0.75))
            icons.extend(self.ui.match_icon_multi(ICON_BUG_IN_FRIEND_DETAIL, threshold=0.75))

        if not icons:
            return []
        icons = self.ui.filter_buttons_in_area(
            icons, x_range=FRIEND_DETAIL_ICON_X_RANGE, y_range=FRIEND_DETAIL_ICON_Y_RANGE
        )
        icons = self.ui.sort_buttons_by_location(icons, horizontal=True)
        return icons

    def _collect_operable_friend_list_icons(
        self, *, enable_help: bool = False, enable_steal: bool = False
    ) -> list[Button]:
        """收集好友列表页（纵向）上的可操作 icon（list 模板）。"""
        icons: list[Button] = []
        if enable_steal:
            icons.extend(self.ui.match_icon_multi(ICON_STEAL_IN_FRIEND_LIST, threshold=0.75))
        if enable_help:
            icons.extend(self.ui.match_icon_multi(ICON_WATER_IN_FRIEND_LIST, threshold=0.75))
            icons.extend(self.ui.match_icon_multi(ICON_WEED_IN_FRIEND_LIST, threshold=0.75))
            icons.extend(self.ui.match_icon_multi(ICON_BUG_IN_FRIEND_LIST, threshold=0.75))

        if not icons:
            return []
        icons = self.ui.filter_buttons_in_area(
            icons, x_range=FRIEND_PAGE_ICON_X_RANGE, y_range=FRIEND_PAGE_ICON_Y_RANGE
        )
        # 好友列表页按纵向优先（y -> x）排序，优先从上往下处理。
        icons = self.ui.sort_buttons_by_location(icons, horizontal=False)
        return icons

    def _run_feature_help(self) -> str | None:
        """好友帮忙。"""
        actions_done = self._help_in_friend_farm()
        if not actions_done:
            return None
        return f'好友帮忙: {"、".join(actions_done)}'

    def _run_feature_steal(self) -> str | None:
        """好友偷菜。"""
        action = self._run_help_single_action(BTN_STEAL, ActionType.STEAL, '偷好友果实')
        if action:
            return action
        return None

    def _help_in_friend_farm(self) -> list[str]:
        """在好友农场执行浇水/除草/除虫，完成后尝试回家。"""
        actions_done: list[str] = []

        action = self._run_help_single_action(BTN_WATER, ActionType.WATER, '帮好友浇水')
        if action:
            actions_done.append(action)

        action = self._run_help_single_action(BTN_WEED, ActionType.WEED, '帮好友除草')
        if action:
            actions_done.append(action)

        action = self._run_help_single_action(BTN_BUG, ActionType.BUG, '帮好友除虫')
        if action:
            actions_done.append(action)

        return actions_done

    def _run_help_single_action(self, button, stat_action: str, done_text: str) -> str | None:
        self.ui.device.screenshot()
        if not self.ui.appear(button, offset=30, static=False):
            return None

        confirm_timer = Timer(0.2, count=1)
        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(button, offset=30, interval=1, static=False):
                self.engine._record_stat(stat_action)
                continue
            if not self.ui.appear(button, offset=30, static=False):
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    return done_text
            else:
                confirm_timer.clear()

    def back_to_home(self):
        """返回主页。"""
        while 1:
            self.ui.device.screenshot()

            if self.ui.appear_then_click(BTN_HOME, offset=30, interval=1):
                continue
            if self.ui.appear(MAIN_GOTO_FRIEND, offset=30):
                break

    def wait_list_loading(self):
        """等待好友列表加载。"""
        while 1:
            self.ui.device.screenshot()
            if self.ui.appear(BTN_VISIT_FIRST, offset=30):
                break
