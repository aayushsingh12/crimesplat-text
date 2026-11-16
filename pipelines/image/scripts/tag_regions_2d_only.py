#!/usr/bin/env python3
"""
2D-only SAM+CLIP tagging for the 10 galanakis2021 photos COLMAP never
registered (IMG_0466-0468, 0471-0475, 0482-0483 -- confirmed by
cross-referencing against sparse_txt/images.txt's registered set, see
phase2_decision.md). These have no camera pose, so tag_regions.py's 3D
localization method (COLMAP's own SIFT-track 2D<->3D correspondences)
has no depth data to work from for them -- expected, not a missed step.

This is a SEPARATE artifact from region_lookup.json on purpose: masks +
CLIP embeddings only, no 3D point, written to region_lookup_2d_only.json.
Never merged into region_lookup.json and never read by query_regions.py --
a query must not be able to match onto a region with no 3D location.
Encoding coverage only (visualize_coverage.py), not query coverage.

Reuses tag_regions.py's masker/CLIP builders and mask-generation config
unmodified (imported, not touched) so the SAM/CLIP setup is identical to
the 3D-queryable regions -- just without the COLMAP correspondence step.

Usage:
    conda activate crime-image-tag
    python pipelines/image/scripts/tag_regions_2d_only.py \\
        --photos-dir pipelines/image/data/galanakis2021/photos_corrected \\
        --out pipelines/image/query/region_lookup_2d_only.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from tag_regions import RESIZE_LONG_SIDE, MIN_MASK_FRAC, MAX_MASK_FRAC, build_masker, build_clip  # noqa: E402

# Confirmed against sparse_txt/images.txt's registered-image set --
# see phase2_decision.md's confirmation step.
UNREGISTERED_IMAGES = [
    "IMG_0466.jpg", "IMG_0467.jpg", "IMG_0468.jpg", "IMG_0471.jpg",
    "IMG_0472.jpg", "IMG_0473.jpg", "IMG_0474.jpg", "IMG_0475.jpg",
    "IMG_0482.jpg", "IMG_0483.jpg",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos-dir", type=Path, required=True)
    ap.add_argument("--sam-checkpoint", type=Path, default=Path(__file__).parent.parent / "models" / "sam_vit_b_01ec64.pth")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    masker = build_masker(args.sam_checkpoint)
    clip_model, clip_preprocess = build_clip()

    records = []
    t_start = time.time()
    for idx, image_name in enumerate(UNREGISTERED_IMAGES):
        img_path = args.photos_dir / image_name
        if not img_path.exists():
            print(f"  [{image_name}] missing file {img_path}, skipping")
            continue

        pil_full = Image.open(img_path).convert("RGB")
        full_w, full_h = pil_full.size
        resize_ratio = RESIZE_LONG_SIDE / max(full_w, full_h)
        small_w, small_h = int(full_w * resize_ratio), int(full_h * resize_ratio)
        pil_small = pil_full.resize((small_w, small_h), Image.BILINEAR)
        small_np = np.array(pil_small)

        t0 = time.time()
        masks = masker.generate(small_np)
        t1 = time.time()

        kept = 0
        for m_idx, m in enumerate(masks):
            frac = m["area"] / (small_w * small_h)
            if frac < MIN_MASK_FRAC or frac > MAX_MASK_FRAC:
                continue
            x, y, w, h = m["bbox"]
            pad = 4
            crop_box = (max(0, x - pad), max(0, y - pad), min(small_w, x + w + pad), min(small_h, y + h + pad))
            crop = pil_small.crop(crop_box)
            with torch.no_grad():
                crop_t = clip_preprocess(crop).unsqueeze(0)
                emb = clip_model.encode_image(crop_t)
                emb = emb / emb.norm(dim=-1, keepdim=True)
            embedding = emb.squeeze(0).tolist()

            # No point3d_raw / point3d_final -- no COLMAP pose exists for
            # this image, so there is nothing to localize with. This
            # record is 2D-only by construction.
            records.append(
                {
                    "image": image_name,
                    "mask_idx": m_idx,
                    "bbox_resized": [x, y, w, h],
                    "resized_wh": [small_w, small_h],
                    "clip_embedding": embedding,
                    "queryable_3d": False,
                }
            )
            kept += 1

        print(
            f"  [{idx + 1}/{len(UNREGISTERED_IMAGES)}] {image_name}: {len(masks)} raw masks, "
            f"{kept} embedded (2D-only) regions kept "
            f"(mask gen {t1 - t0:.1f}s, elapsed {time.time() - t_start:.1f}s)"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "clip_model": "ViT-B-32-quickgelu/openai",
                "note": "2D-only: no COLMAP pose, no 3D point, not queryable. See phase2_decision.md.",
                "records": records,
            },
            indent=1,
        )
    )
    print(f"[tag_regions_2d_only] wrote {len(records)} 2D-only region records to {args.out}")


if __name__ == "__main__":
    main()
