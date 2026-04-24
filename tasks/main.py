"""nklite 农场主任务。"""

from __future__ import annotations

from loguru import logger

from core.engine.task.registry import TaskResult
from core.ui.assets import *
from core.ui.page import page_main
from tasks.base import TaskBase
from tasks.main_actions import TaskMainActionsMixin
from tasks.main_land import TaskMainLandMixin
from utils.bg_patch_number_ocr import BgPatchNumberOCR
from utils.head_info_ocr import HeadInfoOCR
from utils.ocr_utils import OCRTool
from utils.shop_item_ocr import ShopItemOCR

# 商店列表上滑的起点坐标（用于翻页查找种子）。
SHOP_LIST_SWIPE_START = (270, 300)
# 商店列表上滑的终点坐标（与起点配合形成上滑手势）。
SHOP_LIST_SWIPE_END = (270, 860)

# 可播种空地模板集合（用于匹配可操作地块）。
LAND_LIST = [ICON_LAND_STAND, ICON_LAND_BLACK, ICON_LAND_RED, ICON_LAND_GOLD, ICON_LAND_GOLD_2]
# 空地模板命中的中心点 y 轴过滤区间，避免匹配到顶部 UI/底部无关区域。
LAND_MATCH_Y_RANGE = (350, 850)
# 轮询背景树锚点稳定性的采样间隔。
BACKGROUND_TREE_STABLE_CHECK_INTERVAL_SECONDS = 0.1
# 数字块识别区域横向范围（基于主界面截图绝对坐标）。
SEED_POPUP_NUMBER_REGION_X_MIN = 50
SEED_POPUP_NUMBER_REGION_X_MAX = 480
# 数字块识别区域纵向范围（基于“点击地块 y”做相对偏移）。
SEED_POPUP_NUMBER_REGION_Y_OFFSET_TOP = 40
SEED_POPUP_NUMBER_REGION_Y_OFFSET_BOTTOM = 80
# 主界面等级 OCR 顶部带高度（像素，平台无关）。
LEVEL_OCR_TOP_BAND_HEIGHT = 140
# 固定排除作物模板（始终生效）。
ALWAYS_SKIP_SEED_BUTTONS = [SEED_BTN_HEART_FRUIT]
# 可选排除作物模板（受配置开关控制）。
OPTIONAL_SKIP_SEED_BUTTONS = [SEED_BTN_MUGWORT]


