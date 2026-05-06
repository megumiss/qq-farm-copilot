"""用 crop_composite/bgr/ccoeff 测试仓库种子截图。

默认读取仓库根目录最新的 PNG 截图，按仓库 20 个种子格检测并输出种子名、分数。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.vision.cv_detector import CVDetector


DEFAULT_SCALE = 0.6
DEFAULT_THRESHOLD = 0.8
SLOTS = [
    (31, 186, 119, 286),
    (129, 186, 217, 286),
    (226, 186, 314, 286),
    (324, 186, 412, 286),
    (421, 186, 509, 286),
    (31, 296, 119, 396),
    (129, 296, 217, 396),
    (226, 296, 314, 396),
    (324, 296, 412, 396),
    (421, 296, 509, 396),
    (31, 406, 119, 506),
    (129, 406, 217, 506),
    (226, 406, 314, 506),
    (324, 406, 412, 506),
    (421, 406, 509, 506),
    (31, 516, 119, 616),
    (129, 516, 217, 616),
    (226, 516, 314, 616),
    (324, 516, 412, 616),
    (421, 516, 509, 616),
]


def _latest_root_png() -> Path:
    images = sorted(ROOT.glob('*.png'), key=lambda item: item.stat().st_mtime, reverse=True)
    if not images:
        raise FileNotFoundError('仓库根目录没有 PNG 截图')
    return images[0]


def _read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'无法读取截图: {path}')
    return image


def _alpha_bbox(mask: np.ndarray | None) -> tuple[int, int, int, int] | None:
    if mask is None:
        return None
    ys, xs = np.where(mask > 8)
    if xs.size == 0 or ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _slot_bg(slot: np.ndarray) -> np.ndarray:
    patches = np.concatenate(
        [
            slot[:12, :12].reshape(-1, 3),
            slot[:12, -12:].reshape(-1, 3),
            slot[-12:, :12].reshape(-1, 3),
            slot[-12:, -12:].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(patches, axis=0).astype(np.float32)


def _make_crop_composite_template(tpl: dict, scale: float, bg: np.ndarray) -> tuple[np.ndarray, int, int] | None:
    image = tpl['image']
    mask = tpl['mask']
    bbox = _alpha_bbox(mask)
    if bbox is not None:
        x1, y1, x2, y2 = bbox
        image = image[y1:y2, x1:x2]
        mask = mask[y1:y2, x1:x2]

    h, w = image.shape[:2]
    new_w = int(w * scale)
    new_h = int(h * scale)
    if new_w < 10 or new_h < 10:
        return None

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    resized_mask = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST) if mask is not None else None
    if resized_mask is not None:
        alpha = (resized_mask.astype(np.float32) / 255.0)[:, :, None]
        resized = (resized.astype(np.float32) * alpha + bg.reshape(1, 1, 3) * (1.0 - alpha)).astype(np.uint8)
    return resized, new_w, new_h


def _load_seed_name_map() -> dict[str, str]:
    plants_path = ROOT / 'configs' / 'plants.json'
    data = json.loads(plants_path.read_text(encoding='utf-8'))
    out: dict[str, str] = {}
    for item in data:
        name = str(item.get('name') or '').strip()
        seed_id = item.get('seed_id')
        if not name or seed_id is None:
            continue
        try:
            seed_id_int = int(seed_id)
        except (TypeError, ValueError):
            continue
        out[f'seed_crop{seed_id_int % 1000}'] = name
    return out


def _display_name(template_name: str, seed_name_map: dict[str, str]) -> str:
    if template_name.startswith('seed_crop'):
        return seed_name_map.get(template_name, template_name)
    if template_name.startswith('seed_'):
        return template_name[5:]
    return template_name


def _match_slot(
    slot: np.ndarray,
    slot_origin: tuple[int, int],
    templates: dict[str, dict],
    scale: float,
) -> list[tuple[float, str, int, int]]:
    bg = _slot_bg(slot)
    scored: list[tuple[float, str, int, int]] = []
    origin_x, origin_y = slot_origin
    slot_h, slot_w = slot.shape[:2]

    for tpl in templates.values():
        made = _make_crop_composite_template(tpl, scale, bg)
        if made is None:
            continue
        template_image, template_w, template_h = made
        if template_w >= slot_w or template_h >= slot_h:
            continue

        result = cv2.matchTemplate(slot, template_image, cv2.TM_CCOEFF_NORMED)
        result = np.where(np.isfinite(result), result, -1.0)
        h, w = result.shape[:2]
        yy, xx = np.indices((h, w))
        center_x = xx + template_w / 2
        center_y = yy + template_h / 2
        valid = (center_x >= 25) & (center_x <= 65) & (center_y >= 25) & (center_y <= 75)
        result = np.where(valid, result, -1.0)

        _, max_score, _, max_loc = cv2.minMaxLoc(result)
        x = origin_x + max_loc[0] + template_w // 2
        y = origin_y + max_loc[1] + template_h // 2
        scored.append((float(max_score), tpl['name'], int(x), int(y)))

    scored.sort(reverse=True, key=lambda item: item[0])
    return scored


def run(image_path: Path, threshold: float, scale: float, show_low: bool, top: int) -> int:
    logger.remove()
    image = _read_image(image_path)
    detector = CVDetector(templates_dir='templates', template_platform='qq')
    detector.load_seed_templates()
    seed_name_map = _load_seed_name_map()

    print(
        f'image={image_path.name} size={image.shape[1]}x{image.shape[0]} '
        f'method=crop_composite/bgr/ccoeff scale={scale:.3f} threshold={threshold:.3f}'
    )
    hits = 0
    lows = 0
    hit_scores: list[float] = []
    low_scores: list[float] = []

    for idx, (x1, y1, x2, y2) in enumerate(SLOTS, 1):
        slot = image[y1:y2, x1:x2]
        scored = _match_slot(slot, (x1, y1), detector._seed_templates_by_name, scale)
        if not scored:
            print(f'{idx:02d} LOW: 未匹配到模板')
            lows += 1
            continue

        score, template_name, x, y = scored[0]
        is_hit = score >= threshold
        if is_hit:
            hits += 1
            hit_scores.append(score)
        else:
            lows += 1
            low_scores.append(score)
            if not show_low:
                continue

        status = 'HIT' if is_hit else 'LOW'
        top_text = ' | '.join(
            f'{_display_name(name, seed_name_map)}({name}) {score_value:.4f}'
            for score_value, name, _, _ in scored[: max(1, top)]
        )
        print(
            f'{idx:02d} {status}: {_display_name(template_name, seed_name_map)}\t'
            f'{score:.4f}\ttemplate={template_name}\tcenter=({x},{y})\ttop{top}={top_text}'
        )

    print(f'hits={hits} lows={lows}')
    if hit_scores:
        print(
            f'hit score min/avg/max={min(hit_scores):.4f}/{sum(hit_scores) / len(hit_scores):.4f}/{max(hit_scores):.4f}'
        )
    if low_scores:
        print(
            f'low score min/avg/max={min(low_scores):.4f}/{sum(low_scores) / len(low_scores):.4f}/{max(low_scores):.4f}'
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='测试仓库截图中的种子模板匹配结果')
    parser.add_argument('image', nargs='?', type=Path, help='截图路径；默认取仓库根目录最新 PNG')
    parser.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD, help='命中阈值，默认 0.8')
    parser.add_argument('--scale', type=float, default=DEFAULT_SCALE, help='固定缩放，默认 0.6')
    parser.add_argument('--show-low', action='store_true', help='输出低于阈值的空格/低分结果')
    parser.add_argument('--top', type=int, default=3, help='每格输出 Top N，默认 3')
    args = parser.parse_args()

    image_path = args.image if args.image is not None else _latest_root_png()
    if not image_path.is_absolute():
        image_path = (ROOT / image_path).resolve()
    return run(
        image_path=image_path,
        threshold=float(args.threshold),
        scale=float(args.scale),
        show_low=bool(args.show_low),
        top=int(args.top),
    )


if __name__ == '__main__':
    raise SystemExit(main())
