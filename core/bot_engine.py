"""Bot引擎 — 主控编排层

四层架构：
  [1] 窗口控制层: window_manager + screen_capture
  [2] 图像识别层: cv_detector + scene_detector
  [3] 行为决策层: strategies/ (模块化策略)
  [4] 操作执行层: action_executor

优先级：
  P-1 异常处理: popup     — 关闭弹窗/商店/返回主界面
  P0  收益:     harvest   — 一键收获 + 自动出售
  P1  维护:     maintain  — 一键除草/除虫/浇水
  P2  生产:     plant     — 播种 + 购买种子 + 施肥
  P3  资源:     expand    — 扩建土地 + 领取任务
  P4  社交:     friend    — 好友巡查/帮忙/偷菜/同意好友
"""
import time
import cv2
import numpy as np
from PIL import Image as PILImage
from loguru import logger

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from models.config import AppConfig, PlantMode
from models.farm_state import ActionType
from models.game_data import get_best_crop_for_level, get_crop_by_name, format_grow_time
from core.window_manager import WindowManager
from core.screen_capture import ScreenCapture
from core.cv_detector import CVDetector, DetectResult
from core.action_executor import ActionExecutor
from core.task_scheduler import TaskScheduler, BotState
from core.scene_detector import Scene, identify_scene
from core.strategies import (
    PopupStrategy, HarvestStrategy, MaintainStrategy,
    PlantStrategy, ExpandStrategy, FriendStrategy, TaskStrategy,
)


class BotWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, engine: "BotEngine", task_type: str = "farm"):
        super().__init__()
        self.engine = engine
        self.task_type = task_type

    def run(self):
        try:
            if self.task_type == "farm":
                result = self.engine.check_farm()
            elif self.task_type == "friend":
                result = self.engine.check_friends()
            else:
                result = {"success": False, "message": "未知任务类型"}
            self.finished.emit(result)
        except Exception as e:
            logger.exception(f"任务执行异常: {e}")
            self.error.emit(str(e))


