"""OpenCV 视觉检测引擎 - 模板匹配识别游戏UI元素"""

import os
from dataclasses import dataclass, field

import cv2
import numpy as np
from loguru import logger
from PIL import Image


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

    SEED_DETECT_ROI: tuple[int, int, int, int] = (40, 500, 490, 920)

    def __init__(self, templates_dir: str = 'templates'):
        """初始化对象并准备运行所需状态。"""
        self._templates_dir = templates_dir
        self._templates: dict[str, list[dict]] = {}  # category -> [{name, image, mask}]
        self._templates_by_name: dict[str, dict] = {}
        self._loaded = False
        # 详细模板探测日志默认关闭；需要时可设置环境变量 QFARM_TEMPLATE_PROBE_LOG=1
        # self._probe_log_enabled = os.environ.get("QFARM_TEMPLATE_PROBE_LOG", "0") == "1"

    def load_templates(self):
        """加载所有模板图片"""
        if not os.path.exists(self._templates_dir):
            os.makedirs(self._templates_dir, exist_ok=True)
            logger.warning(f'模板目录 {self._templates_dir} 为空，请先采集模板')
            return

        self._templates = {}
        self._templates_by_name = {}
        count = 0
        ignored_top_dirs = {'__pycache__'}
        for root, dirs, files in os.walk(self._templates_dir):
            rel = os.path.relpath(root, self._templates_dir)
            if rel == '.':
                dirs[:] = [d for d in dirs if d.lower() not in ignored_top_dirs]
            else:
                top_dir = rel.split(os.sep)[0].lower()
                if top_dir in ignored_top_dirs:
                    continue
                dirs[:] = [d for d in dirs if d.lower() not in ignored_top_dirs]

            for filename in files:
                if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    continue

                filepath = os.path.join(root, filename)
                # cv2.imread 不支持中文路径，用 numpy 中转
                template = cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
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

                if category not in self._templates:
                    self._templates[category] = []

                tpl_payload = {
                    'name': name,
                    'image': template,
                    'gray': cv2.cvtColor(template, cv2.COLOR_BGR2GRAY),
                    'mask': mask,
                    'category': category,
                }
                self._templates[category].append(tpl_payload)
                self._templates_by_name[name] = tpl_payload
                count += 1

        self._loaded = True
        logger.info(f'已加载 {count} 个模板，分 {len(self._templates)} 个类别')

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
        if not self._loaded:
            self.load_templates()

        # 支持传入“作物名”或“完整模板名（seed_xxx）”两种形式。
        if crop_name_or_template.startswith('seed_'):
            template_name = crop_name_or_template
        else:
            template_name = f'seed_{crop_name_or_template}'

        tpl = None
        for templates in self._templates.values():
            for item in templates:
                if item['name'] == template_name:
                    tpl = item
                    break
            if tpl is not None:
                break

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
        scales = [1.0, 0.9, 0.8, 1.1, 1.2]

        # 控制单模板候选点数量，避免噪声模板在全屏产生过多候选拖慢流程。
        max_hits = 64 if category == 'land' else 8

        for scale in scales:
            new_w = int(tw * scale)
            new_h = int(th * scale)
            # 尺寸非法（过小/超界）直接跳过该尺度。
            if new_w >= sw or new_h >= sh or new_w < 10 or new_h < 10:
                continue

            resized_tpl = cv2.resize(tpl_img, (new_w, new_h))
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
