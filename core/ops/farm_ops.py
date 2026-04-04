"""nklite 业务操作集合（替代 legacy strategies）。"""

from __future__ import annotations

import time

import pyautogui
from loguru import logger

from core.vision.cv_detector import DetectResult
from models.farm_state import Action, ActionType
from utils.shop_item_ocr import ShopItemOCR


class _OpsBase:
    """业务操作基类：封装截图、点击与检测结果查询等通用能力。"""
    def __init__(self, engine):
        """保存引擎引用，并初始化动作节流状态。"""
        self.engine = engine
        self._action_cooldown_seconds = 0.45
        self._action_next_allowed: dict[str, float] = {}

    @property
    def stopped(self) -> bool:
        """返回当前会话是否已请求停止。"""
        return self.engine._is_cancel_requested()

    def sleep(self, seconds: float) -> bool:
        """可中断休眠：停止请求到来时会提前返回 `False`。"""
        return self.engine._sleep_interruptible(seconds)

    def capture(
        self,
        rect: tuple[int, int, int, int],
        *,
        template_names: list[str] | None = None,
        thresholds: dict[str, float] | None = None,
        template_rois: dict[str, tuple[int, int, int, int]] | None = None,
    ):
        """执行截图流程并返回图像结果。"""
        return self.engine._capture_and_detect(
            rect,
            save=False,
            template_names=template_names,
            template_thresholds=thresholds,
            template_rois=template_rois,
        )

    def click(self, x: int, y: int, desc: str = '', action_type: str = ActionType.NAVIGATE) -> bool:
        """执行点击动作并返回是否成功。"""
        if not self.engine.action_executor or self.stopped:
            return False

        # 将客户区坐标统一映射到当前截图坐标系，避免边框偏移导致点偏。
        rel_x, rel_y = int(x), int(y)
        resolver = getattr(self.engine, 'resolve_live_click_point', None)
        if callable(resolver):
            rel_x, rel_y = resolver(rel_x, rel_y)

        # 基于动作类型+描述做轻量节流，抑制高频重复点击。
        key = f'{action_type}:{desc}'
        now = time.perf_counter()
        allow_at = self._action_next_allowed.get(key, 0.0)
        if now < allow_at:
            logger.debug(f'动作冷却中，跳过点击: {desc} ({allow_at - now:.2f}s)')
            return False

        action = Action(
            type=action_type,
            click_position={'x': int(rel_x), 'y': int(rel_y)},
            priority=0,
            description=str(desc),
        )
        result = self.engine.action_executor.execute_action(action)
        if result.success:
            self._action_next_allowed[key] = now + max(0.0, self._action_cooldown_seconds)
            return True
        return False

    @staticmethod
    def find_by_name(detections: list[DetectResult], name: str) -> DetectResult | None:
        """在检测结果中查找指定模板名的第一项。"""
        for d in detections:
            if d.name == name:
                return d
        return None

    @staticmethod
    def find_any(detections: list[DetectResult], names: list[str]) -> DetectResult | None:
        """在检测结果中查找多个模板名中的第一项。"""
        wanted = set(names)
        for d in detections:
            if d.name in wanted:
                return d
        return None

    def click_blank(self, rect: tuple[int, int, int, int]):
        """执行点击动作并返回是否成功。"""
        _ = rect
        self.click(270, 20, '点击回主按钮')


class PopupOps(_OpsBase):
    """封装 `PopupOps` 相关业务操作流程。"""
    def _share_and_cancel(self, share_btn: DetectResult) -> str:
        """点击分享领奖后用 `Esc` 取消分享面板，回到游戏页面。"""
        if self.stopped:
            return '取消领取双倍任务奖励(停止中)'

        self.click(share_btn.x, share_btn.y, '点击分享(双倍奖励)', ActionType.CLOSE_POPUP)
        if not self.sleep(2.0):
            return '取消领取双倍任务奖励(停止中)'

        if self.stopped:
            return '取消领取双倍任务奖励(停止中)'
        pyautogui.press('escape')
        if not self.sleep(1.0):
            return '取消领取双倍任务奖励(停止中)'
        return '领取双倍任务奖励'


