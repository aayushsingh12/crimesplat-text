#!/usr/bin/env python3
"""
EXIF-aware orientation correction for COLMAP input.

COLMAP's image reader loads raw pixel arrays and does not consult the EXIF
Orientation tag, so a batch with mixed portrait/landscape camera metadata
(some photos correctly upright as stored, others stored "sideways" with an
EXIF Orientation tag telling a normal viewer to rotate them on display) gets
fed to SIFT feature extraction with inconsistent effective orientations for
photos of the same real-world scene. This was already identified in Phase 2
as a critical preprocessing step -- fixing it alone (plus
--ImageReader.single_camera 0) took registration on this same 30-photo
dataset from 56.67% to 83.33%.

This script bakes the EXIF Orientation transform into the actual pixel data
(via PIL's ImageOps.exif_transpose) and writes the result to a separate
output directory -- it does not mutate the raw source photos in place, so
the original files stay untouched as provenance. The corrected copies are
what COLMAP should be pointed at, never the raw originals.

Usage:
    python pipelines/image/scripts/fix_exif_orientation.py \\
        pipelines/image/data/galanakis2021/photos \\
        pipelines/image/data/galanakis2021/photos_corrected
"""
import sys
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def fix_orientation(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not files:
        raise SystemExit(f"No images found in {src_dir}")

    changed = 0
    for src in files:
        img = Image.open(src)
        before_size = img.size
        # Bakes any EXIF Orientation rotation/flip into the pixel data and
        # returns an image with no Orientation tag left to apply.
        corrected = ImageOps.exif_transpose(img)
        dst = dst_dir / src.name
        # save() without an exif= kwarg writes no EXIF Orientation tag, so
        # nothing downstream (COLMAP or otherwise) can re-apply a rotation.
        corrected.save(dst)
        if corrected.size != before_size:
            changed += 1
            print(f"{src.name}: {before_size} -> {corrected.size} (rotated)")
        else:
            print(f"{src.name}: {before_size} (unchanged)")

    print(f"\n{len(files)} images written to {dst_dir}; {changed} required rotation.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <src_photos_dir> <dst_corrected_dir>")
    fix_orientation(Path(sys.argv[1]), Path(sys.argv[2]))
