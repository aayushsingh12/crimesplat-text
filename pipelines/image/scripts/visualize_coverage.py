#!/usr/bin/env python3
"""
Demo prep, read-only: builds one summary image showing SAM region-mask
coverage across all 30 galanakis2021 photos -- the 20 COLMAP-registered,
3D-queryable ones (region_lookup.json) plus the 10 COLMAP never
registered, 2D-only encoded ones (region_lookup_2d_only.json, no 3D point,
not queryable -- see phase2_decision.md), visually distinguished in the
grid (desaturated + gray outlines + an explicit caption suffix) so the
two coverage levels are never confused.

Both lookups store each kept region's bbox and mask_idx but not its full
segmentation polygon (too large to keep committed), so mask *outlines*
are recovered by re-running just the SAM mask-generation step
(masker.generate(), reused unmodified from tag_regions.py -- same
function, same config, so mask_idx lines up with what's already in the
lookups) and keeping only the masks whose index was actually kept. No
CLIP, no 3D localization, no queries, and tag_regions.py itself is not
modified -- imported from, not touched.

Usage:
    conda activate crime-image-tag
    python pipelines/image/scripts/visualize_coverage.py \\
        --colmap-dir pipelines/image/data/galanakis2021/colmap \\
        --lookup pipelines/image/query/region_lookup.json \\
        --photos-dir pipelines/image/data/galanakis2021/photos_corrected \\
        --lookup-2d-only pipelines/image/query/region_lookup_2d_only.json \\
        --out pipelines/image/demo_assets/encoding_coverage.png
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from tag_regions import RESIZE_LONG_SIDE, build_masker  # noqa: E402  -- reused, not modified

PALETTE = [
    (255, 64, 64), (64, 160, 255), (64, 220, 120), (255, 200, 40),
    (200, 80, 255), (255, 130, 40), (40, 220, 220), (255, 90, 180),
]
GRAY_PALETTE = [(200, 200, 200), (170, 170, 170), (150, 150, 150)]  # 2D-only: desaturated, no color variety
THUMB_SIZE = 340  # per-cell size in the output grid, before caption strip
CAPTION_LINE_H = 20
CAPTION_MAX_LINES = 2  # the 2D-only captions are longer and need to wrap, not overflow into the next cell
CAPTION_H = CAPTION_LINE_H * CAPTION_MAX_LINES + 8
BORDER_W = 6


def wrap_caption(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Greedy word-wrap so a caption never overflows its cell width into
    the neighboring cell -- the 2D-only captions are long enough to need
    this; the plain ones typically fit on one line."""
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:CAPTION_MAX_LINES]