class ExpandOps(_OpsBase):
    """封装 `ExpandOps` 相关业务操作流程。"""
    def __init__(self, engine):
        """初始化扩建流程状态。"""
        super().__init__(engine)
        self._expand_failed = False

    def try_expand(self, rect: tuple[int, int, int, int], detections: list[DetectResult]) -> str | None:
        """尝试执行一次扩建流程；失败后会进入短路状态避免反复触发。"""
        if self._expand_failed:
            return None

        btn = self.find_by_name(detections, 'btn_expand')
        if not btn:
            return None

        self.click(btn.x, btn.y + 10, '点击可扩建')
        self.sleep(0.5)

        for _ in range(5):
            if self.stopped:
                return None
            cv_img, dets, _ = self.capture(
                rect,
                template_names=[
                    'btn_expand_direct_confirm',
                    'btn_expand_confirm',
                    'btn_close',
                    'btn_confirm',
                    'btn_claim',
                ],
            )
            if cv_img is None:
                return None

            direct_confirm = self.find_by_name(dets, 'btn_expand_direct_confirm')
            normal_confirm = self.find_by_name(dets, 'btn_expand_confirm')
            confirm = direct_confirm or normal_confirm
            if confirm:
                action_name = '直接扩建' if direct_confirm else '扩建确认'
                self.click(confirm.x, confirm.y, action_name)
                self.sleep(0.5)
                self._expand_failed = False

                cv_img2, dets2, _ = self.capture(
                    rect,
                    template_names=['btn_close', 'btn_confirm', 'btn_claim'],
                )
                if cv_img2 is not None:
                    close = self.find_any(dets2, ['btn_close', 'btn_confirm', 'btn_claim'])
                    if close:
                        self.click(close.x, close.y, '关闭扩建弹窗', ActionType.CLOSE_POPUP)
                return action_name

            close = self.find_any(dets, ['btn_close', 'btn_confirm', 'btn_claim'])
            if close:
                self.click(close.x, close.y, '关闭弹窗', ActionType.CLOSE_POPUP)
                self.sleep(0.2)
                continue
            self.sleep(0.3)

        self._expand_failed = True
        logger.info('扩建条件不满足，暂停扩建检测')
        return None


class TaskOps(_OpsBase):
    """封装 `TaskOps` 相关业务操作流程。"""
    def __init__(self, engine, popup: PopupOps):
        """初始化任务奖励处理器并注入弹窗操作对象。"""
        super().__init__(engine)
        self._popup = popup

    def _handle_task_result(self, rect: tuple[int, int, int, int]) -> list[str]:
        """处理任务完成弹窗：优先双倍分享，其次普通领取。"""
        actions: list[str] = []
        for _ in range(5):
            if self.stopped:
                return actions

            cv_img, dets, _ = self.capture(
                rect,
                template_names=['btn_share', 'btn_claim', 'btn_confirm', 'btn_close'],
            )
            if cv_img is None:
                return actions

            share = self.find_by_name(dets, 'btn_share')
            if share:
                self._popup._share_and_cancel(share)
                actions.append('领取双倍任务奖励')
                self.sleep(0.5)
                return actions

            claim = self.find_by_name(dets, 'btn_claim')
            if claim:
                self.click(claim.x, claim.y, '直接领取', ActionType.CLOSE_POPUP)
                actions.append('领取任务奖励')
                self.sleep(0.3)
                return actions

            close = self.find_any(dets, ['btn_close', 'btn_confirm'])
            if close:
                self.click(close.x, close.y, '关闭弹窗', ActionType.CLOSE_POPUP)
                self.sleep(0.2)
                continue

            self.sleep(0.3)
        return actions


