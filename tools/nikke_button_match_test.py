"""Use NIKKE Button.match to test template recognition on screenshots.

Default mode:
- templates: all templates under ./templates
- screenshots: all *.png under ./screenshots (top-level only)
- match: Button.match(static=False)
- output: ./screenshots/annotated_nikke_button_match
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def _imread(path: Path) -> np.ndarray | None:
    """执行 `imread` 相关处理。"""
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def _iter_templates(templates_dir: Path) -> list[Path]:
    """遍历并返回 `templates` 列表。"""
    exts = {".png", ".jpg", ".jpeg"}
    items = [p for p in templates_dir.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    items.sort()
    return items


def _iter_screenshots(shots_dir: Path) -> list[Path]:
    """遍历并返回 `screenshots` 列表。"""
    items = [p for p in shots_dir.glob("*.png") if p.is_file()]
    items.sort()
    return items


def _draw_hits(image: np.ndarray, hits: list[dict]) -> np.ndarray:
    """执行 `draw hits` 相关处理。"""
    out = image.copy()
    for h in hits:
        x1, y1, x2, y2 = h["bbox"]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(out, h["name"], (x1, max(14, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
    return out


def _save_image(path: Path, image: np.ndarray) -> None:
    """保存 `image` 相关数据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", image)
    if ok:
        path.write_bytes(buf.tobytes())


def main() -> int:
    """程序主入口。"""
    parser = argparse.ArgumentParser(description="Batch test by NIKKE Button.match")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--only-540x960", action="store_true")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    nikke_root = root / "NIKKE"
    if str(nikke_root) not in sys.path:
        sys.path.insert(0, str(nikke_root))

    from module.base.button import Button  # type: ignore

    templates_dir = root / "templates"
    shots_dir = root / "screenshots"
    output_dir = Path(args.output) if args.output else (
        shots_dir / ("annotated_nikke_button_match_540x960" if args.only_540x960 else "annotated_nikke_button_match")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    templates = _iter_templates(templates_dir)
    screenshots = _iter_screenshots(shots_dir)
    if not templates:
        print("No templates found")
        return 1
    if not screenshots:
        print("No screenshots found")
        return 1

    prepared_templates: list[tuple[str, Path, int, int]] = []
    skipped_templates: list[str] = []
    for tp in templates:
        img = _imread(tp)
        if img is None:
            skipped_templates.append(str(tp))
            continue
        h, w = img.shape[:2]
        if args.only_540x960 and not (w == 540 and h == 960):
            continue
        prepared_templates.append((tp.stem, tp, w, h))

    summary: dict = {
        "mode": "nikke_button_match",
        "threshold": args.threshold,
        "only_540x960": bool(args.only_540x960),
        "template_total": len(prepared_templates),
        "screenshot_total": len(screenshots),
        "skipped_template_count": len(skipped_templates),
        "items": [],
    }

    for sp in screenshots:
        screen = _imread(sp)
        if screen is None:
            summary["items"].append({"screenshot": sp.name, "error": "read_failed"})
            continue

        hits: list[dict] = []
        for name, tp, tw, th in prepared_templates:
            btn = Button(
                area=(0, 0, tw, th),
                color=(0, 0, 0),
                button=(0, 0, tw, th),
                file=str(tp),
                name=name,
            )
            if not btn.match(screen, threshold=float(args.threshold), static=False):
                continue

            x1, y1, x2, y2 = [int(v) for v in btn.button]
            x1 = max(0, min(x1, screen.shape[1] - 1))
            y1 = max(0, min(y1, screen.shape[0] - 1))
            x2 = max(x1 + 1, min(x2, screen.shape[1]))
            y2 = max(y1 + 1, min(y2, screen.shape[0]))
            hits.append({"name": name, "bbox": [x1, y1, x2, y2]})

        annotated = _draw_hits(screen, hits)
        out_name = sp.stem + ".annotated.png"
        _save_image(output_dir / out_name, annotated)
        summary["items"].append(
            {
                "screenshot": sp.name,
                "hit_count": len(hits),
                "hits": [h["name"] for h in hits],
                "annotated": out_name,
            }
        )
        print(f"{sp.name}: {len(hits)} hits")

    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done. summary -> {output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
