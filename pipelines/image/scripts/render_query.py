#!/usr/bin/env python3
"""
Phase 2 language-query layer, final step: render the checkpoint from the
camera that produced the best-matching region, then overlay a marker at
that region's 3D location projected into the same camera. Runs in the
`crime-image` env (GPU) -- the sole handoff point from the CPU-only
crime-image-tag env, which only wrote a JSON file (the match record from
query_regions.py).

Same weights_only=False checkpoint-loading workaround as eval_checkpoint.py
/ render_checkpoint.py (see those files' docstrings for why).

Usage:
    conda activate crime-image
    python pipelines/image/scripts/render_query.py \\
        --load-config outputs/colmap_pruned/splatfacto/2026-08-24_010039/config.yml \\
        --match pipelines/image/query/last_match.json \\
        --out pipelines/image/query/last_result.jpg
"""
from __future__ import annotations

import argparse
import functools
import json
from pathlib import Path

import numpy as np
import torch

_orig_load = torch.load


@functools.wraps(_orig_load)
def _load_trusted(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_load(*args, **kwargs)


torch.load = _load_trusted

from nerfstudio.utils.eval_utils import eval_setup  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def find_camera(pipeline, frame_path: str):
    """Search train then eval datasets for the camera whose image_filename
    matches frame_path (e.g. "images/frame_00001.jpg"), matching on the
    bare filename only -- the loaded dataset may point at a downscaled
    sibling folder (e.g. "images_4/") depending on the config's auto
    image-downscale factor, not the "images/" path transforms.json used."""
    target_name = Path(frame_path).name
    for split_name, dataset in (
        ("train", pipeline.datamanager.train_dataset),
        ("eval", pipeline.datamanager.eval_dataset),
    ):
        for i, fn in enumerate(dataset.image_filenames):
            if Path(fn).name == target_name:
                return split_name, i, dataset.cameras[i : i + 1]
    return None, None, None


def project_point(camera, point_final: np.ndarray):
    """Project a 3D point (already in the training/final coordinate space)
    into this camera's image plane using its known intrinsics + pose,
    ignoring radial distortion (fine for a marker overlay, not a metric
    measurement)."""
    c2w = camera.camera_to_worlds[0].cpu().numpy()  # (3, 4)
    R = c2w[:3, :3]
    t = c2w[:3, 3]
    # world_to_cam: invert the (rotation, translation) pair
    R_inv = R.T
    t_inv = -R_inv @ t
    p_cam = R_inv @ point_final + t_inv

    fx = float(camera.fx[0])
    fy = float(camera.fy[0])
    cx = float(camera.cx[0])
    cy = float(camera.cy[0])

    # nerfstudio camera convention: +x right, +y up, +z back (camera looks
    # down -z), consistent with camera_utils / the OpenGL-style convention
    # used throughout nerfstudio's Cameras class.
    x, y, z = p_cam
    if z >= 0:
        return None, None  # behind the camera, can't be in frame
    u = fx * (x / -z) + cx
    v = -fy * (y / -z) + cy
    in_bounds = 0 <= u < float(camera.width[0]) and 0 <= v < float(camera.height[0])
    return (u, v), in_bounds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load-config", type=Path, required=True)
    ap.add_argument("--match", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    match = json.loads(args.match.read_text())
    print(f"[render_query] query={match['query']!r} best match image={match['image']} sim={match['similarity']:.4f}")

    if not match.get("localized", True):
        # 2D-only match (see query_regions.py / tag_regions_2d_only.py):
        # no COLMAP pose for this image, so no frame_path / 3D point exists
        # to render or project -- nothing to do here but say so honestly.
        raise SystemExit(
            f"[render_query] best match for {match['query']!r} is 2D-only (image={match['image']}): "
            f"{match.get('message', 'not part of the 3D reconstruction, cannot be rendered.')}"
        )

    config, pipeline, checkpoint_path, step = eval_setup(args.load_config, test_mode="test")
    print(f"[render_query] loaded checkpoint {checkpoint_path} at step {step}")

    split_name, idx, camera = find_camera(pipeline, match["frame_path"])
    if camera is None:
        raise SystemExit(f"[render_query] could not find a camera for {match['frame_path']} in train or eval dataset")
    print(f"[render_query] using {split_name} camera index {idx} ({match['frame_path']})")

    camera = camera.to(pipeline.device)
    with torch.no_grad():
        outputs = pipeline.model.get_outputs_for_camera(camera)
    rgb = outputs["rgb"].detach().cpu().numpy()
    rgb = np.clip(rgb, 0.0, 1.0)
    img = Image.fromarray((rgb * 255).astype(np.uint8))

    point_final = np.array(match["point3d_final"])
    (uv, in_bounds) = project_point(camera, point_final)

    draw = ImageDraw.Draw(img)
    if uv is not None:
        u, v = uv
        r = 22
        color = (255, 32, 32) if in_bounds else (255, 160, 0)
        draw.ellipse([u - r, v - r, u + r, v + r], outline=color, width=5)
        draw.line([u - r - 10, v, u + r + 10, v], fill=color, width=3)
        draw.line([u, v - r - 10, u, v + r + 10], fill=color, width=3)
        print(f"[render_query] projected match location at pixel ({u:.1f}, {v:.1f}), in_bounds={in_bounds}")
    else:
        print("[render_query] WARNING: matched 3D point projects behind this camera -- no marker drawn")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"[render_query] wrote {args.out}")


if __name__ == "__main__":
    main()