class FriendOps(_OpsBase):
    """封装 `FriendOps` 相关业务操作流程。"""
    def _help_in_friend_farm(self, rect: tuple[int, int, int, int]) -> list[str]:
        """在好友农场执行浇水/除草/除虫，完成后尝试回家。"""
        actions_done: list[str] = []
        idle_rounds = 0

        # 好友场景优先执行维护动作，其次回家，最后清理弹窗。
        for _ in range(12):
            if self.stopped:
                break

            cv_img, dets, _ = self.capture(
                rect,
                template_names=[
                    'btn_water',
                    'btn_weed',
                    'btn_bug',
                    'btn_home',
                    'btn_claim',
                    'btn_confirm',
                    'btn_close',
                ],
            )
            if cv_img is None:
                break

            acted = False
            # 维护动作按固定优先级串行执行，每轮只处理一项，降低误触概率。
            for btn_name, desc, action_type in [
                ('btn_water', '帮好友浇水', ActionType.HELP_WATER),
                ('btn_weed', '帮好友除草', ActionType.HELP_WEED),
                ('btn_bug', '帮好友除虫', ActionType.HELP_BUG),
            ]:
                btn = self.find_by_name(dets, btn_name)
                if not btn:
                    continue
                self.click(btn.x, btn.y, desc, action_type)
                actions_done.append(desc)
                acted = True
                self.sleep(0.3)
                break

            if acted:
                # 本轮有动作则重置空转计数，继续下一轮识别。
                idle_rounds = 0
                continue

            home = self.find_by_name(dets, 'btn_home')
            if home:
                self.click(home.x, home.y, '回家')
                actions_done.append('回家')
                self.sleep(0.3)
                break

            # 若被奖励/确认弹窗打断，先清弹窗再继续好友巡查。
            popup = self.find_any(dets, ['btn_claim', 'btn_confirm', 'btn_close'])
            if popup:
                self.click(popup.x, popup.y, '关闭弹窗', ActionType.CLOSE_POPUP)
                self.sleep(0.2)
                continue

            # 连续空转两轮后结束，避免在无可操作状态下循环卡住。
            idle_rounds += 1
            if idle_rounds >= 2:
                break
            self.sleep(0.2)

        return actions_done


