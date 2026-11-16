#!/usr/bin/env python3
"""
Extracts the 20 registered COLMAP camera poses for galanakis2021 and
transforms them into the exact same coordinate space the exported
splat.ply lives in, for the web viewer's preset-viewpoint UI
(pipelines/image/ui_web/). Read-only relative to the pinned pipeline:
reuses colmap_model.py's reader and tag_regions.py's already-verified
raw_to_final() point transform unmodified (imported, not rewritten).

Position: camera center is just a 3D point (no orientation to preserve),
so it's transformed with the IDENTICAL formula phase2_decision.md already
verified for 3D region points: point_final = ([point,1] @ transform.T) *
scale, using this checkpoint's own dataparser_transforms.json.

Orientation: three DISTINCT conversions are involved, easy to conflate --
caught the hard way, not assumed correct on the first pass (see
COLMAP_TO_NERF below for exactly how this was caught and verified):

1. COLMAP_TO_NERF: COLMAP's camera-to-world uses the computer-vision
   convention (Y down, Z forward); nerfstudio's transforms.json poses use
   the OpenGL/NeRF convention (Y up, Z backward) -- negate the Y and Z
   columns, the same step every COLMAP->NeRF converter applies.
2. The dataparser's composed transform's rotation 3x3 block is then
   applied to that already-converted camera-to-world rotation (matching
   exactly how nerfstudio itself transforms camera rotations internally),
   WITHOUT the scale factor (scale only ever multiplies a translation in
   nerfstudio's own dataparser code, never a rotation block, since scaling
   a rotation matrix would break orthonormality).
3. A separate conversion is then needed for the camera basis
convention itself: COLMAP/nerfstudio use the OpenGL-style convention
(camera looks down local -Z), but gsplat.js's Camera class (checked
directly in vendor/gsplat-1.2.9.es.js -- Object3D.forward applies the
rotation to local (0,0,1), i.e. gsplat cameras look down local +Z, and
right x up = forward, the opposite handedness pairing from OpenGL's
right x up = back). Verified by hand-deriving gsplat's own OrbitControls
math on a concrete test case (90 deg yaw) before trusting this: the fix
that keeps "up" and "forward" both physically correct is a 180 deg
rotation of the local frame about its own Y (up) axis, i.e.
R_gsplat = R_nerf_final @ diag(-1, 1, -1) -- a proper rotation (det +1),
so it stays quaternion-representable.

Ships the rotation as a flat row-major 3x3 (not a quaternion computed by
hand here) specifically so the browser can convert it with gsplat's OWN
Quaternion.FromMatrix3() -- reusing the library's already-tested
matrix->quaternion code instead of re-implementing quaternion math in
Python, where a sign slip would be easy to make and hard to notice.

Usage:
    conda activate crime-image-tag   # (pure numpy/json, no torch needed)
    python pipelines/image/scripts/extract_camera_poses.py \\
        --colmap-dir pipelines/image/data/galanakis2021/colmap \\
        --dataparser-transforms outputs/colmap_pruned/splatfacto/2026-08-24_010039/dataparser_transforms.json \\
        --out pipelines/image/ui_web/camera_poses.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from colmap_model import load_model, qvec_to_rotmat  # noqa: E402
from tag_regions import load_dataparser_transform, raw_to_final  # noqa: E402

# Standard COLMAP -> nerfstudio camera-convention fix: COLMAP's
# camera-to-world uses the computer-vision convention (Y down, Z forward);
# nerfstudio's transforms.json poses use the OpenGL/NeRF convention (Y up,
# Z backward, forward = -Z) -- the same "flip the Y and Z columns" step
# every COLMAP->NeRF converter applies (e.g. instant-ngp's colmap2nerf.py).
# This is SEPARATE from applied_transform (an additional axis permutation
# nerfstudio applies on top) and from BASIS_FIX below (gsplat's own,
# further different convention) -- three distinct conversions, easy to
# conflate. Caught via a real bug: an initial version of this script
# omitted this step, verified wrong by projecting a known 3D point through
# the resulting extrinsics and comparing to COLMAP's own recorded 2D pixel
# (matched -- proving qvec_to_rotmat itself was fine), then by diffing the
# resulting rotation directly against transforms.json's own saved
# per-frame pose (mismatched in exactly the Y/Z-column-negation pattern
# this fixes) and against nerfstudio's own loaded, trained
# camera_to_worlds for the same image (matched exactly, to ~1e-6, only
# after adding this fix).
COLMAP_TO_NERF = np.diag([1.0, -1.0, -1.0])

# Local-frame basis fix, nerfstudio (-Z-forward) -> gsplat (+Z-forward).
# Derived and hand-verified against gsplat's own OrbitControls math -- see
# module docstring. Applied on the right: R_gsplat = R_nerf_final @ BASIS_FIX.
BASIS_FIX = np.diag([-1.0, 1.0, -1.0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--colmap-dir", type=Path, required=True)
    ap.add_argument("--dataparser-transforms", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cameras, images, points3D = load_model(args.colmap_dir / "sparse_txt")
    transform, scale = load_dataparser_transform(args.dataparser_transforms)
    print(f"[extract_camera_poses] {len(images)} registered cameras in COLMAP model")

    entries = []
    for image_id in sorted(images.keys()):
        im = images[image_id]

        R_wc = qvec_to_rotmat(im.qvec)  # world-to-camera, raw COLMAP space
        R_cw_raw = R_wc.T  # camera-to-world, raw COLMAP space
        center_raw = -R_cw_raw @ im.tvec  # camera center, raw COLMAP space

        center_final = raw_to_final(center_raw, transform, scale)
        R_cw_raw_nerf_convention = R_cw_raw @ COLMAP_TO_NERF
        R_cw_nerf_final = transform[:3, :3] @ R_cw_raw_nerf_convention  # rotation only, no scale (see docstring)
        R_cw_gsplat_final = R_cw_nerf_final @ BASIS_FIX

        entries.append(
            {
                "image": im.name,
                "position": center_final.tolist(),
                # row-major 3x3, flattened -- fed to SPLAT.Matrix3(...9 args) client-side
                "rotation_matrix_row_major": R_cw_gsplat_final.flatten().tolist(),
            }
        )
        print(f"  {im.name}: position={[round(v, 4) for v in center_final]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"cameras": entries}, indent=1))
    print(f"[extract_camera_poses] wrote {len(entries)} camera poses to {args.out}")


if __name__ == "__main__":
    main()
