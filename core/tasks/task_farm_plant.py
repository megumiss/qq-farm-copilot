"""播种任务。"""

from __future__ import annotations

from core.base.step_result import StepResult
from core.ui.assets import LAND_EMPTY, LAND_EMPTY_2, LAND_EMPTY_3


class TaskFarmPlant:
    """封装 `TaskFarmPlant` 任务的执行入口与步骤。"""
    def __init__(self, engine, ui):
        """初始化对象并准备运行所需状态。"""
        self.engine = engine
        self.ui = ui

    def run(self, rect, features) -> StepResult:
        """执行当前模块主流程并返回结果。"""
        if not features.get('auto_plant', False):
            return StepResult()

        # seed 模板识别保持原有流程：由 plant.plant_all -> detect_seed_template 处理。
        has_land = self.ui.appear_any(
            [LAND_EMPTY, LAND_EMPTY_2, LAND_EMPTY_3],
            offset=(30, 30),
            threshold=0.89,
            static=False,
        )
        if not has_land:
            return StepResult()
        out = StepResult.from_value(self.engine.plant.plant_all(rect, self.engine._resolve_crop_name()))
        return out