class PlantOps(_OpsBase):
    """封装 `PlantOps` 相关业务操作流程。"""
    def __init__(self, engine):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine)
        self.shop_ocr = ShopItemOCR()

    def plant_all(self, rect: tuple[int, int, int, int], crop_name: str) -> list[str]:
        """执行整块农田播种流程（识别空地、拉种子、补种购买）。"""
        all_actions: list[str] = []

        # 先找空地；无空地直接返回，避免无意义后续流程。
        cv_img, dets, _ = self.capture(
            rect,
            template_names=['land_empty', 'land_empty_2', 'land_empty_3'],
            thresholds={'land_empty': 0.89, 'land_empty_2': 0.89, 'land_empty_3': 0.89},
        )
        if cv_img is None:
            return all_actions
        lands = [d for d in dets if d.name.startswith('land_empty')]
        if not lands:
            return all_actions

        # 先点击一块空地唤起种子条。
        self.click(lands[0].x, lands[0].y, '点击空地')
        self.sleep(0.3)

        seed_det = None
        for _ in range(2):
            if self.stopped:
                return all_actions
            cv_img, _dets, _ = self.capture(rect, template_names=[])
            if cv_img is None:
                return all_actions
            seed_dets = self.engine.cv_detector.detect_seed_template(cv_img, crop_name_or_template=crop_name)
            if seed_dets:
                seed_det = seed_dets[0]
                break
            self.sleep(0.3)

        # 没找到种子则走购买流程；购买成功后递归重试一次播种。
        if not seed_det:
            buy_result = self._buy_seeds(rect, crop_name)
            if buy_result:
                all_actions.append(buy_result)
                return all_actions + self.plant_all(rect, crop_name)
            return all_actions

        if not self.engine.action_executor:
            return all_actions

        # 长按拖拽种子穿过空地批量播种。
        seed_x, seed_y = int(seed_det.x), int(seed_det.y)
        resolver = getattr(self.engine, 'resolve_live_click_point', None)
        if callable(resolver):
            seed_x, seed_y = resolver(seed_x, seed_y)
        seed_abs_x, seed_abs_y = self.engine.action_executor.relative_to_absolute(seed_x, seed_y)
        planted_count = 0
        dragging = False
        try:
            if self.stopped:
                return all_actions
            pyautogui.moveTo(seed_abs_x, seed_abs_y, duration=0.05)
            if not self.sleep(0.1):
                return all_actions
            pyautogui.mouseDown()
            dragging = True
            if not self.sleep(0.1):
                return all_actions

            for land in lands:
                if self.stopped:
                    break
                land_x, land_y = int(land.x), int(land.y)
                if callable(resolver):
                    land_x, land_y = resolver(land_x, land_y)
                abs_x, abs_y = self.engine.action_executor.relative_to_absolute(land_x, land_y)
                pyautogui.moveTo(abs_x, abs_y, duration=0.1)
                if not self.sleep(0.15):
                    break
                planted_count += 1
        finally:
            if dragging:
                try:
                    pyautogui.mouseUp()
                except Exception:
                    pass

        if planted_count > 0:
            all_actions.append(f'播种{crop_name}×{planted_count}')

        # 播种后清理残留商店/施肥弹窗，避免影响下一轮页面判断。
        self.sleep(0.5)
        cv_check, dets_check, _ = self.capture(
            rect,
            template_names=['btn_shop_close', 'btn_fertilize_popup'],
        )
        if cv_check is not None:
            if self.find_by_name(dets_check, 'btn_shop_close'):
                self._close_shop_and_buy(rect, crop_name, all_actions)

            if self.find_by_name(dets_check, 'btn_fertilize_popup'):
                self.click_blank(rect)

        return all_actions

    def _close_shop_and_buy(self, rect: tuple[int, int, int, int], crop_name: str, actions_done: list[str]):
        """关闭商店后立刻执行一次补种购买。"""
        self._close_shop(rect)
        buy_result = self._buy_seeds(rect, crop_name)
        if buy_result:
            actions_done.append(buy_result)

    def _buy_seeds(self, rect: tuple[int, int, int, int], crop_name: str) -> str | None:
        """执行买种流程：开商店 -> OCR 定位 -> 选择并确认购买。"""
        if self.stopped:
            return None
        # 购买流程：开商店 -> OCR找作物 -> 购买确认 -> 关商店。
        cv_img, dets, _ = self.capture(rect, template_names=['btn_shop'])
        if cv_img is None:
            return None

        shop_btn = self.find_by_name(dets, 'btn_shop')
        if not shop_btn:
            logger.warning('购买流程: 未找到商店按钮')
            return None
        self.click(shop_btn.x, shop_btn.y, '打开商店')
        self.sleep(1.0)

        shop_cv = None
        for _ in range(5):
            if self.stopped:
                return None
            cv_img, dets, _ = self.capture(rect, template_names=['btn_shop_close'])
            if cv_img is None:
                return None
            if self.find_by_name(dets, 'btn_shop_close'):
                shop_cv = cv_img
                break
            self.sleep(0.5)
        if shop_cv is None:
            self._close_shop(rect)
            return None

        matched_item = None
        for _ in range(3):
            if self.stopped:
                return None
            ocr_match = self.shop_ocr.find_item(shop_cv, crop_name, min_similarity=0.70)
            if ocr_match.target:
                matched_item = ocr_match.target
                break
            self.sleep(0.3)
            cv_img, _dets, _ = self.capture(rect, template_names=[])
            if cv_img is None:
                return None
            shop_cv = cv_img

        if not matched_item:
            logger.warning(f"购买流程: OCR未找到 '{crop_name}'")
            self._close_shop(rect)
            return None

        self.click(matched_item.center_x, matched_item.center_y, f'选择{crop_name}')
        self.sleep(1.0)
        return self._confirm_purchase(rect, crop_name)

    def _confirm_purchase(self, rect: tuple[int, int, int, int], crop_name: str) -> str | None:
        """在购买弹窗中执行确认并处理伴随弹窗。"""
        # 循环等待购买确认，期间兼容关闭二级弹窗。
        for _ in range(5):
            if self.stopped:
                return None
            cv_img, dets, _ = self.capture(
                rect,
                template_names=['btn_buy_confirm', 'btn_close', 'btn_confirm', 'btn_claim'],
            )
            if cv_img is None:
                return None

            confirm = self.find_by_name(dets, 'btn_buy_confirm')
            if confirm:
                self.click(confirm.x, confirm.y, f'确定购买{crop_name}')
                self.sleep(0.3)
                self._close_shop(rect)
                return f'购买{crop_name}'

            close = self.find_any(dets, ['btn_close', 'btn_confirm', 'btn_claim'])
            if close:
                self.click(close.x, close.y, '关闭弹窗', ActionType.CLOSE_POPUP)
                self.sleep(0.2)
                continue

            self.sleep(0.3)

        self._close_shop(rect)
        return None

    def _close_shop(self, rect: tuple[int, int, int, int]):
        """尽可能关闭商店页残留弹窗，回到主流程页面。"""
        for _ in range(3):
            cv_img, dets, _ = self.capture(rect, template_names=['btn_shop_close', 'btn_close'])
            if cv_img is None:
                return
            close_btn = self.find_any(dets, ['btn_shop_close', 'btn_close'])
            if not close_btn:
                return
            self.click(close_btn.x, close_btn.y, '关闭商店', ActionType.CLOSE_POPUP)
            self.sleep(0.3)

