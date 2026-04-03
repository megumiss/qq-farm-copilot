"""nklite 农场主任务。"""

from __future__ import annotations

import time

from loguru import logger

from core.nklite.base.step_result import StepResult
from core.nklite.tasks.task_farm_friend import TaskFarmFriend
from core.nklite.tasks.task_farm_harvest import TaskFarmHarvest
from core.nklite.tasks.task_farm_plant import TaskFarmPlant
from core.nklite.tasks.task_farm_reward import TaskFarmReward
from core.nklite.tasks.task_farm_sell import TaskFarmSell
from core.nklite.ui.page import (
    page_friend,
    page_main,
    page_menu,
    page_shop,
    page_unknown,
)


class TaskFarmMain:
    def __init__(self, engine, ui):
        self.engine = engine
        self.ui = ui
        self.task_harvest = TaskFarmHarvest(engine, ui)
        self.task_plant = TaskFarmPlant(engine, ui)
        self.task_sell = TaskFarmSell(engine, ui)
        self.task_reward = TaskFarmReward(engine, ui)
        self.task_friend = TaskFarmFriend(engine, ui)

    def run(self, session_id: int | None = None) -> dict:
        result = {'success': False, 'actions_done': [], 'next_check_seconds': 5}
        if self.engine._is_cancel_requested(session_id):
            result['message'] = '停止中'
            return result

        features = self.engine.config.features.model_dump()
        rect = self.engine._prepare_window()
        if not rect:
            result['message'] = '窗口未找到'
            return result
        self.ui.device.set_rect(rect)

        self.engine._clear_screen(rect, session_id)
        self.ui.ui_ensure(page_main, confirm_wait=0.15)

        idle_rounds = 0
        max_idle = 3
        sold_this_round = False
        tick = 0
        transition_budget = max(30, int(self.engine.config.safety.max_actions_per_round) * 3)

        while tick < transition_budget:
            if self.engine._is_cancel_requested(session_id):
                logger.info('收到停止/暂停信号，中断当前操作')
                break

            tick_start = time.perf_counter()
            detect_start = time.perf_counter()

            cv_image, _ = self.engine._capture_frame(rect, save=False)
            if cv_image is None:
                result['message'] = '截屏失败'
                break
            self.ui.device.set_image(cv_image)

            page = self.ui.ui_get_current_page(skip_first_screenshot=True, timeout=0.9)
            if page == page_unknown:
                recovered = self.ui.ui_goto(page_main, confirm_wait=0.1, skip_first_screenshot=True)
                if recovered:
                    result['actions_done'].append('导航回主界面')
                    if not self.engine._sleep_interruptible(0.2, session_id):
                        break
                    continue
                self.engine.popup.click_blank(rect)
                result['actions_done'].append('点击空白处')
                if not self.engine._sleep_interruptible(0.2, session_id):
                    break
                continue

            if self.ui.ui_additional():
                result['actions_done'].append('处理弹窗')
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

            result['actions_done'].extend(dispatch_result.actions)
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

            if action_desc:
                idle_rounds = 0
            else:
                idle_rounds += 1
                if idle_rounds == 1:
                    self.engine.popup.click_blank(rect)
                elif idle_rounds >= max_idle:
                    break

            if not self.engine._sleep_interruptible(0.3, session_id):
                break
        else:
            logger.info(f'达到页面跳转预算上限: {transition_budget}，结束本轮')

        has_planted = any('播种' in a for a in result.get('actions_done', []))
        if has_planted:
            interval = self.engine.config.schedule.farm_check_minutes * 60
            result['next_check_seconds'] = interval
        else:
            result['next_check_seconds'] = 30

        result['success'] = True
        self.engine.screen_capture.cleanup_old_screenshots(0)
        return result

    def _run_main_tasks(
        self,
        rect: tuple[int, int, int, int],
        features: dict,
        sold_this_round: bool,
    ) -> tuple[StepResult, bool]:
        out = self.task_harvest.run(features=features)
        if out.action:
            return out, sold_this_round

        out = self.task_plant.run(rect=rect, features=features)
        if out.action:
            return out, sold_this_round

        if features.get('auto_upgrade', True):
            cv_image = self.ui.device.image
            cur = self.engine._augment_detections(cv_image, [], ['btn_expand']) if cv_image is not None else []
            out = StepResult.from_value(self.engine.expand.try_expand(rect, cur))
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

    def _run_page_specific(self, page, rect: tuple[int, int, int, int]) -> StepResult:
        if page == page_friend:
            return StepResult.from_value(self.engine.friend._help_in_friend_farm(rect))
        return StepResult()
