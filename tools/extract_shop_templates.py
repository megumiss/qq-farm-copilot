"""Extract shop templates from screenshots and name them with OCR.

This follows template_collector preprocessing:
PIL RGB -> OpenCV BGR.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from collections import defaultdict
import argparse
import csv
import re

import cv2
import numpy as np
from PIL import Image

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency `rapidocr_onnxruntime`. Install with:\n"
        "  .\\.venv\\Scripts\\python -m pip install rapidocr_onnxruntime"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCREENSHOT_GLOB = "PixPin_2026-03-31_19-50-*.png"
OUTPUT_DIR = ROOT / "templates" / "shop_extracted_auto"
DEBUG_DIR = ROOT / "screenshots" / "shop_extracted_auto_debug"

# Dominant shop template resolution in this repo.
TARGET_SIZE = (109, 118)  # (width, height)

NORMALIZE_MAP = {
    "黄色秋菊": "秋菊（黄色）",
    "红色秋菊": "秋菊（红色）",
}

MANUAL_PATCH_MAP = {
    "白": "白萝卜",
    "胡萝": "胡萝卜",
    "向日": "向日葵",
    "花香根": "花香根鸢尾",
}


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int
    area: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract shop item cards and name them by OCR."
    )
    parser.add_argument(
        "--glob",
        default=DEFAULT_SCREENSHOT_GLOB,
        help="Screenshot glob under project root.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete previous extracted shop_*.png before writing new files.",
    )
    return parser.parse_args()


def read_like_template_collector(path: Path) -> np.ndarray:
    pil = Image.open(path).convert("RGB")
    rgb = np.array(pil)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def iou(a: Rect, b: Rect) -> float:
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.w, b.x + b.w)
    y2 = min(a.y + a.h, b.y + b.h)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def detect_shop_cards(img_bgr: np.ndarray) -> list[Rect]:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edge = cv2.Canny(blur, 50, 150)
    contours, _ = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[Rect] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if h == 0:
            continue
        ar = w / h
        if 25000 <= area <= 42000 and 0.90 <= ar <= 1.05:
            candidates.append(Rect(x, y, w, h, area))

    candidates.sort(key=lambda r: r.area, reverse=True)
    kept: list[Rect] = []
    for r in candidates:
        if all(iou(r, k) < 0.35 for k in kept):
            kept.append(r)
    kept.sort(key=lambda r: (r.y, r.x))
    return kept


def annotate_rects(img_bgr: np.ndarray, rects: list[Rect]) -> np.ndarray:
    vis = img_bgr.copy()
    for i, r in enumerate(rects, start=1):
        cv2.rectangle(vis, (r.x, r.y), (r.x + r.w, r.y + r.h), (0, 0, 255), 2)
        cv2.putText(
            vis,
            str(i),
            (r.x + 2, max(12, r.y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 255),
            1,
        )
    return vis


def row_col_indices(rects: list[Rect]) -> list[tuple[int, int]]:
    if not rects:
        return []
    rows: list[list[Rect]] = []
    y_tol = 25
    for r in rects:
        placed = False
        for row in rows:
            if abs(r.y - row[0].y) <= y_tol:
                row.append(r)
                placed = True
                break
        if not placed:
            rows.append([r])
    for row in rows:
        row.sort(key=lambda t: t.x)

    pos_map: dict[tuple[int, int, int, int], tuple[int, int]] = {}
    for ri, row in enumerate(rows, start=1):
        for ci, r in enumerate(row, start=1):
            pos_map[(r.x, r.y, r.w, r.h)] = (ri, ci)

    return [pos_map[(r.x, r.y, r.w, r.h)] for r in rects]


def collect_vocab() -> list[str]:
    vocab: set[str] = set()
    for p in (ROOT / "templates").glob("seed_*.png"):
        vocab.add(p.stem[len("seed_") :])
    for p in (ROOT / "templates").glob("shop_*.png"):
        if "shop_extracted_auto" in str(p):
            continue
        vocab.add(p.stem[len("shop_") :])
    return sorted(vocab)


def clean_text(text: str) -> str:
    text = re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9（）()]+", "", text)
    return text.strip()


def sanitize_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    return text.strip() or "未识别"


def resolve_name(raw_text: str, vocab: list[str]) -> tuple[str, float]:
    text = clean_text(raw_text)
    if not text:
        return "未识别", 0.0
    if text in NORMALIZE_MAP:
        text = NORMALIZE_MAP[text]
    if text in MANUAL_PATCH_MAP:
        text = MANUAL_PATCH_MAP[text]
    if text in vocab:
        return text, 1.0

    starts = [v for v in vocab if v.startswith(text)]
    if len(starts) == 1:
        return starts[0], 0.92

    best_name = text
    best_score = 0.0
    for v in vocab:
        s = SequenceMatcher(None, text, v).ratio()
        if s > best_score:
            best_score = s
            best_name = v
    if best_score >= 0.70:
        return best_name, best_score
    return text, best_score


def ocr_title(ocr: RapidOCR, card_bgr: np.ndarray) -> tuple[str, float]:
    h, w = card_bgr.shape[:2]
    # Right-top title area on the original card.
    roi = card_bgr[2 : int(h * 0.26), int(w * 0.35) : w - 6]
    roi = cv2.resize(roi, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    roi = cv2.convertScaleAbs(roi, alpha=1.25, beta=0)
    result, _ = ocr(roi)
    if not result:
        return "", 0.0
    return str(result[0][1]), float(result[0][2])


def clean_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in OUTPUT_DIR.glob("shop_*.png"):
        p.unlink(missing_ok=True)
    for p in OUTPUT_DIR.glob("manifest*.csv"):
        p.unlink(missing_ok=True)


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    if args.clean:
        clean_output_dir()

    screenshots = sorted(ROOT.glob(args.glob))
    if not screenshots:
        raise SystemExit(f"No screenshots found by pattern: {args.glob}")

    ocr = RapidOCR()
    vocab = collect_vocab()

    rows: list[dict[str, str | int]] = []
    total_saved = 0
    name_counter: defaultdict[str, int] = defaultdict(int)

    for shot in screenshots:
        img = read_like_template_collector(shot)
        rects = detect_shop_cards(img)
        rc = row_col_indices(rects)

        debug = annotate_rects(img, rects)
        debug_path = DEBUG_DIR / f"{shot.stem}_cards.png"
        ok, buf = cv2.imencode(".png", debug)
        if ok:
            debug_path.write_bytes(buf.tobytes())

        saved_this_image = 0
        for idx, (rect, (ridx, cidx)) in enumerate(zip(rects, rc), start=1):
            x, y, w, h = rect.x, rect.y, rect.w, rect.h
            card = img[y : y + h, x : x + w]
            if card.size == 0:
                continue

            raw_text, ocr_conf = ocr_title(ocr, card)
            resolved_name, match_score = resolve_name(raw_text, vocab)
            resolved_name = sanitize_name(resolved_name)

            name_counter[resolved_name] += 1
            n = name_counter[resolved_name]
            filename = (
                f"shop_{resolved_name}.png"
                if n == 1
                else f"shop_{resolved_name}_{n}.png"
            )
            out_path = OUTPUT_DIR / filename

            resized = cv2.resize(card, TARGET_SIZE, interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".png", resized)
            if not ok:
                continue
            out_path.write_bytes(buf.tobytes())

            rows.append(
                {
                    "source_screenshot": shot.name,
                    "index_in_screenshot": idx,
                    "row": ridx,
                    "col": cidx,
                    "bbox_x": x,
                    "bbox_y": y,
                    "bbox_w": w,
                    "bbox_h": h,
                    "ocr_text": raw_text,
                    "ocr_confidence": f"{ocr_conf:.6f}",
                    "resolved_item_name": resolved_name,
                    "name_match_score": f"{match_score:.6f}",
                    "saved_template": str(out_path),
                    "saved_w": TARGET_SIZE[0],
                    "saved_h": TARGET_SIZE[1],
                }
            )
            total_saved += 1
            saved_this_image += 1

        print(f"{shot.name}: detected={len(rects)} saved={saved_this_image}")

    manifest_csv = OUTPUT_DIR / "manifest.csv"
    if rows:
        with manifest_csv.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    print(f"done: screenshots={len(screenshots)} saved_templates={total_saved}")
    print(f"templates_dir={OUTPUT_DIR}")
    print(f"manifest={manifest_csv}")
    print(f"debug_dir={DEBUG_DIR}")


if __name__ == "__main__":
    main()
