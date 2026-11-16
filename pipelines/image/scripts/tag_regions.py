#!/usr/bin/env python3
"""
Phase 2 language-query layer, step 1-4: SAM region masks -> CLIP embeddings
-> 3D localization via COLMAP's own 2D<->3D correspondences -> a saved
lookup file. Runs in the `crime-image-tag` env (CPU-only, no live nerfstudio
objects needed -- reads transforms.json / dataparser_transforms.json /
the COLMAP text model as plain data). See phase2_decision.md for the design
rationale.

Usage:
    conda activate crime-image-tag
    python pipelines/image/scripts/tag_regions.py \\
        --colmap-dir pipelines/image/data/galanakis2021/colmap \\
        --dataparser-transforms outputs/colmap_pruned/splatfacto/2026-08-24_010039/dataparser_transforms.json \\
        --out pipelines/image/query/region_lookup.json
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
from colmap_model import load_model, qvec_to_rotmat  # noqa: E402

RESIZE_LONG_SIDE = 1024  # SAM runs on a downsized copy for CPU speed
MIN_MASK_FRAC = 0.005  # drop masks smaller than this fraction of image area (noise)
MAX_MASK_FRAC = 0.5  # drop masks larger than this fraction (walls/floor background)


def load_dataparser_transform(path: Path):
    d = json.loads(path.read_text())
    transform = np.array(d["transform"])  # (3, 4)
    scale = float(d["scale"])
    return transform, scale


def raw_to_final(point_raw: np.ndarray, transform: np.ndarray, scale: float) -> np.ndarray:
    """Same formula as nerfstudio's NerfstudioDataParser._load_3D_points:
    point_final = ([point_raw, 1] @ transform.T) * scale
    """
    homog = np.append(point_raw, 1.0)
    return (transform @ homog) * scale


def build_masker(sam_checkpoint: Path):
    from segment_anything import SamAutomaticMaskGenerator, sam_model_registry

    sam = sam_model_registry["vit_b"](checkpoint=str(sam_checkpoint))
    sam.to("cpu")
    return SamAutomaticMaskGenerator(
        sam,
        points_per_side=16,  # reduced from default 32 for CPU speed
        pred_iou_thresh=0.86,
        stability_score_thresh=0.9,
        min_mask_region_area=200,
    )


def build_clip():
    import open_clip

    # "-quickgelu" variant matches the activation function the original
    # OpenAI CLIP weights were actually trained with; plain "ViT-B-32" +
    # pretrained="openai" mismatches (quick_gelu=False vs. the checkpoint's
    # quick_gelu=True) and open_clip warns about exactly this.
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32-quickgelu", pretrained="openai"
    )
    model.eval()
    return model, preprocess


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--colmap-dir", type=Path, required=True)
    ap.add_argument("--dataparser-transforms", type=Path, required=True)
    ap.add_argument("--sam-checkpoint", type=Path, default=Path(__file__).parent.parent / "models" / "sam_vit_b_01ec64.pth")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit-images", type=int, default=None, help="process only the first N registered images (debug)")
    args = ap.parse_args()

    transforms_json = json.loads((args.colmap_dir / "transforms.json").read_text())
    colmap_id_to_frame = {f["colmap_im_id"]: f["file_path"] for f in transforms_json["frames"]}

    cameras, images, points3D = load_model(args.colmap_dir / "sparse_txt")
    dp_transform, dp_scale = load_dataparser_transform(args.dataparser_transforms)

    print(f"[tag_regions] COLMAP model: {len(cameras)} cameras, {len(images)} images, {len(points3D)} points3D")

    masker = build_masker(args.sam_checkpoint)
    clip_model, clip_preprocess = build_clip()
    tokenizer = None  # not needed here, query_regions.py owns text encoding

    image_ids = sorted(images.keys())
    if args.limit_images:
        image_ids = image_ids[: args.limit_images]

    records = []
    t_start = time.time()
    for idx, image_id in enumerate(image_ids):
        im = images[image_id]
        frame_rel_path = colmap_id_to_frame.get(image_id)
        if frame_rel_path is None:
            print(f"  [{im.name}] no transforms.json frame for colmap_im_id={image_id}, skipping")
            continue
        img_path = args.colmap_dir / frame_rel_path
        if not img_path.exists():
            print(f"  [{im.name}] missing file {img_path}, skipping")
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

        # This image's known SIFT-track 2D<->3D correspondences, scaled into
        # the same resized-pixel space the masks live in. These pixel
        # locations and their matched 3D points were computed by COLMAP
        # itself from this image's camera pose+intrinsics during bundle
        # adjustment -- reused here rather than re-projected, per the task's
        # "reuse the pinned camera parameters, don't recompute."
        valid = im.point3D_ids >= 0
        xys_small = im.xys[valid] * resize_ratio
        pt_ids = im.point3D_ids[valid]

        kept = 0
        for m_idx, m in enumerate(masks):
            area = m["area"]
            frac = area / (small_w * small_h)
            if frac < MIN_MASK_FRAC or frac > MAX_MASK_FRAC:
                continue
            seg = m["segmentation"]  # (small_h, small_w) bool
            x, y, w, h = m["bbox"]  # xywh, resized-pixel space

            # which of this image's tracked 3D points fall inside this mask
            px = xys_small[:, 0].astype(int)
            py = xys_small[:, 1].astype(int)
            in_bounds = (px >= 0) & (px < small_w) & (py >= 0) & (py < small_h)
            inside_mask = np.zeros(len(px), dtype=bool)
            inside_mask[in_bounds] = seg[py[in_bounds], px[in_bounds]]
            support_ids = pt_ids[inside_mask]

            if len(support_ids) == 0:
                continue  # no depth evidence for this region, can't localize -- skip

            support_xyz = np.array([points3D[pid].xyz for pid in support_ids if pid in points3D])
            if len(support_xyz) == 0:
                continue
            point_raw = support_xyz.mean(axis=0)
            point_final = raw_to_final(point_raw, dp_transform, dp_scale)

            pad = 4
            crop_box = (max(0, x - pad), max(0, y - pad), min(small_w, x + w + pad), min(small_h, y + h + pad))
            crop = pil_small.crop(crop_box)
            with torch.no_grad():
                crop_t = clip_preprocess(crop).unsqueeze(0)
                emb = clip_model.encode_image(crop_t)
                emb = emb / emb.norm(dim=-1, keepdim=True)
            embedding = emb.squeeze(0).tolist()

            records.append(
                {
                    "image": im.name,
                    "frame_path": frame_rel_path,
                    "mask_idx": m_idx,
                    "bbox_resized": [x, y, w, h],
                    "resized_wh": [small_w, small_h],
                    "num_support_points": int(len(support_xyz)),
                    "point3d_raw": point_raw.tolist(),
                    "point3d_final": point_final.tolist(),
                    "clip_embedding": embedding,
                }
            )
            kept += 1

        print(
            f"  [{idx + 1}/{len(image_ids)}] {im.name}: {len(masks)} raw masks, "
            f"{kept} localized+embedded regions kept "
            f"(mask gen {t1 - t0:.1f}s, elapsed {time.time() - t_start:.1f}s)"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"clip_model": "ViT-B-32/openai", "records": records}, indent=1))
    print(f"[tag_regions] wrote {len(records)} region records to {args.out}")


if __name__ == "__main__":
    main()
