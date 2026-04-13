"""好友求助任务。"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from core.base.button import Button
from core.base.timer import Timer
from core.engine.task.registry import TaskResult
from core.ui.assets import (
    BTN_BUG,
    BTN_CLOSE,
    BTN_FRIEND_AGREED,
    BTN_FRIEND_APPLY,
    BTN_FRIEND_RIGHT_FRAME,
    BTN_HOME,
    BTN_STEAL,
    BTN_VISIT_FIRST,
    BTN_WATER,
    BTN_WEED,
    ICON_BUG_IN_FRIEND_LIST,
    ICON_STEAL_IN_FRIEND_LIST,
    ICON_WATER_IN_FRIEND_LIST,
    ICON_WEED_IN_FRIEND_LIST,
    MAIN_GOTO_FRIEND,
)
from core.ui.page import page_friend_list, page_main
from models.farm_state import ActionType
from tasks.base import TaskBase
from utils.friend_name_ocr import FriendNameOCR
from utils.ocr_utils import OCRTool

# 好友列表中“可操作图标”筛选范围：x 轴有效区间（像素）。
FRIEND_PAGE_ICON_X_RANGE = (105, 410)
# 好友列表中“可操作图标”筛选范围：y 轴有效区间（像素）。
FRIEND_PAGE_ICON_Y_RANGE = (260, 800)
# 正常切换到下一位好友时，在当前选中框中心 x 基础上的偏移量（像素）。
FRIEND_NEXT_OFFSET_X = 70
# 连续识别到“当前好友无可执行动作”达到该次数后，结束本轮好友巡查。
FRIEND_NO_ACTION_EXIT_STREAK = 3
# 好友昵称 OCR 区域：以当前选中好友框中心点 `current_location(x, y)` 为基准。
# x 偏移（像素）：从选中框中心向右偏移后，作为昵称识别框左上角 x。
FRIEND_NAME_OCR_OFFSET_X = 15
# y 偏移（像素）：从选中框中心向上/下偏移后，作为昵称识别框左上角 y（负值表示向上）。
FRIEND_NAME_OCR_OFFSET_Y = 25
# 识别框宽度（像素）。
FRIEND_NAME_OCR_WIDTH = 100
# 识别框高度（像素）。
FRIEND_NAME_OCR_HEIGHT = 25
# 黑名单前缀匹配的最小有效昵称长度（过短通常是 OCR 噪声）。
FRIEND_BLACKLIST_MIN_PREFIX_LEN = 1
# 好友列表“访问”按钮命中黑名单后，向下重试的行高偏移（像素）。
FRIEND_VISIT_SKIP_STEP_Y = 110
# 好友列表“访问”按钮黑名单过滤最多重试次数（包含首次）。
FRIEND_VISIT_SKIP_MAX_TRIES = 6
# 好友列表昵称 OCR 区域（相对访问按钮中心）：x 偏移（像素）。
FRIEND_VISIT_NAME_OCR_OFFSET_X = -310
# 好友列表昵称 OCR 区域（相对访问按钮中心）：y 偏移（像素）。
FRIEND_VISIT_NAME_OCR_OFFSET_Y = -30
# 好友列表昵称 OCR 区域宽度（像素）。
FRIEND_VISIT_NAME_OCR_WIDTH = 150
# 好友列表昵称 OCR 区域高度（像素）。
FRIEND_VISIT_NAME_OCR_HEIGHT = 30
# 好友列表“访问”按钮定向匹配时 ROI 在 x 方向扩展量（像素）。
FRIEND_VISIT_MATCH_MARGIN_X = 10
# 好友列表“访问”按钮定向匹配时 ROI 在 y 方向扩展量（像素）。
FRIEND_VISIT_MATCH_MARGIN_Y = 30


class TaskFriend(TaskBase):
    """封装 `TaskFriend` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui, *, ocr_tool: OCRTool | None = None):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)
        self._friend_blacklist: list[str] = []
        self.friend_name_ocr = FriendNameOCR(ocr_tool=ocr_tool)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行主流程：递进遍历可操作好友，直到没有可继续目标。"""
        _ = rect
        features = self.get_features('friend')
        enable_steal = self.has_feature(features, 'auto_steal')
        enable_help = self.has_feature(features, 'auto_help')
        enable_accept_request = self.has_feature(features, 'auto_accept_request', default=True)
        self._friend_blacklist = self._read_blacklist(features)
        logger.info('好友巡查: 开始 | 偷菜={} 帮忙={} 同意请求={}', enable_steal, enable_help, enable_accept_request)
        if self._friend_blacklist:
            logger.info('好友巡查: 黑名单已加载 | 数量={}', len(self._friend_blacklist))
        if not enable_steal and not enable_help:
            logger.info('好友巡查: 未启用任何功能，结束')
            return self.ok()

        # 进入好友列表页
        self.ui.ui_ensure(page_friend_list)
        # 处理微信好友请求
        if enable_accept_request:
            self.accept_friend()
        # 等待列表加载
        self.wait_list_loading()

        self._run_friend_progressive(enable_help=enable_help, enable_steal=enable_steal)
        # 返回主页
        self.back_to_home()
        logger.info('好友巡查: 结束')

        return self.ok()

    def _run_friend_progressive(self, *, enable_help: bool, enable_steal: bool):
        """好友任务递进流程：进入详情后执行动作，再切到下一个可操作好友。"""
        if not self._enter_friend_detail():
            return

        self._run_friend_recursive(enable_help=enable_help, enable_steal=enable_steal, no_action=0)

    def _run_friend_recursive(self, *, enable_help: bool, enable_steal: bool, no_action: int):
        """递归处理好友：连续命中无操作按钮达到阈值后退出。"""
        has_action = self._has_current_friend_actions(enable_help=enable_help, enable_steal=enable_steal)
        if not has_action:
            no_action += 1
            logger.info('好友巡查: 当前好友无可执行动作，连续空轮询={}/{}', no_action, FRIEND_NO_ACTION_EXIT_STREAK)
            if no_action >= FRIEND_NO_ACTION_EXIT_STREAK:
                logger.info('好友巡查: 连续无动作达到阈值，结束好友任务')
                return
        else:
            no_action = 0
            if enable_steal:
                self._run_feature_steal()
            if enable_help:
                self._run_feature_help()

        if not self._goto_next_friend():
            logger.info('好友巡查: 切换下一位好友失败，结束好友任务')
            return

        self._run_friend_recursive(enable_help=enable_help, enable_steal=enable_steal, no_action=no_action)

    def _has_current_friend_actions(self, *, enable_help: bool, enable_steal: bool) -> bool:
        """判断当前好友界面是否有可执行操作按钮（使用 BTN 模板）。"""
        self.ui.device.screenshot()
        buttons: list[Button] = []
        if enable_steal:
            buttons.append(BTN_STEAL)
        if enable_help:
            buttons.extend([BTN_WATER, BTN_WEED, BTN_BUG])
        if not buttons:
            return False
        return bool(self.ui.appear_any(buttons, offset=30, static=False))

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
        logger.info('好友巡查: 列表可操作目标 | 偷菜={} 帮忙={}', len(list_steal), len(list_help))

        # 进入详情页
        if list_steal or list_help:
            attempt = 0
            while 1:
                self.ui.device.screenshot()
                if self.ui.appear(BTN_HOME, offset=30):
                    logger.info('好友巡查: 已进入好友详情页')
                    return True

                if self._friend_blacklist:
                    should_continue, attempt = self._try_click_visit_with_blacklist(attempt=attempt)
                else:
                    should_continue = self._try_click_visit_without_blacklist()
                if should_continue:
                    continue
                break

        logger.info('好友巡查: 未进入好友详情页，结束本轮')
        return False

    def _try_click_visit_without_blacklist(self) -> bool:
        """无黑名单时，按默认访问按钮进入好友详情。"""
        self.ui.appear_then_click(BTN_VISIT_FIRST, offset=30, interval=1)
        return True

    def _try_click_visit_with_blacklist(self, *, attempt: int) -> tuple[bool, int]:
        """有黑名单时，按行偏移识别昵称并决定是否进入。"""
        if attempt >= FRIEND_VISIT_SKIP_MAX_TRIES:
            logger.info('好友巡查: 黑名单过滤重试超过{}次，停止进入详情', FRIEND_VISIT_SKIP_MAX_TRIES)
            return False, attempt

        step_y = attempt * FRIEND_VISIT_SKIP_STEP_Y
        visit_location = self._find_visit_button_with_step_y(step_y=step_y)
        if visit_location is None:
            logger.info('好友巡查: 未找到可进入的好友目标')
            return False, attempt

        visit_x, visit_y = visit_location
        detected_name = self._detect_friend_name_near_visit_button(visit_x=visit_x, visit_y=visit_y)
        hit_blacklist = self._is_blacklisted_friend_name(detected_name)
        if hit_blacklist:
            logger.info(
                '好友巡查: 列表命中黑名单 | 昵称={} | 重试进度={}/{}',
                detected_name,
                attempt + 1,
                FRIEND_VISIT_SKIP_MAX_TRIES,
            )
            return True, attempt + 1

        if self.ui.device.click_point(visit_x, visit_y, desc='访问好友'):
            logger.info('好友巡查: 点击访问好友 | 昵称={} 行偏移={}', detected_name or '<empty>', step_y)
            return True, attempt

        logger.info('好友巡查: 点击访问好友失败 | 昵称={} 行偏移={}', detected_name or '<empty>', step_y)
        return False, attempt

    def _find_visit_button_with_step_y(self, *, step_y: int) -> tuple[int, int] | None:
        """在指定纵向偏移区域内查找访问按钮。"""
        offset = (
            int(-FRIEND_VISIT_MATCH_MARGIN_X),
            int(step_y - FRIEND_VISIT_MATCH_MARGIN_Y),
            int(FRIEND_VISIT_MATCH_MARGIN_X),
            int(step_y + FRIEND_VISIT_MATCH_MARGIN_Y),
        )
        return self.ui.appear_location(BTN_VISIT_FIRST, offset=offset, threshold=0.8, static=True)

    def _detect_friend_name_near_visit_button(self, *, visit_x: int, visit_y: int) -> str:
        """在好友列表中，根据访问按钮位置识别同一行昵称。"""
        image = self.ui.device.image
        if image is None:
            return ''

        h, w = image.shape[:2]
        x1 = int(visit_x + FRIEND_VISIT_NAME_OCR_OFFSET_X)
        y1 = int(visit_y + FRIEND_VISIT_NAME_OCR_OFFSET_Y)
        x2 = int(x1 + FRIEND_VISIT_NAME_OCR_WIDTH)
        y2 = int(y1 + FRIEND_VISIT_NAME_OCR_HEIGHT)

        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        if x2 <= x1 or y2 <= y1:
            return ''

        text, _score = self.friend_name_ocr.detect_name(
            image,
            region=(x1, y1, x2, y2),
        )
        name = str(text or '').strip()
        logger.debug('好友巡查: 列表昵称识别 | region=({}, {}, {}, {}) text={}', x1, y1, x2, y2, name or '<empty>')
        return name

    def _goto_next_friend(self) -> bool:
        """点击下一个好友：使用当前选中框模板位置 `x+50` 跳转。"""
        self.ui.device.stuck_record_clear()
        self.ui.device.click_record_clear()

        self.ui.device.screenshot()
        current_location = self.ui.appear_location(BTN_FRIEND_RIGHT_FRAME, offset=30, threshold=0.83, static=False)
        if not current_location:
            logger.info('好友巡查: 未识别到当前选中好友框')
            return False

        current_x, current_y = current_location
        detected_name = self._detect_friend_name_in_selected_row(current_x=current_x, current_y=current_y)
        step_offset = FRIEND_NEXT_OFFSET_X
        if self._friend_blacklist:
            hit_blacklist = self._is_blacklisted_friend_name(detected_name)
            if hit_blacklist:
                step_offset = FRIEND_NEXT_OFFSET_X * 2 + 20
                logger.info('好友巡查: 命中黑名单 | 昵称={} | 跳过好友', detected_name)

        next_x = int(current_x + step_offset)
        next_y = int(current_y)
        if self.ui.device.click_point(next_x, next_y, desc='切换下一位好友'):
            logger.info(
                '好友巡查: 切换下一位好友 | 昵称={} 偏移={}',
                detected_name or '<empty>',
                step_offset,
            )
            self.ui.device.sleep(0.2)
            return True

        logger.info('好友巡查: 点击下一位好友失败')
        return False

    @staticmethod
    def _normalize_friend_name(value: str) -> str:
        """规范化昵称文本，减少 OCR 噪声影响。"""
        text = str(value or '').strip()
        if not text:
            return ''
        # 仅保留中英文和数字，过滤标点/符号/空白。
        text = re.sub(r'[\W_]+', '', text, flags=re.UNICODE)
        return text.lower()

    @staticmethod
    def _read_blacklist(features: dict[str, Any]) -> list[str]:
        """从任务 feature 中读取黑名单并去重。"""
        if not isinstance(features, dict):
            return []
        raw = features.get('blacklist', [])
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            name = str(item or '').strip()
            if not name:
                continue
            key = TaskFriend._normalize_friend_name(name)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(name)
        return out

    def _detect_friend_name_in_selected_row(self, *, current_x: int, current_y: int) -> str:
        """在选中好友附近区域识别昵称。"""
        image = self.ui.device.image
        if image is None:
            return ''

        h, w = image.shape[:2]
        x1 = int(current_x + FRIEND_NAME_OCR_OFFSET_X)
        y1 = int(current_y + FRIEND_NAME_OCR_OFFSET_Y)
        x2 = int(x1 + FRIEND_NAME_OCR_WIDTH)
        y2 = int(y1 + FRIEND_NAME_OCR_HEIGHT)

        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        if x2 <= x1 or y2 <= y1:
            return ''

        text, _score = self.friend_name_ocr.detect_name(
            image,
            region=(x1, y1, x2, y2),
        )
        name = str(text or '').strip()
        logger.debug('好友巡查: 好友昵称识别 | region=({}, {}, {}, {}) text={}', x1, y1, x2, y2, name or '<empty>')
        return name

    def _is_blacklisted_friend_name(self, detected_name: str) -> bool:
        """按前缀规则匹配黑名单：黑名单项以识别昵称开头即命中。"""
        raw_name = str(detected_name or '').strip()
        if not raw_name:
            return False

        prefix = self._normalize_friend_name(raw_name)
        if not prefix:
            return False
        if len(prefix) < FRIEND_BLACKLIST_MIN_PREFIX_LEN:
            return False

        for item in self._friend_blacklist:
            candidate = self._normalize_friend_name(item)
            if prefix.startswith(candidate):
                return True
        return False

    def _collect_operable_friend_list_icons(
        self, *, enable_help: bool = False, enable_steal: bool = False
    ) -> list[Button]:
        """收集好友列表页（纵向）上的可操作 icon（list 模板）。"""
        icons: list[Button] = []
        if enable_steal:
            icons.extend(self.ui.match_icon_multi(ICON_STEAL_IN_FRIEND_LIST, threshold=0.85))
        if enable_help:
            icons.extend(self.ui.match_icon_multi(ICON_WATER_IN_FRIEND_LIST, threshold=0.85))
            icons.extend(self.ui.match_icon_multi(ICON_WEED_IN_FRIEND_LIST, threshold=0.85))
            icons.extend(self.ui.match_icon_multi(ICON_BUG_IN_FRIEND_LIST, threshold=0.85))

        if not icons:
            return []
        icons = self.ui.filter_buttons_in_area(
            icons, x_range=FRIEND_PAGE_ICON_X_RANGE, y_range=FRIEND_PAGE_ICON_Y_RANGE
        )
        # 好友列表页按纵向优先（y -> x）排序，优先从上往下处理。
        icons = self.ui.sort_buttons_by_location(icons, horizontal=False)
        return icons

    def _run_feature_help(self):
        """好友帮忙。"""
        self._help_in_friend_farm()

    def _run_feature_steal(self):
        """好友偷菜。"""
        self._run_help_single_action(BTN_STEAL, ActionType.STEAL, '偷好友果实')

    def _help_in_friend_farm(self):
        """在好友农场执行浇水/除草/除虫，完成后尝试回家。"""
        self._run_help_single_action(BTN_WATER, ActionType.WATER, '帮好友浇水')
        self._run_help_single_action(BTN_WEED, ActionType.WEED, '帮好友除草')
        self._run_help_single_action(BTN_BUG, ActionType.BUG, '帮好友除虫')

    def _run_help_single_action(self, button, stat_action: str, done_text: str) -> bool:
        self.ui.device.screenshot()
        if not self.ui.appear(button, offset=30, static=False):
            return False

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
                    logger.info('好友巡查: 完成动作 | {}', done_text)
                    return True
            else:
                confirm_timer.clear()

    def back_to_home(self):
        """返回主页。"""
        self.ui.ui_ensure(page_main)

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

    def accept_friend(self):
        """处理微信好友请求。"""
        while 1:
            self.ui.device.screenshot()
            if not self.ui.appear(BTN_FRIEND_APPLY, offset=30):
                break
            if self.ui.appear(BTN_FRIEND_APPLY, offset=30) and self.ui.appear_then_click(
                BTN_FRIEND_AGREED, offset=30, interval=1
            ):
                continue
            if self.ui.appear(BTN_FRIEND_APPLY, offset=30) and self.ui.appear_then_click(
                BTN_CLOSE, offset=30, interval=1
            ):
                continue
