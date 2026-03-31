"""OpenCV 视觉检测引擎 - 模板匹配识别游戏UI元素"""
import os
import cv2
import numpy as np
from dataclasses import dataclass, field
from loguru import logger
from PIL import Image


@dataclass
class DetectResult:
    """单个检测结果"""
    name: str           # 模板名称，如 "btn_harvest", "icon_weed"
    category: str       # 类别，如 "button", "status_icon", "crop"
    x: int              # 匹配中心x（相对于截图）
    y: int              # 匹配中心y
    w: int              # 匹配区域宽
    h: int              # 匹配区域高
    confidence: float   # 匹配置信度 0~1
    extra: dict = field(default_factory=dict)

    @property
    def center(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """左上角和右下角 (x1, y1, x2, y2)"""
        return (self.x - self.w // 2, self.y - self.h // 2,
                self.x + self.w // 2, self.y + self.h // 2)


# 模板类别定义
TEMPLATE_CATEGORIES = {
    "btn": "button",
    "icon": "status_icon",
    "crop": "crop",
    "ui": "ui_element",
    "land": "land",
    "seed": "seed",
    "shop": "shop",
}


class CVDetector:
    """基于OpenCV模板匹配的游戏UI检测器"""

    def __init__(self, templates_dir: str = "templates"):
        self._templates_dir = templates_dir
        self._templates: dict[str, list[dict]] = {}  # category -> [{name, image, mask}]
        self._loaded = False

    def load_templates(self):
        """加载所有模板图片"""
        if not os.path.exists(self._templates_dir):
            os.makedirs(self._templates_dir, exist_ok=True)
            logger.warning(f"模板目录 {self._templates_dir} 为空，请先采集模板")
            return

        count = 0
        for filename in os.listdir(self._templates_dir):
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue

            filepath = os.path.join(self._templates_dir, filename)
            # cv2.imread 不支持中文路径，用 numpy 中转
            template = cv2.imdecode(
                np.fromfile(filepath, dtype=np.uint8), cv2.IMREAD_UNCHANGED
            )
            if template is None:
                logger.warning(f"无法读取模板: {filename}")
                continue

            name = os.path.splitext(filename)[0]
            # 从文件名前缀判断类别: btn_harvest.png -> button
            prefix = name.split("_")[0]
            category = TEMPLATE_CATEGORIES.get(prefix, "unknown")

            # 处理带alpha通道的模板（用于mask匹配）
            mask = None
            if template.shape[2] == 4:
                mask = template[:, :, 3]
                template = template[:, :, :3]

            if category not in self._templates:
                self._templates[category] = []

            self._templates[category].append({
                "name": name,
                "image": template,
                "mask": mask,
                "category": category,
            })
            count += 1

        self._loaded = True
        logger.info(f"已加载 {count} 个模板，分 {len(self._templates)} 个类别")

    def detect_all(self, screenshot: np.ndarray,
                   threshold: float = 0.8) -> list[DetectResult]:
        """在截图中检测所有已加载的模板"""
        if not self._loaded:
            self.load_templates()

        results = []
        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        for category, templates in self._templates.items():
            for tpl in templates:
                matches = self._match_template(
                    screenshot, gray_screen, tpl, threshold
                )
                results.extend(matches)

        # 去重（NMS - 非极大值抑制）
        results = self._nms(results, iou_threshold=0.5)
        # 按置信度排序
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    def detect_category(self, screenshot: np.ndarray,
                        category: str,
                        threshold: float = 0.8) -> list[DetectResult]:
        """只检测指定类别的模板"""
        if not self._loaded:
            self.load_templates()

        results = []
        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        templates = self._templates.get(category, [])
        for tpl in templates:
            matches = self._match_template(
                screenshot, gray_screen, tpl, threshold
            )
            results.extend(matches)

        results = self._nms(results, iou_threshold=0.5)
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    def detect_single_template(self, screenshot: np.ndarray,
                                name: str,
                                threshold: float = 0.7) -> list[DetectResult]:
        """只检测指定名称的单个模板"""
        if not self._loaded:
            self.load_templates()

        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        for category, templates in self._templates.items():
            for tpl in templates:
                if tpl["name"] == name:
                    results, best_score = self._match_template_with_best(
                        screenshot, gray_screen, tpl, threshold
                    )
                    results = self._nms(results, iou_threshold=0.5)
                    results.sort(key=lambda r: r.confidence, reverse=True)
                    top_score = results[0].confidence if results else best_score
                    logger.debug(
                        f"模板检测: name={name}, threshold={threshold:.3f}, "
                        f"score={top_score:.3f}, hit={bool(results)}"
                    )
                    return results
        logger.debug(
            f"模板检测: name={name}, threshold={threshold:.3f}, score=0.000, hit=False"
        )
        return []

    def _match_template(self, screenshot: np.ndarray,
                        gray_screen: np.ndarray,
                        tpl: dict,
                        threshold: float) -> list[DetectResult]:
        """对单个模板执行多尺度匹配"""
        results, _ = self._match_template_with_best(
            screenshot, gray_screen, tpl, threshold
        )
        return results

    def _match_template_with_best(self, screenshot: np.ndarray,
                                  gray_screen: np.ndarray,
                                  tpl: dict,
                                  threshold: float) -> tuple[list[DetectResult], float]:
        """对单个模板执行多尺度匹配，并返回最佳分数（不受阈值限制）。"""
        results = []
        best_score = 0.0
        tpl_img = tpl["image"]
        tpl_mask = tpl["mask"]
        th, tw = tpl_img.shape[:2]
        sh, sw = screenshot.shape[:2]

        # 多尺度匹配：应对不同分辨率
        scales = [1.0, 0.9, 0.8, 1.1, 1.2]

        for scale in scales:
            new_w = int(tw * scale)
            new_h = int(th * scale)
            if new_w >= sw or new_h >= sh or new_w < 10 or new_h < 10:
                continue

            resized_tpl = cv2.resize(tpl_img, (new_w, new_h))
            resized_mask = None
            if tpl_mask is not None:
                resized_mask = cv2.resize(tpl_mask, (new_w, new_h))

            # 灰度匹配（更快）
            gray_tpl = cv2.cvtColor(resized_tpl, cv2.COLOR_BGR2GRAY)

            if resized_mask is not None:
                match_result = cv2.matchTemplate(
                    gray_screen, gray_tpl, cv2.TM_CCOEFF_NORMED, mask=resized_mask
                )
            else:
                match_result = cv2.matchTemplate(
                    gray_screen, gray_tpl, cv2.TM_CCOEFF_NORMED
                )

            finite = np.isfinite(match_result)
            if finite.any():
                scale_best = float(match_result[finite].max())
                if scale_best > best_score:
                    best_score = scale_best

            # 找到所有超过阈值的匹配位置
            locations = np.where(match_result >= threshold)
            for pt_y, pt_x in zip(*locations):
                confidence = float(match_result[pt_y, pt_x])
                center_x = pt_x + new_w // 2
                center_y = pt_y + new_h // 2

                results.append(DetectResult(
                    name=tpl["name"],
                    category=tpl["category"],
                    x=center_x,
                    y=center_y,
                    w=new_w,
                    h=new_h,
                    confidence=confidence,
                ))

            # 如果在原始尺度找到了高置信度匹配，跳过其他尺度
            if scale == 1.0 and any(r.confidence > 0.95 for r in results):
                break

        return results, best_score

    @staticmethod
    def _nms(results: list[DetectResult],
             iou_threshold: float = 0.5) -> list[DetectResult]:
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
        rgb = np.array(image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def draw_results(self, screenshot: np.ndarray,
                     results: list[DetectResult]) -> np.ndarray:
        """在截图上绘制检测结果（用于调试）"""
        output = screenshot.copy()
        colors = {
            "button": (0, 255, 0),
            "status_icon": (0, 0, 255),
            "crop": (255, 165, 0),
            "ui_element": (255, 255, 0),
            "land": (128, 128, 128),
            "seed": (255, 0, 255),
            "unknown": (255, 255, 255),
        }
        for r in results:
            color = colors.get(r.category, (255, 255, 255))
            x1, y1, x2, y2 = r.bbox
            cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
            label = f"{r.name} {r.confidence:.2f}"
            cv2.putText(output, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
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
