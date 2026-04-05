"""nklite 农场主任务。"""

from __future__ import annotations

import time

from loguru import logger

from core.engine.task.registry import TaskResult
from core.base.step_result import StepResult
from core.tasks.farm_friend import TaskFarmFriend
from core.tasks.farm_harvest import TaskFarmHarvest
from core.tasks.farm_plant import TaskFarmPlant
from core.tasks.farm_reward import TaskFarmReward
from core.tasks.farm_sell import TaskFarmSell
from core.ui.page import (
    GOTO_MAIN,
    page_friend,
    page_main,
    page_shop,
    page_unknown,
)
from core.ui.assets import (
    BTN_CLAIM,
    BTN_CLOSE,
    BTN_CONFIRM,
    BTN_EXPAND,
    BTN_EXPAND_CONFIRM,
    BTN_EXPAND_DIRECT_CONFIRM,
)


class TaskFarmMain:
    """封装 `TaskFarmMain` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui
        self._expand_failed = False
        self.task_harvest = TaskFarmHarvest(engine, ui)
        self.task_plant = TaskFarmPlant(engine, ui)
        self.task_sell = TaskFarmSell(engine, ui)
        self.task_reward = TaskFarmReward(engine, ui)
        self.task_friend = TaskFarmFriend(engine, ui)

    def run(self, session_id: int | None = None) -> TaskResult:
        """执行当前模块主流程并返回结果。"""
        result = TaskResult(success=False, actions=[], next_run_seconds=None, error='')
        if self.engine._is_cancel_requested(session_id):
            result.error = '停止中'
            return result

        # [准备阶段] 同步窗口与 UI 状态，确保从主界面开始执行。
        features = self.engine.get_task_features('farm_main')
        rect = self.engine._prepare_window()
        if not rect:
            result.error = '窗口未找到'
            return result
        self.ui.device.set_rect(rect)

        self.engine._clear_screen(rect, session_id)
        self.ui.ui_ensure(page_main, confirm_wait=0.5)

        # [巡查阶段] 先做自家农场维护（收获/除草/除虫/浇水）。
        patrol_actions = self._run_self_farm_patrol(rect=rect, features=features, session_id=session_id)
        if patrol_actions:
            result.actions.extend(patrol_actions)

        idle_rounds = 0
        max_idle = 3
        sold_this_round = False
        tick = 0
        transition_budget = max(30, int(self.engine.config.safety.max_actions_per_round) * 3)

        # [主循环阶段] 按页面识别结果驱动任务分发，直到达到预算或进入空闲。
        while tick < transition_budget:
            if self.engine._is_cancel_requested(session_id):
                logger.info('收到停止/暂停信号，中断当前操作')
                break

            tick_start = time.perf_counter()
            detect_start = time.perf_counter()

            cv_image, _ = self.engine._capture_frame(rect, save=False)
            if cv_image is None:
                result.error = '截屏失败'
                break
            self.ui.device.set_image(cv_image)

            page = self.ui.ui_get_current_page(skip_first_screenshot=True, timeout=0.9)
            if page == page_unknown:
                # 未知页面优先尝试导航回主，否则点击固定回主点。
                recovered = self.ui.ui_goto(page_main, confirm_wait=0.5, skip_first_screenshot=True)
                if recovered:
                    result.actions.append('导航回主界面')
                    if not self.engine._sleep_interruptible(0.2, session_id):
                        break
                    continue
                self._click_goto_main(rect)
                result.actions.append('点击回主按钮')
                if not self.engine._sleep_interruptible(0.2, session_id):
                    break
                continue

            if self.ui.ui_additional():
                # 弹窗处理命中后立即进入下一轮，避免污染当前页面判断。
                result.actions.append('处理弹窗')
                if not self.engine._sleep_interruptible(0.2, session_id):
                    break
                continue

            tick += 1
            detections = []
            detect_ms = (time.perf_counter() - detect_start) * 1000.0
            self.engine.scheduler.update_runtime_metrics(
                current_page=page.cn_name,
                current_task='farm_main',
                failure_count=self.engine._runtime_failure_count,
            )

            det_summary = ', '.join(f'{d.name}({d.confidence:.0%})' for d in detections[:6])
            logger.info(f'[tick={tick}] 页面={page.cn_name} | {det_summary}')
            self.engine._emit_annotated(cv_image, detections)

            action_start = time.perf_counter()
            if page == page_main:
                dispatch_result, sold_this_round = self._run_main_tasks(
                    rect=rect,
                    features=features,
                    sold_this_round=sold_this_round,
                )
            elif page == page_shop:
                dispatch_result = StepResult()
            else:
                dispatch_result = self._run_page_specific(page=page, rect=rect)
            action_ms = (time.perf_counter() - action_start) * 1000.0
            tick_ms = (time.perf_counter() - tick_start) * 1000.0

            result.actions.extend(dispatch_result.actions)
            action_desc = dispatch_result.action
            logger.info(
                'task=farm_main page={} action={} detect_ms={:.1f} action_ms={:.1f} tick_ms={:.1f}',
                page.cn_name,
                action_desc or 'none',
                detect_ms,
                action_ms,
                tick_ms,
            )
            self.engine.scheduler.update_runtime_metrics(
                last_result=action_desc or 'none',
                last_tick_ms=f'{tick_ms:.1f}ms',
            )

            # 连续空转时先点一次回主，再在上限处提前结束本轮。
            if action_desc:
                idle_rounds = 0
            else:
                idle_rounds += 1
                if idle_rounds == 1:
                    self._click_goto_main(rect)
                elif idle_rounds >= max_idle:
                    break

            if not self.engine._sleep_interruptible(0.3, session_id):
                break
        else:
            logger.info(f'达到页面跳转预算上限: {transition_budget}，结束本轮')

        result.success = True
        self.engine.screen_capture.cleanup_old_screenshots(0)
        return result

    def _run_main_tasks(
        self,
        rect: tuple[int, int, int, int],
        features: dict,
        sold_this_round: bool,
    ) -> tuple[StepResult, bool]:
        """执行 `main_tasks` 子流程。"""
        out = self.task_plant.run(rect=rect, features=features)
        if out.action:
            return out, sold_this_round

        if features.get('auto_upgrade', False):
            out = StepResult.from_value(self._try_expand(rect))
            if out.action:
                return out, sold_this_round

        out, sold_this_round = self.task_sell.run(features=features, sold_this_round=sold_this_round)
        if out.action:
            return out, sold_this_round

        out = self.task_reward.run(rect=rect, features=features)
        if out.action:
            return out, sold_this_round

        out = self.task_friend.run(rect=rect, features=features)
        return out, sold_this_round

    def _run_self_farm_patrol(
        self,
        rect: tuple[int, int, int, int],
        features: dict,
        session_id: int | None,
    ) -> list[str]:
        """自家农场巡查阶段：收获/除草/除虫/浇水，独立于主流程分发。"""
        actions: list[str] = []
        max_rounds = 8

        for _ in range(max_rounds):
            if self.engine._is_cancel_requested(session_id):
                break

            cv_image, _ = self.engine._capture_frame(rect, save=False)
            if cv_image is None:
                break
            self.ui.device.set_image(cv_image)

            if self.ui.ui_additional():
                actions.append('处理弹窗')
                if not self.engine._sleep_interruptible(0.2, session_id):
                    break
                continue

            page = self.ui.ui_get_current_page(skip_first_screenshot=True, timeout=0.9)
            if page != page_main:
                if self.ui.ui_goto(page_main, confirm_wait=0.4, skip_first_screenshot=True):
                    actions.append('导航回主界面')
                    if not self.engine._sleep_interruptible(0.2, session_id):
                        break
                    continue
                break

            out = self.task_harvest.run(features=features)
            if not out.action:
                break
            actions.extend(out.actions)
            if not self.engine._sleep_interruptible(0.2, session_id):
                break

        return actions

    def _run_page_specific(self, page, rect: tuple[int, int, int, int]) -> StepResult:
        """执行 `page_specific` 子流程。"""
        if page == page_friend:
            return StepResult.from_value(self.task_friend.help_in_friend_farm(rect))
        return StepResult()

    def _click_goto_main(self, rect: tuple[int, int, int, int]):
        """点击回主按钮。"""
        x, y = self.engine._resolve_goto_main_point(rect)
        self.engine._nklite_click(x, y, GOTO_MAIN.name)

    def _refresh_ui_image(self, rect: tuple[int, int, int, int]) -> bool:
        """刷新一帧并更新 UI 缓存图像。"""
        cv_img, _dets, _image = self.engine._capture_and_detect(rect, save=False, template_names=[])
        if cv_img is None:
            return False
        self.ui.device.set_image(cv_img)
        return True

    def _try_expand(self, rect: tuple[int, int, int, int]) -> str | None:
        """尝试执行一次扩建流程；失败后会进入短路状态避免反复触发。"""
        if self._expand_failed:
            return None

        if not self.ui.appear_then_click(BTN_EXPAND, offset=(30, 30), interval=1, threshold=0.8, static=False):
            return None
        self.engine._sleep_interruptible(0.5)

        for _ in range(5):
            if self.engine._is_cancel_requested():
                return None
            if not self._refresh_ui_image(rect):
                return None

            action_name = None
            if self.ui.appear_then_click(
                BTN_EXPAND_DIRECT_CONFIRM, offset=(30, 30), interval=1, threshold=0.8, static=False
            ):
                action_name = '直接扩建'
            elif self.ui.appear_then_click(BTN_EXPAND_CONFIRM, offset=(30, 30), interval=1, threshold=0.8, static=False):
                action_name = '扩建确认'

            if action_name:
                self.engine._sleep_interruptible(0.5)
                self._expand_failed = False
                if self._refresh_ui_image(rect):
                    self.ui.appear_then_click_any(
                        [BTN_CLOSE, BTN_CONFIRM, BTN_CLAIM],
                        offset=(30, 30),
                        interval=1,
                        threshold=0.8,
                        static=False,
                    )
                return action_name

            if self.ui.appear_then_click_any(
                [BTN_CLOSE, BTN_CONFIRM, BTN_CLAIM],
                offset=(30, 30),
                interval=1,
                threshold=0.8,
                static=False,
            ):
                self.engine._sleep_interruptible(0.2)
                continue
            self.engine._sleep_interruptible(0.3)

        self._expand_failed = True
        logger.info('扩建条件不满足，暂停扩建检测')
        return None
