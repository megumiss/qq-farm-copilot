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
    BTN_STEAL_TOTAL,
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
from utils.ocr_utils import OCRItem, OCRTool
from utils.steal_stats import record_steal

# 好友列表中“可操作图标”筛选范围：x 轴有效区间（像素）。
FRIEND_PAGE_ICON_X_RANGE = (105, 410)
# 好友列表中“可操作图标”筛选范围：y 轴有效区间（像素）。
FRIEND_PAGE_ICON_Y_RANGE = (260, 800)
# 正常切换到下一位好友时，在当前选中框中心 x 基础上的偏移量（像素）。
FRIEND_NEXT_OFFSET_X = 70
# 连续识别到“当前好友无可执行动作”达到该次数后，结束本轮好友巡查。
FRIEND_NO_ACTION_EXIT_STREAK = 3
# 好友详情页“下一位好友昵称”识别：固定在底部带内取样高度（像素）。
FRIEND_NEXT_NAME_BOTTOM_BAND_HEIGHT = 75
# 好友详情页“下一位好友昵称”识别：以选中框按钮中心为起点，向右识别宽度（像素）。
FRIEND_NEXT_NAME_RIGHT_WIDTH = 130
# 黑名单前缀匹配的最小有效昵称长度（过短通常是 OCR 噪声）。
FRIEND_BLACKLIST_MIN_PREFIX_LEN = 1
# 好友列表“访问”按钮命中黑名单后，向下重试的行高偏移（像素）。
FRIEND_VISIT_SKIP_STEP_Y = 110
# 好友列表“访问”按钮黑名单过滤最多重试次数（包含首次）。
FRIEND_VISIT_SKIP_MAX_TRIES = 6
# 好友列表昵称 OCR 区域（相对访问按钮中心）：x 偏移（像素）。
FRIEND_VISIT_NAME_OCR_X1 = 150
# 好友列表昵称 OCR 固定区域（像素）：右边界 x。
FRIEND_VISIT_NAME_OCR_X2 = 400
# 好友列表昵称 OCR 固定区域（像素）：上边界 y。
FRIEND_VISIT_NAME_OCR_Y1 = 265
# 好友列表昵称 OCR 固定区域（像素）：下边界 y。
FRIEND_VISIT_NAME_OCR_Y2 = 780
# 好友列表昵称 OCR 候选筛选：访问按钮中心点上方 y 方向窗口（像素）。
FRIEND_VISIT_NAME_ABOVE_Y_WINDOW = 40
# 好友列表“访问”按钮定向匹配时 ROI 在 x 方向扩展量（像素）。
FRIEND_VISIT_MATCH_MARGIN_X = 10
# 好友列表“访问”按钮定向匹配时 ROI 在 y 方向扩展量（像素）。
FRIEND_VISIT_MATCH_MARGIN_Y = 30
# 偷取统计：等待“总计按钮”出现的超时时间（秒）。
STEAL_TOTAL_WAIT_TIMEOUT_SECONDS = 10.0
# 偷取统计：识别按钮出现后的稳定等待（秒）。
STEAL_TOTAL_STABLE_WAIT_SECONDS = 1.0
# 偷取统计：OCR 轮询间隔（秒）。
STEAL_TOTAL_OCR_POLL_INTERVAL_SECONDS = 0.2
# 偷取统计 OCR 固定区域（x1, y1, x2, y2），按当前统一截图坐标系定义。
STEAL_TOTAL_OCR_REGION = (420, 240, 530, 390)
# 偷取统计金额 token 正则：支持纯数字/小数/万单位，允许前导负号。
STEAL_AMOUNT_TOKEN_PATTERN = re.compile(r'-?\d+(?:\.\d+)?(?:万)?')


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
        enable_steal_stats = self.has_feature(features, 'steal_stats', default=False)
        self._friend_blacklist = self._read_blacklist(features)
        logger.info(
            '好友巡查: 开始 | 偷菜={} 帮忙={} 同意请求={} 偷取统计={}',
            enable_steal,
            enable_help,
            enable_accept_request,
            enable_steal_stats,
        )
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

        self._run_friend_progressive(
            enable_help=enable_help,
            enable_steal=enable_steal,
            enable_steal_stats=enable_steal_stats,
        )
        # 返回主页
        self.back_to_home()
        logger.info('好友巡查: 结束')

        return self.ok()

    def _run_friend_progressive(self, *, enable_help: bool, enable_steal: bool, enable_steal_stats: bool):
        """好友任务递进流程：进入详情后执行动作，再切到下一个可操作好友。"""
        if not self._enter_friend_detail():
            return

        self._run_friend_recursive(
            enable_help=enable_help,
            enable_steal=enable_steal,
            enable_steal_stats=enable_steal_stats,
            no_action=0,
        )

    def _run_friend_recursive(self, *, enable_help: bool, enable_steal: bool, enable_steal_stats: bool, no_action: int):
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
                self._run_feature_steal(enable_steal_stats=enable_steal_stats)
            if enable_help:
                self._run_feature_help()

        if not self._goto_next_friend():
            logger.info('好友巡查: 切换下一位好友失败，结束好友任务')
            return

        self._run_friend_recursive(
            enable_help=enable_help,
            enable_steal=enable_steal,
            enable_steal_stats=enable_steal_stats,
            no_action=no_action,
        )

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

        _ = visit_x
        h, w = image.shape[:2]
        x1 = int(FRIEND_VISIT_NAME_OCR_X1)
        y1 = int(FRIEND_VISIT_NAME_OCR_Y1)
        x2 = int(FRIEND_VISIT_NAME_OCR_X2)
        y2 = int(FRIEND_VISIT_NAME_OCR_Y2)

        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        if x2 <= x1 or y2 <= y1:
            return ''

        items = self.friend_name_ocr.detect_items(
            image,
            region=(x1, y1, x2, y2),
        )
        y_low = float(visit_y - FRIEND_VISIT_NAME_ABOVE_Y_WINDOW)
        y_high = float(visit_y)
        candidates: list[tuple[float, str]] = []
        for item in items:
            text = str(item.text or '').strip()
            if not text:
                continue
            ys = [point[1] for point in item.box]
            xs = [point[0] for point in item.box]
            center_y = float(min(ys) + max(ys)) / 2.0
            if not (y_low <= center_y <= y_high):
                continue
            min_x = float(min(xs))
            candidates.append((min_x, text))

        candidates.sort(key=lambda item: item[0])
        tokens = [item[1] for item in candidates]
        name = ''.join(tokens).strip()
        logger.debug(
            '好友巡查: 列表昵称识别 | region=({}, {}, {}, {}) pick_y_range=({:.1f}, {:.1f}) tokens={} text={}',
            x1,
            y1,
            x2,
            y2,
            y_low,
            y_high,
            tokens,
            name or '<empty>',
        )
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
        detected_name = ''
        step_offset = FRIEND_NEXT_OFFSET_X
        if self._friend_blacklist:
            detected_name = self._detect_friend_name_in_selected_row(current_x=current_x, current_y=current_y)
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
        """识别“下一位好友”昵称：先识别底部 75px，再筛选右侧 130px 内内容。"""
        image = self.ui.device.image
        if image is None:
            return ''

        h, w = image.shape[:2]
        _ = current_y
        y1 = int(h - FRIEND_NEXT_NAME_BOTTOM_BAND_HEIGHT)
        detect_x1 = 0
        detect_x2 = int(w)
        y2 = int(h)

        x1 = int(current_x)
        x2 = int(x1 + FRIEND_NEXT_NAME_RIGHT_WIDTH)
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        if x2 <= x1 or y2 <= y1:
            return ''

        items = self.friend_name_ocr.detect_items(
            image,
            region=(detect_x1, y1, detect_x2, y2),
        )
        ranged_items = []
        for item in items:
            text = str(item.text or '').strip()
            if not text:
                continue
            min_x = min(point[0] for point in item.box)
            max_x = max(point[0] for point in item.box)
            if not (x1 <= min_x and max_x <= x2):
                continue
            ranged_items.append(item)

        ranged_items.sort(key=lambda item: min(point[0] for point in item.box))
        tokens = [str(item.text or '').strip() for item in ranged_items if str(item.text or '').strip()]

        name = ''.join(tokens).strip()
        logger.debug(
            '好友巡查: 好友昵称识别 | detect_region=({}, {}, {}, {}) pick_x_range=({}, {}) tokens={} text={}',
            detect_x1,
            y1,
            detect_x2,
            y2,
            x1,
            x2,
            tokens,
            name or '<empty>',
        )
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

    def _run_feature_steal(self, *, enable_steal_stats: bool):
        """好友偷菜。"""
        if self._run_help_single_action(BTN_STEAL, ActionType.STEAL, '偷好友果实'):
            if enable_steal_stats:
                self._ocr_and_record_steal()

    def _ocr_and_record_steal(self):
        """偷取成功后等待总计按钮，基于 OCR 源数据解析并写入统计。"""
        try:
            if not self._wait_steal_total_button():
                logger.info('好友偷取统计: 等待超时，跳过本次统计')
                return

            self.ui.device.sleep(STEAL_TOTAL_STABLE_WAIT_SECONDS)
            total_amount, loss_amount, bean_amount, score, debug_info = self._wait_stable_steal_ocr_result()
            coin_amount = max(0, total_amount - loss_amount)

            if coin_amount > 0 or bean_amount > 0:
                logger.info(
                    '好友偷取统计: 总价值={} 被咬损失={} 金币={} 金豆={}',
                    total_amount,
                    loss_amount,
                    coin_amount,
                    bean_amount,
                )
                logger.debug('好友偷取统计 OCR 明细: score={:.2f} {}', score, debug_info)
                record_steal(self._resolve_instance_id(), coin_amount, bean_amount)
                return
            logger.info('好友偷取统计: 未解析到有效偷取结果，跳过记录')
            logger.debug('好友偷取统计 OCR 明细: score={:.2f} {}', score, debug_info)
        except Exception as e:
            logger.warning('好友偷取统计 OCR 失败: {}', e)

    def _wait_stable_steal_ocr_result(self) -> tuple[int, int, int, float, str]:
        """轮询 OCR，直到连续两次解析结果一致。"""
        last_value: tuple[int, int, int] | None = None
        while 1:
            self.ui.device.screenshot()
            items = self.friend_name_ocr.ocr.detect(
                self.ui.device.image, region=STEAL_TOTAL_OCR_REGION, scale=1.3, alpha=1.12, beta=0.0
            )
            total_amount, loss_amount, bean_amount, debug_info = self._parse_steal_total_and_loss_from_items(items)
            score = float(sum(float(item.score) for item in items) / len(items)) if items else 0.0
            current_value = (total_amount, loss_amount, bean_amount)
            if last_value is not None and current_value == last_value:
                return total_amount, loss_amount, bean_amount, score, debug_info
            last_value = current_value
            self.ui.device.sleep(STEAL_TOTAL_OCR_POLL_INTERVAL_SECONDS)

    def _wait_steal_total_button(self) -> bool:
        timer = Timer(STEAL_TOTAL_WAIT_TIMEOUT_SECONDS, count=0).start()
        while 1:
            self.ui.device.screenshot()
            if self.ui.appear(BTN_STEAL_TOTAL, offset=(20, 20)):
                return True
            if timer.reached():
                return False
            self.ui.device.sleep(STEAL_TOTAL_OCR_POLL_INTERVAL_SECONDS)

    def _resolve_instance_id(self) -> str:
        for name in ('_instance_id', 'instance_id'):
            value = getattr(self.engine, name, None)
            text = str(value or '').strip()
            if text:
                return text
        return 'default'

    @staticmethod
    def _parse_amount_token(token: str) -> int:
        text = str(token or '').strip()
        if not text:
            return 0
        sign = -1 if text.startswith('-') else 1
        unsigned = text.lstrip('+-')
        multiplier = 10000 if unsigned.endswith('万') else 1
        numeric = unsigned[:-1] if unsigned.endswith('万') else unsigned
        try:
            value = float(numeric)
        except Exception:
            return 0
        return int(round(sign * value * multiplier))

    @staticmethod
    def _ocr_item_bounds(item: OCRItem) -> tuple[float, float, float, float]:
        xs = [float(point[0]) for point in item.box]
        ys = [float(point[1]) for point in item.box]
        return min(xs), min(ys), max(xs), max(ys)

    @classmethod
    def _parse_steal_total_and_loss_from_items(
        cls,
        items: list[OCRItem],
    ) -> tuple[int, int, int, str]:
        normalized: list[dict[str, float | str]] = []
        for item in items:
            text = str(item.text or '').replace(' ', '').strip()
            if not text:
                continue
            x1, y1, x2, y2 = cls._ocr_item_bounds(item)
            normalized.append(
                {
                    'text': text,
                    'x1': x1,
                    'y1': y1,
                    'x2': x2,
                    'y2': y2,
                    'score': float(item.score),
                }
            )

        normalized.sort(key=lambda x: (float(x['y1']), float(x['x1'])))
        total_label_x: float | None = None
        total_label_y: float | None = None
        loss_label_x: float | None = None
        loss_label_y: float | None = None
        for item in normalized:
            text = str(item['text'])
            if total_label_x is None and '总价值' in text:
                total_label_x = float(item['x1'])
                total_label_y = float(item['y1'])
            if loss_label_x is None and '被咬损失' in text:
                loss_label_x = float(item['x1'])
                loss_label_y = float(item['y1'])

        amount_tokens: list[dict[str, float | str]] = []
        for item in normalized:
            text = str(item['text'])
            for match in STEAL_AMOUNT_TOKEN_PATTERN.finditer(text):
                amount_tokens.append(
                    {
                        'token': str(match.group(0)),
                        'x1': float(item['x1']),
                        'y1': float(item['y1']),
                    }
                )
        amount_tokens.sort(key=lambda x: (float(x['y1']), float(x['x1'])))

        total_pick: dict[str, float | str] | None = None
        loss_pick: dict[str, float | str] | None = None
        bean_pick: dict[str, float | str] | None = None
        if total_label_x is not None:
            candidates = [t for t in amount_tokens if float(t['x1']) >= total_label_x]
            if total_label_y is not None:
                candidates = [t for t in candidates if float(t['y1']) >= total_label_y]
            if loss_label_y is not None:
                candidates = [t for t in candidates if float(t['y1']) < loss_label_y]
            if loss_label_x is not None:
                total_candidates = [t for t in candidates if float(t['x1']) < loss_label_x]
                if total_candidates:
                    total_pick = total_candidates[0]
                elif candidates:
                    total_pick = candidates[0]
            elif candidates:
                total_pick = candidates[0]

        if loss_label_x is not None:
            loss_candidates = [t for t in amount_tokens if float(t['x1']) >= loss_label_x]
            if loss_label_y is not None:
                loss_candidates = [t for t in loss_candidates if float(t['y1']) >= loss_label_y]
            neg_in_loss = [t for t in loss_candidates if str(t['token']).startswith('-')]
            if neg_in_loss:
                loss_pick = neg_in_loss[0]

        if total_pick is None and amount_tokens:
            total_pick = amount_tokens[0]
        if loss_pick is None:
            neg_tokens = [t for t in amount_tokens if str(t['token']).startswith('-')]
            if neg_tokens and (total_pick is None or neg_tokens[0] is not total_pick):
                loss_pick = neg_tokens[0]

        total_token = str(total_pick['token']) if total_pick is not None else ''
        loss_token = str(loss_pick['token']) if loss_pick is not None else ''

        remaining = [t for t in amount_tokens if t is not total_pick and t is not loss_pick]
        if total_pick is not None:
            y_lower = float(total_pick['y1'])
            y_upper = float(loss_pick['y1']) if loss_pick is not None else float('inf')
            below_total = [
                t
                for t in remaining
                if float(t['y1']) > y_lower
                and float(t['y1']) < y_upper
                and not str(t['token']).startswith('-')
                and '万' not in str(t['token'])
            ]
            below_total.sort(key=lambda x: (float(x['y1']), abs(float(x['x1']) - float(total_pick['x1']))))
            if below_total:
                bean_pick = below_total[0]

        if bean_pick is None:
            fallback = [t for t in remaining if not str(t['token']).startswith('-') and '万' not in str(t['token'])]
            fallback.sort(key=lambda x: (float(x['y1']), float(x['x1'])))
            if fallback:
                bean_pick = fallback[0]

        bean_token = str(bean_pick['token']) if bean_pick is not None else ''
        total_amount = max(0, cls._parse_amount_token(total_token))
        loss_amount = abs(cls._parse_amount_token(loss_token))
        bean_amount = max(0, abs(cls._parse_amount_token(bean_token)))
        item_texts = [str(item['text']) for item in normalized]
        token_texts = [str(item['token']) for item in amount_tokens]
        debug_info = (
            f'items={item_texts} tokens={token_texts} '
            f'pick_total={total_token} pick_loss={loss_token} pick_bean={bean_token}'
        )
        return total_amount, loss_amount, bean_amount, debug_info

    def _help_in_friend_farm(self):
        """在好友农场执行浇水/除草/除虫，完成后尝试回家。"""
        self._run_help_maintain_actions()

    def _run_help_maintain_actions(self) -> bool:
        """统一执行帮好友浇水/除草/除虫，共用确认计时器。"""
        action_specs = [
            (BTN_WATER, ActionType.WATER),
            (BTN_WEED, ActionType.WEED),
            (BTN_BUG, ActionType.BUG),
        ]
        action_buttons = [button for button, _ in action_specs]

        self.ui.device.screenshot()
        if not self.ui.appear_any(action_buttons, offset=30, static=False):
            return False

        confirm_timer = Timer(0.5, count=2)
        while 1:
            self.ui.device.screenshot()

            clicked_action: str | None = None
            for button, stat_action in action_specs:
                if self.ui.appear(button, offset=30, static=False):
                    clicked_action = stat_action
                    break
            if self.ui.appear_then_click_any(action_buttons, offset=30, interval=1, static=False):
                if clicked_action is not None:
                    self.engine._record_stat(clicked_action)
                confirm_timer.clear()
                continue

            if not self.ui.appear_any(action_buttons, offset=30, static=False):
                if not confirm_timer.started():
                    confirm_timer.start()
                if confirm_timer.reached():
                    logger.info('好友巡查: 完成动作 | 帮好友维护')
                    return True
            else:
                confirm_timer.clear()

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
