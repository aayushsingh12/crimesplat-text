#!/usr/bin/env python3
"""Camera pose error of a COLMAP model against ground-truth camera poses.

Conventions (all explicit):
  * COLMAP image pose (qvec,tvec) is WORLD->CAMERA: x_cam = R x_world + t.
    Camera centre C = -R^T t; camera-to-world c2w = [R^T | C]. Camera axes are
    OpenCV-style: +x right, +y down, +z forward (viewing direction).
  * Internally everything is camera-to-world with OpenCV axes ("cv-c2w").
  * GT as COLMAP images.txt (or a model dir): w2c -> cv-c2w as above.
  * GT as JSON {image_name: 4x4 camera-to-world}: the axis convention of the
    camera frame MUST be stated with --gt-camera-convention:
      opencv : x right, y down, z forward (used as-is)
      opengl : x right, y up,  z backward (Blender, NeRF/nerfstudio transforms.json)
               cv_c2w = gl_c2w @ diag(1,-1,-1,1)
  * Images are matched by basename (directory parts and nothing else ignored).
  * Alignment: Sim(3) est->GT fitted on matched camera centres (Umeyama);
    optional RANSAC. Metric units are those of the GT.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import colmap_io
from align import Sim3, umeyama, umeyama_ransac, residuals

GL_TO_CV = np.diag([1.0, -1.0, -1.0, 1.0])


def c2w_from_colmap(img: colmap_io.ImageRec) -> np.ndarray:
    return img.cam_to_world()


def convert_c2w_to_cv(c2w: np.ndarray, convention: str) -> np.ndarray:
    c2w = np.asarray(c2w, float)
    if convention == "opencv":
        return c2w
    if convention == "opengl":
        return c2w @ GL_TO_CV
    raise ValueError(f"unknown camera convention {convention!r}")


def load_colmap_poses(model_path) -> dict:
    """{basename: cv-c2w} from a model dir (bin or txt) or an images.txt file."""
    p = Path(model_path)
    if p.is_file():
        imgs = colmap_io._read_images_txt(p, False)
    else:
        imgs = colmap_io.read_images(p, False)
    out = {}
    for im in imgs.values():
        k = Path(im.name).name
        if k in out:
            raise ValueError(f"duplicate basename {k!r} in {model_path}; cannot match by filename")
        out[k] = c2w_from_colmap(im)
    return out


def load_gt_poses(path, camera_convention: str | None) -> dict:
    p = Path(path)
    if p.suffix == ".json":
        if camera_convention is None:
            raise ValueError("GT JSON needs --gt-camera-convention (opencv|opengl)")
        raw = json.load(open(p))
        out = {}
        for k, m in raw.items():
            m = np.array(m, float)
            if m.shape != (4, 4):
                raise ValueError(f"GT pose for {k!r} is not 4x4")
            b = Path(k).name
            if b in out:
                raise ValueError(f"duplicate basename {b!r} in GT")
            out[b] = convert_c2w_to_cv(m, camera_convention)
        return out
    return load_colmap_poses(p)


def rotation_angle_deg(R: np.ndarray) -> np.ndarray:
    """Angle of rotation matrices R (...,3,3) in degrees."""
    c = (np.trace(R, axis1=-2, axis2=-1) - 1.0) / 2.0
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def _stats(x: np.ndarray) -> dict:
    x = np.asarray(x, float)
    if x.size == 0:
        return {k: None for k in ("mean", "median", "rmse", "p95", "max")}
    return {"mean": float(x.mean()), "median": float(np.median(x)),
            "rmse": float(np.sqrt((x ** 2).mean())),
            "p95": float(np.percentile(x, 95)), "max": float(x.max())}


def evaluate(est: dict, gt: dict, with_scale: bool, extent: float | None,
             ransac_thresh: float | None = None, ransac_iters: int | None = None,
             seed: int | None = None) -> dict:
    """est, gt: {name: cv-c2w 4x4}. extent: scene extent in GT units, or None -> bbox
    diagonal of the GT camera centres of the matched images."""
    names = sorted(set(est) & set(gt))
    if len(names) < 3:
        raise ValueError(f"only {len(names)} images matched by filename; need >= 3")
    C_est = np.array([est[n][:3, 3] for n in names])
    C_gt = np.array([gt[n][:3, 3] for n in names])
    if ransac_thresh is not None:
        sim, mask = umeyama_ransac(C_est, C_gt, ransac_thresh, ransac_iters, seed, with_scale)
    else:
        sim, mask = umeyama(C_est, C_gt, with_scale), np.ones(len(names), bool)
    err = residuals(sim, C_est, C_gt)  # per-camera translation error, GT units
    if extent is None:
        extent = float(np.linalg.norm(C_gt.max(0) - C_gt.min(0)))
        extent_src = "bbox diagonal of matched GT camera centres"
    else:
        extent_src = "user-supplied"

    R_est = np.array([est[n][:3, :3] for n in names])
    R_gt = np.array([gt[n][:3, :3] for n in names])
    R_est_al = np.einsum("ij,njk->nik", sim.R, R_est)  # camera-to-world rotation in GT frame
    abs_rot = rotation_angle_deg(np.einsum("nji,njk->nik", R_gt, R_est_al))  # angle(R_gt^T R_est_al)
    # pairwise relative rotation error (alignment-independent):
    # dR_est(i,j) = R_est_i^T R_est_j ; error = angle(dR_gt^T dR_est)
    iu, ju = np.triu_indices(len(names), 1)
    dR_est = np.einsum("pji,pjk->pik", R_est[iu], R_est[ju])
    dR_gt = np.einsum("pji,pjk->pik", R_gt[iu], R_gt[ju])
    rel_rot = rotation_angle_deg(np.einsum("pji,pjk->pik", dR_gt, dR_est))

    ate = _stats(err)
    return {
        "sim3": sim.to_dict(),
        "with_scale": with_scale,
        "n_gt_images": len(gt), "n_est_images": len(est), "n_matched": len(names),
        "registered_fraction": len(names) / len(gt),
        "gt_not_in_model": sorted(set(gt) - set(est)),
        "model_not_in_gt": sorted(set(est) - set(gt)),
        "n_alignment_inliers": int(mask.sum()),
        "ate": {**ate, "units": "GT units (metres if GT is metric)"},
        "ate_percent_of_extent": {k: (None if v is None else 100.0 * v / extent) for k, v in ate.items()},
        "scene_extent": extent, "scene_extent_source": extent_src,
        "abs_rotation_error_deg": _stats(abs_rot),
        "relative_rotation_error_deg": {**_stats(rel_rot), "n_pairs": int(len(iu))},
        "per_image": {n: {"ate": float(e), "abs_rot_deg": float(r), "alignment_inlier": bool(m)}
                      for n, e, r, m in zip(names, err, abs_rot, mask)},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="COLMAP model dir (bin or txt) or images.txt")
    ap.add_argument("--gt", required=True, help="GT: COLMAP model dir / images.txt, or JSON name->4x4 c2w")
    ap.add_argument("--gt-camera-convention", choices=["opencv", "opengl"],
                    help="required for JSON GT")
    ap.add_argument("--with-scale", required=True, choices=["true", "false"],
                    help="false = rigid SE(3) only (use if the model is already metric)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--extent", type=float, help="scene extent in GT units")
    g.add_argument("--extent-from-gt-cameras", action="store_true",
                   help="extent = bbox diagonal of matched GT camera centres")
    ap.add_argument("--ransac-thresh", type=float, help="enable RANSAC alignment (GT units)")
    ap.add_argument("--ransac-iters", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.ransac_thresh is not None and (a.ransac_iters is None or a.seed is None):
        ap.error("--ransac-thresh requires --ransac-iters and --seed")
    res = evaluate(load_colmap_poses(a.model), load_gt_poses(a.gt, a.gt_camera_convention),
                   a.with_scale == "true", a.extent, a.ransac_thresh, a.ransac_iters, a.seed)
    json.dump(res, open(a.out, "w"), indent=2)
    print(json.dumps({k: res[k] for k in ("n_matched", "registered_fraction", "ate",
                                           "ate_percent_of_extent", "abs_rotation_error_deg",
                                           "relative_rotation_error_deg")}, indent=2))


if __name__ == "__main__":
    main()