class TaskMainLevelMixin:
    """提供播种前等级 OCR 与配置回写能力。"""

    def _get_level_ocr_region(self, frame_shape: tuple[int, ...]) -> tuple[int, int, int, int] | None:
        """读取统一等级 OCR 区域并裁剪到截图范围内（不区分平台）。"""
        try:
            frame_h = int(frame_shape[0]) if len(frame_shape) >= 1 else 0
            frame_w = int(frame_shape[1]) if len(frame_shape) >= 2 else 0
        except Exception:
            return None

        if frame_w <= 1 or frame_h <= 1:
            return None

        x1 = 0
        y1 = 0
        x2 = frame_w
        y2 = min(frame_h, int(LEVEL_OCR_TOP_BAND_HEIGHT))

        x1 = max(0, min(x1, frame_w - 1))
        y1 = max(0, min(y1, frame_h - 1))
        x2 = max(x1 + 1, min(x2, frame_w))
        y2 = max(y1 + 1, min(y2, frame_h))
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2

    @staticmethod
    def _normalize_head_profile_text(value: object) -> str:
        """规范化头部信息文本字段。"""
        return str(value or '').strip()

    def _sync_head_profile_from_ocr(self, *, level: int | None, extra_info: dict[str, object] | None) -> bool:
        """将头部 OCR 结构化信息回写到 `config.land.profile`。"""
        profile = getattr(getattr(self.engine.config, 'land', None), 'profile', None)
        if profile is None:
            return False

        data = extra_info if isinstance(extra_info, dict) else {}
        old_level = int(getattr(profile, 'level', 0))
        old_gold = self._normalize_head_profile_text(getattr(profile, 'gold', ''))
        old_coupon = self._normalize_head_profile_text(getattr(profile, 'coupon', ''))
        old_exp = self._normalize_head_profile_text(getattr(profile, 'exp', ''))

        new_level = int(level) if isinstance(level, int) and level > 0 else old_level
        if new_level <= 0:
            try:
                ocr_level = int(data.get('level', 0))
            except Exception:
                ocr_level = 0
            if ocr_level > 0:
                new_level = ocr_level
        gold_candidate = self._normalize_head_profile_text(data.get('gold', ''))
        coupon_candidate = self._normalize_head_profile_text(data.get('coupon', ''))
        exp_candidate = self._normalize_head_profile_text(data.get('exp', ''))
        new_gold = gold_candidate or old_gold
        new_coupon = coupon_candidate or old_coupon
        new_exp = exp_candidate or old_exp

        changed = old_level != new_level or old_gold != new_gold or old_coupon != new_coupon or old_exp != new_exp
        if not changed:
            return False

        profile.level = new_level
        profile.gold = new_gold
        profile.coupon = new_coupon
        profile.exp = new_exp
        logger.info(
            '等级识别: 个人信息已更新 | level={} gold={} coupon={} exp={}',
            new_level,
            new_gold or '-',
            new_coupon or '-',
            new_exp or '-',
        )
        return True

    def _sync_player_level_before_plant(self) -> int | None:
        """播种前识别主界面等级并回写配置。"""
        planting = self.engine.config.planting
        if not bool(getattr(planting, 'level_ocr_enabled', True)):
            return None

        cv_img = self.ui.device.screenshot()
        if cv_img is None:
            return None

        roi = self._get_level_ocr_region(cv_img.shape)
        if roi is None:
            logger.warning('等级识别: ROI 无效，跳过本轮识别')
            return None

        level, score, raw_text, extra_info = self.head_info_ocr.detect_head_info(
            cv_img,
            region=roi,
        )
        if extra_info:
            logger.debug(
                '等级识别: 头部信息 | roi={} tokens={} money={} id={} version={}',
                roi,
                extra_info.get('tokens', []),
                extra_info.get('money_candidates', []),
                extra_info.get('id_candidates', []),
                extra_info.get('version_candidates', []),
            )
        if level is None:
            logger.debug('等级识别: 未匹配等级 | roi={} raw={}', roi, raw_text)
            return None

        old_level = int(getattr(planting, 'player_level', 1))
        accepted_level = int(level)
        if level < old_level:
            logger.warning(
                '等级识别: OCR识别出错，忽略较低识别结果 | Lv{} -> Lv{} | roi={} score={:.3f} raw={}',
                old_level,
                level,
                roi,
                score,
                raw_text,
            )
            accepted_level = old_level

        level_changed = accepted_level > old_level
        if level_changed:
            planting.player_level = int(accepted_level)
        else:
            logger.debug('等级识别: 等级未变化 | Lv{} score={:.3f}', accepted_level, score)

        profile_changed = self._sync_head_profile_from_ocr(level=accepted_level, extra_info=extra_info)
        if not level_changed and not profile_changed:
            return accepted_level

        try:
            self.engine.config.save()
        except Exception as exc:
            logger.warning(
                '等级识别: 配置保存失败 | Lv{} -> Lv{} | profile_changed={} | error={}',
                old_level,
                accepted_level,
                profile_changed,
                exc,
            )
        else:
            config_path = str(getattr(self.engine.config, '_config_path', '') or '')
            if level_changed:
                logger.info(
                    '等级识别: 等级已更新 | Lv{} -> Lv{} | roi={} score={:.3f} raw={} config={}',
                    old_level,
                    accepted_level,
                    roi,
                    score,
                    raw_text,
                    config_path or 'default-config-path',
                )
            else:
                logger.info(
                    '等级识别: 个人信息已保存 | Lv{} | roi={} score={:.3f} raw={} config={}',
                    accepted_level,
                    roi,
                    score,
                    raw_text,
                    config_path or 'default-config-path',
                )
            self._emit_config_updated()
        return accepted_level

    def _emit_config_updated(self) -> None:
        """向主进程广播配置已更新，触发设置面板刷新。"""
        emit_now = getattr(self.engine, '_emit_config_now', None)
        if callable(emit_now):
            try:
                emit_now()
                return
            except Exception as exc:
                logger.debug('等级识别: 复用引擎配置广播失败: {}', exc)

        payload = dict(self.engine.config.model_dump())
        direct_sender = getattr(self.engine, 'emit_config_event', None)
        if callable(direct_sender):
            try:
                direct_sender(payload)
                return
            except Exception as exc:
                logger.debug('等级识别: 直连广播配置更新失败: {}', exc)

        signal = getattr(self.engine, 'config_updated', None)
        if signal is None or not hasattr(signal, 'emit'):
            return
        try:
            signal.emit(payload)
        except Exception as exc:
            logger.debug('等级识别: 广播配置更新失败: {}', exc)


# 这里延后导入，确保常量已定义，供 main_planting 直接引用。
from tasks.main_planting import TaskMainPlantingMixin


class TaskMain(
    TaskMainLevelMixin,
    TaskMainActionsMixin,
    TaskMainPlantingMixin,
    TaskMainLandMixin,
    TaskBase,
):
    """封装 `TaskMain` 任务的执行入口与步骤。"""

    def __init__(self, engine, ui, *, ocr_tool: OCRTool | None = None):
        """初始化对象并准备运行所需状态。"""
        super().__init__(engine, ui)
        self._expand_failed = False
        self._upgrade_failed = False
        self.shop_ocr = ShopItemOCR(ocr_tool=ocr_tool)
        self.seed_number_ocr = BgPatchNumberOCR(ocr_tool=ocr_tool)
        self.head_info_ocr = HeadInfoOCR(ocr_tool=ocr_tool)

    def run(self, rect: tuple[int, int, int, int]) -> TaskResult:
        """执行主流程：在 run 内按 feature 显式控制每个子方法。"""
        features = self.get_features('main')

        self.ui.ui_ensure(page_main)

        # 一键收获
        if self.has_feature(features, 'auto_harvest'):
            self._run_feature_harvest()

        self._run_feature_maintain_actions(
            enable_weed=self.has_feature(features, 'auto_weed'),
            enable_bug=self.has_feature(features, 'auto_bug'),
            enable_water=self.has_feature(features, 'auto_water'),
        )

        # 自动扩建
        if self.has_feature(features, 'auto_expand'):
            self._run_feature_expand()

        # 自动播种
        if self.has_feature(features, 'auto_plant'):
            self._sync_player_level_before_plant()
            self._run_feature_plant()

        # TODO 自动施肥
        if self.has_feature(features, 'auto_fertilize'):
            self._run_feature_fertilize()

        if self.has_feature(features, 'auto_upgrade'):
            self._run_feature_upgrade()

        return self.ok()