class BotEngine(QObject):
    log_message = pyqtSignal(str)
    screenshot_updated = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    detection_result = pyqtSignal(object)

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config

        # [1] 窗口控制层
        self.window_manager = WindowManager()
        self.screen_capture = ScreenCapture()

        # [2] 图像识别层
        self.cv_detector = CVDetector(templates_dir="templates")

        # [3] 行为决策层（按优先级）
        self.popup = PopupStrategy(self.cv_detector)       # P-1
        self.harvest = HarvestStrategy(self.cv_detector)    # P0
        self.maintain = MaintainStrategy(self.cv_detector)  # P1
        self.plant = PlantStrategy(self.cv_detector)        # P2
        self.expand = ExpandStrategy(self.cv_detector)      # P3
        self.task = TaskStrategy(self.cv_detector)          # P3.5
        self.friend = FriendStrategy(self.cv_detector)      # P4
        self._strategies = [self.popup, self.harvest, self.maintain,
                            self.plant, self.expand, self.task, self.friend]

        # [4] 操作执行层
        self.action_executor: ActionExecutor | None = None

        # 调度
        self.scheduler = TaskScheduler()
        self._worker: BotWorker | None = None
        self._is_busy = False

        self.scheduler.farm_check_triggered.connect(self._on_farm_check)
        self.scheduler.friend_check_triggered.connect(self._on_friend_check)
        self.scheduler.state_changed.connect(self.state_changed.emit)
        self.scheduler.stats_updated.connect(self.stats_updated.emit)

    def _init_strategies(self):
        """初始化所有策略的依赖"""
        for s in self._strategies:
            s.action_executor = self.action_executor
            s.set_capture_fn(self._capture_and_detect)
            s._stop_requested = False
        self.task.sell_config = self.config.sell

    def update_config(self, config: AppConfig):
        self.config = config
        self.task.sell_config = config.sell

    def _resolve_crop_name(self) -> str:
        """根据策略决定种植作物"""
        planting = self.config.planting
        if planting.strategy == PlantMode.BEST_EXP_RATE:
            best = get_best_crop_for_level(planting.player_level)
            if best:
                logger.info(f"策略选择: {best[0]} (经验效率 {best[4]/best[3]:.4f}/秒)")
                return best[0]
        return planting.preferred_crop

    def _clear_screen(self, rect: tuple):
        """点击窗口顶部天空区域，关闭残留弹窗/菜单/土地信息

        点击位置：水平居中，垂直 5% 处（天空区域，不会触发任何游戏操作）。
        连续点击 2 次，间隔 0.3 秒等待动画消失。
        """
        if not self.action_executor:
            return

        platform = getattr(self.config.planting, "window_platform", "qq")
        platform_value = platform.value if hasattr(platform, "value") else str(platform)
        if not rect or len(rect) != 4:
            logger.warning("清屏点击跳过: capture rect 不可用")
            return

        cap_left, cap_top, cap_w, cap_h = [int(v) for v in rect]
        x1, y1, crop_w, crop_h = self.window_manager.get_preview_crop_box(
            raw_width=cap_w,
            raw_height=cap_h,
            platform=platform_value,
        )
        sky_x = int(cap_left + x1 + crop_w // 2)
        sky_y = int(cap_top + y1 + max(10, int(crop_h * 0.05)))

        for _ in range(2):
            self.action_executor.click(sky_x, sky_y)
            time.sleep(0.3)


    def start(self) -> bool:
        self.cv_detector.load_templates()
        tpl_count = sum(len(v) for v in self.cv_detector._templates.values())
        if tpl_count == 0:
            self.log_message.emit("未找到模板图片，请先运行模板采集工具")
            return False

        window = self.window_manager.find_window(self.config.window_title_keyword)
        if not window:
            self.log_message.emit("未找到QQ农场窗口，请先打开微信小程序中的QQ农场")
            return False

        pos = getattr(self.config.planting, "window_position", "left_center")
        pos_value = pos.value if hasattr(pos, "value") else str(pos)
        platform = getattr(self.config.planting, "window_platform", "qq")
        platform_value = platform.value if hasattr(platform, "value") else str(platform)
        self.window_manager.resize_window(pos_value, platform_value)
        time.sleep(0.5)
        window = self.window_manager.refresh_window_info(self.config.window_title_keyword)
        self.log_message.emit(
            "窗口已调整（整窗外框目标：540x960 + 非客户区增量）-> "
            f"实际外框 {window.width}x{window.height}"
        )

        rect = self.window_manager.get_capture_rect()
        if not rect:
            rect = (window.left, window.top, window.width, window.height)
        self.action_executor = ActionExecutor(
            window_rect=rect,
            delay_min=self.config.safety.random_delay_min,
            delay_max=self.config.safety.random_delay_max,
            click_offset=self.config.safety.click_offset_range,
        )
        self._init_strategies()

        farm_ms = self.config.schedule.farm_check_minutes * 60 * 1000
        friend_ms = self.config.schedule.friend_check_minutes * 60 * 1000
        self.scheduler.start(farm_ms, friend_ms)
        self.log_message.emit(f"Bot已启动 - 窗口: {window.title} | 模板: {tpl_count}个")
        return True

    def stop(self):
        for s in self._strategies:
            s._stop_requested = True
        self.scheduler.stop()
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        self._is_busy = False
        for s in self._strategies:
            s._stop_requested = False
        self.log_message.emit("Bot已停止")

    def pause(self):
        for s in self._strategies:
            s._stop_requested = True
        self.scheduler.pause()

    def resume(self):
        for s in self._strategies:
            s._stop_requested = False
        self.scheduler.resume()

    def run_once(self):
        self._on_farm_check()

    def _on_farm_check(self):
        if self._is_busy:
            logger.debug("上一轮操作尚未完成，跳过")
            return
        self._is_busy = True
        self._worker = BotWorker(self, "farm")
        self._worker.finished.connect(self._on_task_finished)
        self._worker.error.connect(self._on_task_error)
        self._worker.start()

    def _on_friend_check(self):
        if self._is_busy:
            return
        if not self.config.features.auto_steal and not self.config.features.auto_help:
            return
        self._is_busy = True
        self._worker = BotWorker(self, "friend")
        self._worker.finished.connect(self._on_task_finished)
        self._worker.error.connect(self._on_task_error)
        self._worker.start()

    def _on_task_finished(self, result: dict):
        self._is_busy = False
        actions = result.get("actions_done", [])
        if actions:
            self.log_message.emit(f"本轮完成: {', '.join(actions)}")
        next_sec = result.get("next_check_seconds", 0)
        if next_sec > 0:
            self.scheduler.set_farm_interval(next_sec)

    def _on_task_error(self, error_msg: str):
        self._is_busy = False
        self.log_message.emit(f"操作异常: {error_msg}")

    # ============================================================
    # 截屏 + 检测
    # ============================================================

    def _prepare_window(self) -> tuple | None:
        window = self.window_manager.refresh_window_info(self.config.window_title_keyword)
        if not window:
            return None
        self.window_manager.activate_window()
        time.sleep(0.3)
        rect = self.window_manager.get_capture_rect()
        if not rect:
            rect = (window.left, window.top, window.width, window.height)
        if self.action_executor:
            self.action_executor.update_window_rect(rect)
        return rect

    def _crop_preview_image(self, image: PILImage.Image | None) -> PILImage.Image | None:
        """仅用于左侧预览显示：按 nonclient 配置裁掉窗口边框/标题栏。"""
        if image is None:
            return None
        platform = getattr(self.config.planting, "window_platform", "qq")
        platform_value = platform.value if hasattr(platform, "value") else str(platform)
        return self.window_manager.crop_window_image_for_preview(image, platform_value)

    def _capture_and_detect(self, rect: tuple, prefix: str = "farm",
                            categories: list[str] | None = None,
                            save: bool = True
                            ) -> tuple[np.ndarray | None, list[DetectResult], PILImage.Image | None]:
        if save:
            image, _ = self.screen_capture.capture_and_save(rect, prefix)
        else:
            image = self.screen_capture.capture_region(rect)
        if image is None:
            return None, [], None
        preview_image = self._crop_preview_image(image)
        if preview_image is not None:
            self.screenshot_updated.emit(preview_image)
        cv_image = self.cv_detector.pil_to_cv2(image)

        if categories is not None:
            detections = []
            for cat in categories:
                detections += self.cv_detector.detect_category(cv_image, cat, threshold=0.8)
            detections = self.cv_detector._nms(detections, iou_threshold=0.5)
        else:
            detections = []
            for cat in self.cv_detector._templates:
                if cat in ("seed", "shop"):
                    continue
                if cat == "land":
                    thresh = 0.89
                elif cat == "button":
                    thresh = 0.8
                else:
                    thresh = 0.8
                detections += self.cv_detector.detect_category(cv_image, cat, threshold=thresh)
            detections = [d for d in detections
                          if d.name != "btn_shop_close"
                          and not (d.name == "btn_expand" and d.confidence < 0.85)]

        return cv_image, detections, image

    def _emit_annotated(self, cv_image: np.ndarray, detections: list[DetectResult]):
        if detections:
            annotated = self.cv_detector.draw_results(cv_image, detections)
            annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            annotated_pil = PILImage.fromarray(annotated_rgb)
            preview_annotated = self._crop_preview_image(annotated_pil)
            if preview_annotated is not None:
                self.detection_result.emit(preview_annotated)

    def _record_stat(self, action_type: str):
        type_map = {
            ActionType.HARVEST: "harvest", ActionType.PLANT: "plant",
            ActionType.WATER: "water", ActionType.WEED: "weed",
            ActionType.BUG: "bug", ActionType.STEAL: "steal",
            ActionType.SELL: "sell",
        }
        stat_key = type_map.get(action_type)
        if stat_key:
            self.scheduler.record_action(stat_key)


    # ============================================================
    # 主循环
    # ============================================================

    def check_farm(self) -> dict:
        result = {"success": False, "actions_done": [], "next_check_seconds": 5}
        features = self.config.features.model_dump()
        buy_qty = self.config.planting.buy_quantity

        rect = self._prepare_window()
        if not rect:
            result["message"] = "窗口未找到"
            return result

        # 清屏：点击天空区域关闭残留弹窗/菜单
        self._clear_screen(rect)

        idle_rounds = 0
        max_idle = 3

        for round_num in range(1, 51):
            if self.popup.stopped:
                logger.info("收到停止/暂停信号，中断当前操作")
                break

            cv_image, detections, _ = self._capture_and_detect(rect, save=False)
            if cv_image is None:
                result["message"] = "截屏失败"
                break

            scene = identify_scene(detections, self.cv_detector, cv_image)
            det_summary = ", ".join(f"{d.name}({d.confidence:.0%})" for d in detections[:6])
            logger.info(f"[轮{round_num}] 场景={scene.value} | {det_summary}")
            self._emit_annotated(cv_image, detections)

            action_desc = None

            # ---- P-1 异常处理 ----
            if scene == Scene.LEVEL_UP:
                action_desc = self.popup.handle_popup(detections)
                self.config.planting.player_level += 1
                self.config.save()
                new_level = self.config.planting.player_level
                self.log_message.emit(f"升级! Lv.{new_level - 1} → Lv.{new_level}")
                self.log_message.emit(f"当前种植: {self._resolve_crop_name()}")
            elif scene == Scene.POPUP:
                action_desc = self.popup.handle_popup(detections)
            elif scene == Scene.BUY_CONFIRM:
                action_desc = self.popup.handle_popup(detections)
            elif scene == Scene.SHOP_PAGE:
                self.popup.close_shop(rect)
                action_desc = "关闭商店"
            elif scene == Scene.PLOT_MENU:
                action_desc = self.popup.handle_popup(detections)

            # ---- 农场主页操作 ----
            elif scene == Scene.FARM_OVERVIEW:
                # P0 收益：一键收获
                if not action_desc and features.get("auto_harvest", True):
                    action_desc = self.harvest.try_harvest(detections)

                # P1 维护：除草/除虫/浇水
                if not action_desc:
                    action_desc = self.maintain.try_maintain(detections, features)

                # P2 生产：播种
                if not action_desc and features.get("auto_plant", True):
                    pa = self.plant.plant_all(rect, self._resolve_crop_name(), buy_qty)
                    if pa:
                        result["actions_done"].extend(pa)
                        action_desc = pa[-1]

                # P3 资源：扩建
                if not action_desc and features.get("auto_upgrade", True):
                    action_desc = self.expand.try_expand(rect, detections)

                # P3.5 任务：领取奖励 / 售卖果实
                if not action_desc and features.get("auto_task", True):
                    ta = self.task.try_task(rect, detections)
                    if ta:
                        result["actions_done"].extend(ta)
                        action_desc = ta[-1]

                # P4 社交：好友求助
                if not action_desc and features.get("auto_help", True):
                    fa = self.friend.try_friend_help(rect, detections)
                    if fa:
                        result["actions_done"].extend(fa)
                        action_desc = fa[-1]

            # ---- 好友家园 ----
            elif scene == Scene.FRIEND_FARM:
                fa = self.friend._help_in_friend_farm(rect)
                if fa:
                    result["actions_done"].extend(fa)
                    action_desc = fa[-1]

            elif scene == Scene.SEED_SELECT:
                crop_name = self._resolve_crop_name()
                seed = self.popup.find_by_name(detections, f"seed_{crop_name}")
                if seed:
                    self.popup.click(seed.x, seed.y, f"播种{crop_name}", ActionType.PLANT)
                    self._record_stat(ActionType.PLANT)
                    action_desc = f"播种{crop_name}"

            elif scene == Scene.UNKNOWN:
                self.popup.click_blank(rect)
                action_desc = "点击空白处"

            # ---- 结果处理 ----
            if action_desc:
                result["actions_done"].append(action_desc)
                idle_rounds = 0
            else:
                idle_rounds += 1
                if idle_rounds == 1:
                    self.popup.click_blank(rect)
                elif idle_rounds >= max_idle:
                    break

            time.sleep(0.3)

        # 设置下次检查间隔
        # 有播种操作 → 5分钟后检查维护（除虫/除草/浇水）
        # 无播种操作 → 30秒后再检查（可能有新状态）
        has_planted = any("播种" in a for a in result.get("actions_done", []))
        if has_planted:
            interval = self.config.schedule.farm_check_minutes * 60
            result["next_check_seconds"] = interval
            crop_name = self._resolve_crop_name()
            crop = get_crop_by_name(crop_name)
            if crop:
                grow_time = crop[3]
                logger.info(f"已播种{crop_name}，{format_grow_time(grow_time)}后成熟，每{self.config.schedule.farm_check_minutes}分钟检查维护")
        else:
            result["next_check_seconds"] = 30

        result["success"] = True
        self.screen_capture.cleanup_old_screenshots(0)
        return result

    def check_friends(self) -> dict:
        result = {"success": True, "actions_done": [], "next_check_seconds": 1800}
        logger.info("好友巡查功能开发中...")
        return result
