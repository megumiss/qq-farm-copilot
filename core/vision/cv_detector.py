"""OpenCV 视觉检测引擎 - 模板匹配识别游戏UI元素"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from PIL import Image

from utils.template_paths import (
    normalize_template_platform,
    template_scan_roots,
)
from utils.warehouse_seed_vision import (
    WAREHOUSE_SEED_GRID_ROI as DEFAULT_WAREHOUSE_SEED_GRID_ROI,
)
from utils.warehouse_seed_vision import (
    detect_warehouse_seed_slot_boxes,
)


@dataclass
class DetectResult:
    """单个检测结果"""

    name: str  # 模板名称，如 "btn_harvest", "icon_weed"
    category: str  # 类别，如 "button", "status_icon", "crop"
    x: int  # 匹配中心x（相对于截图）
    y: int  # 匹配中心y
    w: int  # 匹配区域宽
    h: int  # 匹配区域高
    confidence: float  # 匹配置信度 0~1
    extra: dict = field(default_factory=dict)

    @property
    def center(self) -> tuple[int, int]:
        """返回中心点坐标。"""
        return self.x, self.y

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """左上角和右下角 (x1, y1, x2, y2)"""
        return (self.x - self.w // 2, self.y - self.h // 2, self.x + self.w // 2, self.y + self.h // 2)


@dataclass
class SeedWarehouseSlot:
    """仓库种子格识别结果。"""

    index: int
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    template_name: str
    confidence: float


# 模板类别定义
TEMPLATE_CATEGORIES = {
    'btn': 'button',
    'icon': 'status_icon',
    'crop': 'crop',
    'ui': 'ui_element',
    'land': 'land',
    'seed': 'seed',
}


class CVDetector:
    """基于OpenCV模板匹配的游戏UI检测器"""

    # 仓库种子页当前可见 5x4 种子格区域，供默认种子格分割使用。
    WAREHOUSE_SEED_GRID_ROI: tuple[int, int, int, int] = DEFAULT_WAREHOUSE_SEED_GRID_ROI
    # 仓库种子格底色，按 RGB 记录；OpenCV 合成模板时会转换为 BGR。
    WAREHOUSE_SEED_SLOT_BG_RGB: tuple[int, int, int] = (255, 245, 223)

    def __init__(self, templates_dir: str = 'templates', template_platform: str = 'qq'):
        """初始化对象并准备运行所需状态。"""
        self._templates_dir = templates_dir
        self._template_platform = normalize_template_platform(template_platform)
        self._templates: dict[str, list[dict]] = {}  # category -> [{name, image, mask}]
        self._templates_by_name: dict[str, dict] = {}
        self._loaded = False
        self._seed_templates_by_name: dict[str, dict] = {}
        self._seed_loaded = False
        # 详细模板探测日志默认关闭；需要时可设置环境变量 QFARM_TEMPLATE_PROBE_LOG=1
        # self._probe_log_enabled = os.environ.get("QFARM_TEMPLATE_PROBE_LOG", "0") == "1"

    def set_template_platform(self, platform: str | None):
        """设置模板平台；平台变化后会强制下次重新加载模板。"""
        normalized = normalize_template_platform(platform)
        if normalized == self._template_platform:
            return
        self._template_platform = normalized
        self._loaded = False
        self._templates = {}
        self._templates_by_name = {}
        # seed 模板不跟平台，不需要重置 seed 缓存。

    def load_seed_templates(self):
        """仅加载 seed 模板（固定目录 `templates/qq/seed`，不做平台回退）。"""
        base_root = Path(self._templates_dir)
        if not base_root.is_absolute():
            base_root = (Path(__file__).resolve().parents[2] / base_root).resolve()
        seed_root = base_root / 'qq' / 'seed'
        if not seed_root.exists():
            seed_root.mkdir(parents=True, exist_ok=True)
            logger.warning(f'种子模板目录 {seed_root} 为空，请先采集种子模板')
            self._seed_templates_by_name = {}
            self._seed_loaded = True
            return

        out: dict[str, dict] = {}
        count = 0
        for filepath in seed_root.rglob('*'):
            if not filepath.is_file():
                continue
            if filepath.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
                continue
            template = cv2.imdecode(np.fromfile(str(filepath), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if template is None:
                logger.warning(f'无法读取种子模板: {filepath}')
                continue

            name = filepath.stem
            mask = None
            if template.ndim == 3 and template.shape[2] == 4:
                alpha = template[:, :, 3]
                if not np.all(alpha == 255):
                    mask = alpha
                template = template[:, :, :3]
            elif template.ndim == 2:
                template = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)

            out[name] = {
                'name': name,
                'image': template,
                'gray': cv2.cvtColor(template, cv2.COLOR_BGR2GRAY),
                'mask': mask,
                'category': 'seed',
            }
            count += 1
        self._seed_templates_by_name = out
        self._seed_loaded = True
        logger.info(f'已加载 {count} 个种子模板（固定目录，不按平台切换）')

    @staticmethod
    def _alpha_bbox(mask: np.ndarray | None) -> tuple[int, int, int, int] | None:
        """返回 alpha 非透明区域包围盒。"""
        if mask is None:
            return None
        ys, xs = np.where(mask > 8)
        if xs.size == 0 or ys.size == 0:
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1

    @classmethod
    def _warehouse_seed_background_bgr(cls) -> np.ndarray:
        """返回仓库种子格固定背景色，格式为 OpenCV BGR。"""
        red, green, blue = cls.WAREHOUSE_SEED_SLOT_BG_RGB
        return np.array((blue, green, red), dtype=np.float32)

    def _make_crop_composite_seed_template(
        self,
        tpl: dict,
        *,
        scale: float,
        bg: np.ndarray,
    ) -> tuple[np.ndarray, int, int] | None:
        """裁剪透明边缘、缩放并按格子背景合成种子模板。"""
        image = tpl['image']
        mask = tpl['mask']
        bbox = self._alpha_bbox(mask)
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            image = image[y1:y2, x1:x2]
            mask = mask[y1:y2, x1:x2]

        h, w = image.shape[:2]
        new_w = int(w * float(scale))
        new_h = int(h * float(scale))
        if new_w < 10 or new_h < 10:
            return None

        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        resized_mask = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST) if mask is not None else None
        if resized_mask is not None:
            alpha = (resized_mask.astype(np.float32) / 255.0)[:, :, None]
            resized = (resized.astype(np.float32) * alpha + bg.reshape(1, 1, 3) * (1.0 - alpha)).astype(np.uint8)
        return resized, new_w, new_h

    def _match_warehouse_seed_slot(
        self,
        slot: np.ndarray,
        slot_origin: tuple[int, int],
        *,
        scale: float,
        template_name: str | None = None,
    ) -> tuple[float, str, int, int] | None:
        """匹配单个仓库种子格，返回最高分模板。"""
        if slot is None or slot.size == 0:
            return None
        templates = (
            [self._seed_templates_by_name[template_name]]
            if template_name and template_name in self._seed_templates_by_name
            else list(self._seed_templates_by_name.values())
        )
        if not templates:
            return None

        bg = self._warehouse_seed_background_bgr()
        origin_x, origin_y = slot_origin
        slot_h, slot_w = slot.shape[:2]
        best: tuple[float, str, int, int] | None = None

        for tpl in templates:
            made = self._make_crop_composite_seed_template(tpl, scale=float(scale), bg=bg)
            if made is None:
                continue
            template_image, template_w, template_h = made
            if template_w >= slot_w or template_h >= slot_h:
                continue

            result = cv2.matchTemplate(slot, template_image, cv2.TM_CCOEFF_NORMED)
            result = np.where(np.isfinite(result), result, -1.0)
            h, w = result.shape[:2]
            yy, xx = np.indices((h, w))
            center_x = xx + template_w / 2.0
            center_y = yy + template_h / 2.0
            valid = (center_x >= 25) & (center_x <= 70) & (center_y >= 25) & (center_y <= 80)
            result = np.where(valid, result, -1.0)

            _, max_score, _, max_loc = cv2.minMaxLoc(result)
            x = origin_x + int(max_loc[0]) + template_w // 2
            y = origin_y + int(max_loc[1]) + template_h // 2
            current = (float(max_score), str(tpl['name']), int(x), int(y))
            if best is None or current[0] > best[0]:
                best = current

        return best

    def detect_seed_template_in_warehouse(
        self,
        screenshot: np.ndarray,
        seed_id: int,
        *,
        threshold: float,
        scale: float,
        boxes: list[tuple[int, int, int, int]] | None = None,
    ) -> list[SeedWarehouseSlot]:
        """在仓库种子格中按 seed_id 识别目标种子，按分数倒序返回。"""
        if not self._seed_loaded:
            self.load_seed_templates()

        template_name = f'seed_{int(seed_id)}'
        if template_name not in self._seed_templates_by_name:
            logger.warning('仓库种子匹配: 模板不存在 | 模板={}', template_name)
            return []

        seed_boxes = boxes if boxes is not None else detect_warehouse_seed_slot_boxes(screenshot)[:20]
        results: list[SeedWarehouseSlot] = []
        for idx, (x1, y1, x2, y2) in enumerate(seed_boxes, 1):
            slot = screenshot[y1:y2, x1:x2]
            matched = self._match_warehouse_seed_slot(
                slot,
                (x1, y1),
                scale=float(scale),
                template_name=template_name,
            )
            if matched is None:
                continue
            score, name, cx, cy = matched
            if score < float(threshold):
                continue
            results.append(
                SeedWarehouseSlot(
                    index=int(idx),
                    bbox=(int(x1), int(y1), int(x2), int(y2)),
                    center=(int(cx), int(cy)),
                    template_name=str(name),
                    confidence=float(score),
                )
            )
        results.sort(key=lambda item: item.confidence, reverse=True)
        return results

    def _iter_template_files(self, root: Path):
        """遍历模板文件（忽略 `__pycache__` 目录）。"""
        ignored_top_dirs = {'__pycache__'}
        root_str = str(root)
        for walk_root, dirs, files in os.walk(root_str):
            rel = os.path.relpath(walk_root, root_str)
            if rel == '.':
                dirs[:] = [d for d in dirs if d.lower() not in ignored_top_dirs]
            else:
                top_dir = rel.split(os.sep)[0].lower()
                if top_dir in ignored_top_dirs:
                    continue
                dirs[:] = [d for d in dirs if d.lower() not in ignored_top_dirs]

            for filename in files:
                if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    yield Path(walk_root) / filename

    def load_templates(self):
        """加载所有模板图片（按平台优先，缺失回退 QQ）。"""
        selected_platform = normalize_template_platform(self._template_platform)
        roots = template_scan_roots(selected_platform, self._templates_dir)
        if not roots:
            logger.warning(f'模板目录 {self._templates_dir} 为空，请先采集模板')
            return
        if not any(root.exists() for root in roots):
            os.makedirs(str(roots[0]), exist_ok=True)
            logger.warning(f'模板目录 {roots[0]} 为空，请先采集模板')
            self._templates = {}
            self._templates_by_name = {}
            self._loaded = True
            return

        by_name: dict[str, dict] = {}
        for root in roots:
            if not root.exists():
                continue
            for filepath in self._iter_template_files(root):
                filename = filepath.name
                # cv2.imread 不支持中文路径，用 numpy 中转
                template = cv2.imdecode(np.fromfile(str(filepath), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if template is None:
                    logger.warning(f'无法读取模板: {filepath}')
                    continue

                name = os.path.splitext(filename)[0]
                # 从文件名前缀判断类别: btn_harvest.png -> button
                prefix = name.split('_')[0]
                category = TEMPLATE_CATEGORIES.get(prefix, 'unknown')

                # 处理带alpha通道的模板（用于mask匹配）
                mask = None
                if template.ndim == 3 and template.shape[2] == 4:
                    alpha = template[:, :, 3]
                    # alpha 全不透明时无需 mask；直接用 mask 会让 TM_CCOEFF_NORMED
                    # 在部分 OpenCV 环境产生 NaN/Inf，导致误命中。
                    if not np.all(alpha == 255):
                        mask = alpha
                    template = template[:, :, :3]
                elif template.ndim == 2:
                    template = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)

                by_name[name] = {
                    'name': name,
                    'image': template,
                    'gray': cv2.cvtColor(template, cv2.COLOR_BGR2GRAY),
                    'mask': mask,
                    'category': category,
                }

        self._templates = {}
        self._templates_by_name = {}
        for name in sorted(by_name.keys()):
            payload = by_name[name]
            category = payload['category']
            if category not in self._templates:
                self._templates[category] = []
            self._templates[category].append(payload)
            self._templates_by_name[name] = payload

        self._loaded = True
        logger.info(
            f'已加载 {len(self._templates_by_name)} 个模板，分 {len(self._templates)} 个类别，平台={selected_platform}'
        )

    def detect_all(self, screenshot: np.ndarray, threshold: float = 0.8) -> list[DetectResult]:
        """在截图中检测所有已加载的模板"""
        if not self._loaded:
            self.load_templates()

        results = []
        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        for category, templates in self._templates.items():
            for tpl in templates:
                matches, best_score = self._match_template_with_best(screenshot, gray_screen, tpl, threshold)
                self._log_template_probe(
                    template_name=tpl['name'],
                    threshold=threshold,
                    best_score=best_score,
                    hit_count=len(matches),
                )
                results.extend(matches)

        # 去重（NMS - 非极大值抑制）
        results = self._nms(results, iou_threshold=0.5)
        # 按置信度排序
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    def detect_category(self, screenshot: np.ndarray, category: str, threshold: float = 0.8) -> list[DetectResult]:
        """只检测指定类别的模板"""
        if not self._loaded:
            self.load_templates()

        results = []
        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        templates = self._templates.get(category, [])
        for tpl in templates:
            matches, best_score = self._match_template_with_best(screenshot, gray_screen, tpl, threshold)
            self._log_template_probe(
                template_name=tpl['name'],
                threshold=threshold,
                best_score=best_score,
                hit_count=len(matches),
            )
            results.extend(matches)

        results = self._nms(results, iou_threshold=0.5)
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    def detect_single_template(self, screenshot: np.ndarray, name: str, threshold: float = 0.7) -> list[DetectResult]:
        """只检测指定名称的单个模板"""
        if not self._loaded:
            self.load_templates()

        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        for category, templates in self._templates.items():
            for tpl in templates:
                if tpl['name'] == name:
                    results, best_score = self._match_template_with_best(screenshot, gray_screen, tpl, threshold)
                    results = self._nms(results, iou_threshold=0.5)
                    results.sort(key=lambda r: r.confidence, reverse=True)
                    self._log_template_probe(
                        template_name=name,
                        threshold=threshold,
                        best_score=best_score,
                        hit_count=len(results),
                    )
                    return results
        self._log_template_probe(
            template_name=name,
            threshold=threshold,
            best_score=0.0,
            hit_count=0,
        )
        return []

    def detect_templates(
        self,
        screenshot: np.ndarray,
        template_names: list[str],
        default_threshold: float = 0.8,
        thresholds: dict[str, float] | None = None,
        roi_map: dict[str, tuple[int, int, int, int]] | None = None,
    ) -> list[DetectResult]:
        """按模板名执行精确识别，避免全量模板扫描。"""
        if not self._loaded:
            self.load_templates()

        if not template_names:
            return []

        # 预先生成灰度图，减少单模板匹配时的重复转换开销。
        results: list[DetectResult] = []
        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        seen: set[str] = set()
        # 按调用方传入顺序逐个模板匹配（重复模板会被去重）。
        for name in template_names:
            name = str(name or '').strip()
            if not name or name in seen:
                continue
            seen.add(name)
            tpl = self._templates_by_name.get(name)
            if tpl is None:
                self._log_template_probe(
                    template_name=name,
                    threshold=default_threshold,
                    best_score=0.0,
                    hit_count=0,
                )
                continue

            threshold = float(thresholds.get(name, default_threshold) if thresholds else default_threshold)
            roi = roi_map.get(name) if roi_map else None
            if roi is not None:
                # ROI 匹配：在局部区域搜索，再将命中坐标映射回全图。
                x1, y1, x2, y2 = [int(v) for v in roi]
                sh, sw = screenshot.shape[:2]
                x1 = max(0, min(x1, sw - 1))
                y1 = max(0, min(y1, sh - 1))
                x2 = max(x1 + 1, min(x2, sw))
                y2 = max(y1 + 1, min(y2, sh))
                if x2 <= x1 or y2 <= y1:
                    self._log_template_probe(
                        template_name=name,
                        threshold=threshold,
                        best_score=0.0,
                        hit_count=0,
                    )
                    continue
                roi_img = screenshot[y1:y2, x1:x2]
                roi_gray = gray_screen[y1:y2, x1:x2]
                matches, best_score = self._match_template_with_best(roi_img, roi_gray, tpl, threshold)
                for m in matches:
                    m.x += x1
                    m.y += y1
                    m.extra['roi'] = (x1, y1, x2, y2)
            else:
                # 全图匹配：直接在整张截图搜索模板。
                matches, best_score = self._match_template_with_best(screenshot, gray_screen, tpl, threshold)
            self._log_template_probe(
                template_name=name,
                threshold=threshold,
                best_score=best_score,
                hit_count=len(matches),
            )
            results.extend(matches)

        # 汇总后做 NMS 去重，返回稳定结果集合。
        results = self._nms(results, iou_threshold=0.5)
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    def detect_seed_template(
        self,
        screenshot: np.ndarray,
        crop_name_or_template: str,
        threshold: float = 0.6,
        roi: tuple[int, int, int, int] | None = None,
    ) -> list[DetectResult]:
        """执行种子模板专用识别，保持既有 Seed 匹配策略不变。

        关键约束：
        - 仅在 Seed ROI 内匹配，避免全屏误检；
        - 优先 0.75 缩放，只有首轮无命中才回退 0.70/0.80；
        - 模板含 alpha 时使用 mask，插值策略保持 NIKKE 对齐。
        """
        if not self._seed_loaded:
            self.load_seed_templates()

        # 支持传入“作物名 / seed_id / 完整模板名（seed_xxx）”。
        crop_name_or_template = str(crop_name_or_template or '').strip()
        if crop_name_or_template.startswith('seed_'):
            template_name = crop_name_or_template
        elif crop_name_or_template.isdigit():
            template_name = f'seed_{crop_name_or_template}'
        else:
            template_name = self._seed_template_by_crop_name.get(crop_name_or_template, f'seed_{crop_name_or_template}')

        tpl = self._seed_templates_by_name.get(template_name)

        if tpl is None:
            self._log_template_probe(
                template_name=template_name,
                threshold=threshold,
                best_score=0.0,
                hit_count=0,
            )
            return []

        # 先将 ROI 夹紧到截图边界，避免越界切片。
        h, w = screenshot.shape[:2]
        x1, y1, x2, y2 = roi if roi is not None else self.SEED_DETECT_ROI
        x1 = max(0, min(int(x1), w - 1))
        y1 = max(0, min(int(y1), h - 1))
        x2 = max(x1 + 1, min(int(x2), w))
        y2 = max(y1 + 1, min(int(y2), h))
        roi_img = screenshot[y1:y2, x1:x2]
        if roi_img.size == 0:
            self._log_template_probe(
                template_name=template_name,
                threshold=threshold,
                best_score=0.0,
                hit_count=0,
            )
            return []

        def _run_scales(scales: list[float]) -> tuple[list[DetectResult], float]:
            """在给定缩放列表上匹配并返回命中结果与最佳分数。"""
            results: list[DetectResult] = []
            best_score = 0.0
            tpl_img = tpl['image']
            tpl_mask = tpl['mask']
            th, tw = tpl_img.shape[:2]
            rh, rw = roi_img.shape[:2]

            for scale in scales:
                new_w = int(tw * scale)
                new_h = int(th * scale)
                # 跳过过小模板或超过 ROI 的模板尺寸。
                if new_w < 10 or new_h < 10 or new_w >= rw or new_h >= rh:
                    continue

                # Seed 识别固定插值：模板 AREA，mask NEAREST（与 NIKKE 一致）。
                resized_tpl = cv2.resize(tpl_img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                resized_mask = None
                if tpl_mask is not None:
                    resized_mask = cv2.resize(tpl_mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

                if resized_mask is not None:
                    mask3 = cv2.merge([resized_mask] * 3)
                    match_result = cv2.matchTemplate(roi_img, resized_tpl, cv2.TM_CCOEFF_NORMED, mask=mask3)
                else:
                    match_result = cv2.matchTemplate(roi_img, resized_tpl, cv2.TM_CCOEFF_NORMED)

                finite = np.isfinite(match_result)
                if not finite.all():
                    # NaN/Inf 统一置为 -1，防止被阈值命中。
                    match_result = np.where(finite, match_result, -1.0)
                    finite = np.isfinite(match_result)

                if finite.any():
                    scale_best = float(match_result[finite].max())
                    if scale_best > best_score:
                        best_score = scale_best

                locations = np.where(match_result >= threshold)
                for pt_y, pt_x in zip(*locations):
                    confidence = float(match_result[pt_y, pt_x])
                    # ROI 坐标回映射到整图坐标系，供点击流程直接使用。
                    center_x = x1 + pt_x + new_w // 2
                    center_y = y1 + pt_y + new_h // 2
                    results.append(
                        DetectResult(
                            name=tpl['name'],
                            category=tpl['category'],
                            x=center_x,
                            y=center_y,
                            w=new_w,
                            h=new_h,
                            confidence=confidence,
                            extra={'scale': scale, 'roi': (x1, y1, x2, y2)},
                        )
                    )

            results = self._nms(results, iou_threshold=0.5)
            results.sort(key=lambda r: r.confidence, reverse=True)
            return results, best_score

        # 优先 0.75
        primary_results, primary_best = _run_scales([0.75])
        if primary_results:
            self._log_template_probe(
                template_name=template_name,
                threshold=threshold,
                best_score=primary_best,
                hit_count=len(primary_results),
            )
            return primary_results

        # 仅当 0.75 无命中时，回退到 0.70 / 0.80
        fallback_results, fallback_best = _run_scales([0.70, 0.80])
        self._log_template_probe(
            template_name=template_name,
            threshold=threshold,
            best_score=max(primary_best, fallback_best),
            hit_count=len(fallback_results),
        )
        return fallback_results

    def _log_template_probe(self, template_name: str, threshold: float, best_score: float, hit_count: int) -> None:
        # if not self._probe_log_enabled:
        #     return
        """输出模板识别调试日志。"""
        logger.debug(
            '模板识别: 模板={}, 阈值={:.3f}, 最大分数={:.3f}, 命中数={}',
            template_name,
            threshold,
            best_score,
            int(hit_count),
        )

    def _match_template(
        self, screenshot: np.ndarray, gray_screen: np.ndarray, tpl: dict, threshold: float
    ) -> list[DetectResult]:
        """对单个模板执行多尺度匹配"""
        results, _ = self._match_template_with_best(screenshot, gray_screen, tpl, threshold)
        return results

    def _match_template_with_best(
        self, screenshot: np.ndarray, gray_screen: np.ndarray, tpl: dict, threshold: float
    ) -> tuple[list[DetectResult], float]:
        """执行单模板多尺度匹配，并返回命中列表与尺度内最高分。"""
        results = []
        best_score = 0.0
        tpl_img = tpl['image']
        tpl_gray_src = tpl['gray']
        tpl_mask = tpl['mask']
        th, tw = tpl_img.shape[:2]
        sh, sw = screenshot.shape[:2]

        category = tpl.get('category', 'unknown')
        template_name = str(tpl.get('name', '') or '')
        scales = [1.0, 0.9, 0.8, 1.1, 1.2]
        min_tpl_side = 4 if template_name.startswith('icon_num_') else 10

        # 控制单模板候选点数量，避免噪声模板在全屏产生过多候选拖慢流程。
        max_hits = 64 if category == 'land' else 8

        for scale in scales:
            new_w = int(tw * scale)
            new_h = int(th * scale)
            # 尺寸非法（过小/超界）直接跳过该尺度。
            if new_w >= sw or new_h >= sh or new_w < min_tpl_side or new_h < min_tpl_side:
                continue

            resized_mask = None
            if tpl_mask is not None:
                resized_mask = cv2.resize(tpl_mask, (new_w, new_h))

            # 灰度模板在加载时已缓存，避免每次匹配重复转灰度。
            gray_tpl = cv2.resize(tpl_gray_src, (new_w, new_h))

            if resized_mask is not None:
                match_result = cv2.matchTemplate(gray_screen, gray_tpl, cv2.TM_CCOEFF_NORMED, mask=resized_mask)
            else:
                match_result = cv2.matchTemplate(gray_screen, gray_tpl, cv2.TM_CCOEFF_NORMED)

            finite = np.isfinite(match_result)
            if not finite.all():
                # 屏蔽 NaN/Inf：避免被阈值筛选命中并污染置信度。
                match_result = np.where(finite, match_result, -1.0)
                finite = np.isfinite(match_result)

            if finite.any():
                scale_best = float(match_result[finite].max())
                if scale_best > best_score:
                    best_score = scale_best

            # 找到所有超过阈值的匹配位置
            locations = np.where(match_result >= threshold)
            if locations[0].size > max_hits:
                # 候选过多时只保留分数最高的一批，降低后续 NMS 负担。
                scores = match_result[locations]
                top_idx = np.argpartition(scores, -max_hits)[-max_hits:]
                pt_ys = locations[0][top_idx]
                pt_xs = locations[1][top_idx]
            else:
                pt_ys, pt_xs = locations

            for pt_y, pt_x in zip(pt_ys, pt_xs):
                confidence = float(match_result[pt_y, pt_x])
                center_x = pt_x + new_w // 2
                center_y = pt_y + new_h // 2

                results.append(
                    DetectResult(
                        name=tpl['name'],
                        category=tpl['category'],
                        x=center_x,
                        y=center_y,
                        w=new_w,
                        h=new_h,
                        confidence=confidence,
                    )
                )

            # 如果在原始尺度找到了高置信度匹配，跳过其他尺度
            if scale == 1.0 and any(r.confidence > 0.95 for r in results):
                break

        return results, best_score

    @staticmethod
    def _nms(results: list[DetectResult], iou_threshold: float = 0.5) -> list[DetectResult]:
        """非极大值抑制，去除重叠检测"""
        if len(results) <= 1:
            return results

        # 按置信度降序排列
        results.sort(key=lambda r: r.confidence, reverse=True)
        keep = []

        while results:
            best = results.pop(0)
            keep.append(best)
            remaining = []
            for r in results:
                if _iou(best.bbox, r.bbox) < iou_threshold:
                    remaining.append(r)
            results = remaining

        return keep

    @staticmethod
    def pil_to_cv2(image: Image.Image) -> np.ndarray:
        """PIL Image 转 OpenCV 格式"""
        rgb = np.array(image.convert('RGB'))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def draw_results(self, screenshot: np.ndarray, results: list[DetectResult]) -> np.ndarray:
        """在截图上绘制检测结果（用于调试）"""
        output = screenshot.copy()
        colors = {
            'button': (0, 255, 0),
            'status_icon': (0, 0, 255),
            'crop': (255, 165, 0),
            'ui_element': (255, 255, 0),
            'land': (128, 128, 128),
            'seed': (255, 0, 255),
            'unknown': (255, 255, 255),
        }
        for r in results:
            color = colors.get(r.category, (255, 255, 255))
            x1, y1, x2, y2 = r.bbox
            cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
            label = f'{r.name} {r.confidence:.2f}'
            cv2.putText(output, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        return output


def _iou(box1: tuple, box2: tuple) -> float:
    """计算两个框的IoU"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0