def overlay_masks(pil_small: Image.Image, masks: list, keep_idxs: set[int], palette: list, desaturate: bool = False) -> Image.Image:
    """Draws semi-transparent colored outlines for the kept masks onto a
    copy of pil_small. desaturate=True (2D-only images) converts the base
    photo to grayscale first, so these cells read as visually distinct
    from the full-color 3D-queryable ones at a glance."""
    base = pil_small.convert("L").convert("RGB") if desaturate else pil_small.convert("RGB")
    base = base.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i, m_idx in enumerate(sorted(keep_idxs)):
        seg = masks[m_idx]["segmentation"].astype(np.uint8)
        contours, _ = cv2.findContours(seg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        color = palette[i % len(palette)]
        for c in contours:
            pts = [(int(p[0][0]), int(p[0][1])) for p in c]
            if len(pts) >= 2:
                draw.line(pts + [pts[0]], fill=color + (200,), width=3)
    return Image.alpha_composite(base, overlay).convert("RGB")


def build_grid(cells: list[Image.Image], captions: list[str], borders: list[tuple], n_cols: int) -> Image.Image:
    n = len(cells)
    n_rows = -(-n // n_cols)
    cell_w, cell_h = THUMB_SIZE, THUMB_SIZE + CAPTION_H
    grid = Image.new("RGB", (n_cols * cell_w, n_rows * cell_h), (24, 24, 24))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()

    for i, (cell, caption, border_color) in enumerate(zip(cells, captions, borders)):
        row, col = divmod(i, n_cols)
        thumb = cell.copy()
        thumb.thumbnail((THUMB_SIZE, THUMB_SIZE))
        x0 = col * cell_w + (cell_w - thumb.width) // 2
        y0 = row * cell_h
        if border_color is not None:
            draw.rectangle(
                [x0 - BORDER_W, y0 - BORDER_W, x0 + thumb.width + BORDER_W, y0 + thumb.height + BORDER_W],
                outline=border_color,
                width=BORDER_W,
            )
        grid.paste(thumb, (x0, y0))
        text_color = (150, 150, 150) if border_color is not None else (230, 230, 230)
        lines = wrap_caption(draw, caption, font, cell_w - 8)
        for li, line in enumerate(lines):
            text_bbox = draw.textbbox((0, 0), line, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            tx = col * cell_w + (cell_w - text_w) // 2
            ty = row * cell_h + THUMB_SIZE + 4 + li * CAPTION_LINE_H
            draw.text((tx, ty), line, fill=text_color, font=font)
    return grid


def process_image(img_path: Path, image_name: str, keep_idxs: set[int], masker, palette, desaturate: bool):
    pil_full = Image.open(img_path).convert("RGB")
    full_w, full_h = pil_full.size
    resize_ratio = RESIZE_LONG_SIDE / max(full_w, full_h)
    small_w, small_h = int(full_w * resize_ratio), int(full_h * resize_ratio)
    pil_small = pil_full.resize((small_w, small_h), Image.BILINEAR)

    masks = masker.generate(np.array(pil_small))
    assert max(keep_idxs) < len(masks), (
        f"{image_name}: lookup references mask_idx {max(keep_idxs)} but a fresh "
        f"masker.generate() only produced {len(masks)} masks -- SAM mask generation "
        f"is not reproducing the same result as when the lookup was built."
    )
    return overlay_masks(pil_small, masks, keep_idxs, palette, desaturate=desaturate), len(masks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--colmap-dir", type=Path, required=True)
    ap.add_argument("--lookup", type=Path, required=True)
    ap.add_argument("--photos-dir", type=Path, default=None, help="dir holding the 2D-only images (photos_corrected)")
    ap.add_argument("--lookup-2d-only", type=Path, default=None, help="region_lookup_2d_only.json, optional")
    ap.add_argument("--sam-checkpoint", type=Path, default=Path(__file__).parent.parent / "models" / "sam_vit_b_01ec64.pth")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    lookup = json.loads(args.lookup.read_text())
    by_frame = defaultdict(list)  # frame_path -> list of records
    for r in lookup["records"]:
        by_frame[r["frame_path"]].append(r)

    print(f"[visualize_coverage] {len(by_frame)} 3D-queryable images in {args.lookup}")

    masker = build_masker(args.sam_checkpoint)

    cells, captions, borders = [], [], []
    for frame_path in sorted(by_frame.keys(), key=lambda p: int(Path(p).stem.split("_")[-1])):
        recs = by_frame[frame_path]
        image_name = recs[0]["image"]
        keep_idxs = {r["mask_idx"] for r in recs}
        img_path = args.colmap_dir / frame_path
        annotated, n_raw = process_image(img_path, image_name, keep_idxs, masker, PALETTE, desaturate=False)
        cells.append(annotated)
        captions.append(f"{image_name} - {len(recs)} regions")  # plain hyphen: PIL's default font has no em-dash glyph
        borders.append(None)
        print(f"  {image_name}: {len(recs)} kept regions overlaid (of {n_raw} raw masks)")

    if args.lookup_2d_only is not None and args.photos_dir is not None:
        lookup_2d = json.loads(args.lookup_2d_only.read_text())
        by_image_2d = defaultdict(list)
        for r in lookup_2d["records"]:
            by_image_2d[r["image"]].append(r)
        print(f"[visualize_coverage] {len(by_image_2d)} 2D-only (no COLMAP pose) images in {args.lookup_2d_only}")

        for image_name in sorted(by_image_2d.keys()):
            recs = by_image_2d[image_name]
            keep_idxs = {r["mask_idx"] for r in recs}
            img_path = args.photos_dir / image_name
            annotated, n_raw = process_image(img_path, image_name, keep_idxs, masker, GRAY_PALETTE, desaturate=True)
            cells.append(annotated)
            captions.append(f"{image_name} - {len(recs)} regions (2D only - no COLMAP pose)")
            borders.append((255, 140, 0))  # orange border marks "not 3D-queryable"
            print(f"  {image_name}: {len(recs)} kept regions overlaid (of {n_raw} raw masks) [2D only]")

    grid = build_grid(cells, captions, borders, n_cols=5)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    grid.save(args.out)
    print(f"[visualize_coverage] wrote {args.out} ({grid.width}x{grid.height}), {len(cells)} images total")


if __name__ == "__main__":
    main()
