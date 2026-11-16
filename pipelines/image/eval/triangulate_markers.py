#!/usr/bin/env python3
"""Triangulate ArUco marker corners/centres from a COLMAP sparse model + detections.

Per marker id:
  * views = registered images (matched by basename) in which the marker was detected;
  * robust selection: every PAIR of views triangulates the 4 corners (linear DLT on
    undistorted normalised rays); a view is an inlier if its mean corner reprojection
    error (full camera model incl. distortion, in pixels) is < --reproj-thresh-px and
    all corners are in front of the camera; the pair with most inliers (ties: lowest
    total error) wins, ties between equal pairs broken by pair order (deterministic);
  * refit: DLT on all inlier views, then nonlinear least squares on pixel
    reprojection error (scipy least_squares, per corner);
  * the marker position is the MEAN OF THE FOUR TRIANGULATED CORNERS (= marker centre
    for a square marker). ground_truth.json positions must refer to marker centres.
  * markers with fewer than --min-views inlier views are rejected (reason recorded).

Detection image size is checked against the camera width/height in the model; a
mismatch (e.g. detecting on raw rather than the EXIF-corrected images) is an error.

Output JSON:
  {"markers": {id: {"position":[x,y,z], "corners":[[..]x4], "n_views":int, "views":[names],
                    "outlier_views":[names], "reproj_rms_px":f, "reproj_max_px":f,
                    "per_view_reproj_px":{name:f}, "side_lengths":[4 floats]}},
   "rejected": {id: reason}, "params": {...}}
Units: model units (COLMAP is up to an arbitrary scale).
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

import colmap_io as ci


def dlt(Rs, ts, xn):
    """Linear triangulation of one point. Rs (V,3,3), ts (V,3), xn (V,2) normalised coords."""
    A = []
    for R, t, (x, y) in zip(Rs, ts, xn):
        P = np.c_[R, t]
        A.append(x * P[2] - P[0])
        A.append(y * P[2] - P[1])
    _, _, Vt = np.linalg.svd(np.array(A))
    X = Vt[-1]
    return X[:3] / X[3]


class View:
    def __init__(self, name, cam, R, t, uv):
        self.name, self.cam, self.R, self.t, self.uv = name, cam, R, t, np.asarray(uv, float)
        self.xn = ci.undistort_to_normalized(cam, self.uv)

    def reproj(self, X4):
        uv, z = ci.project(self.cam, self.R, self.t, X4)
        return np.linalg.norm(uv - self.uv, axis=1), z


def _tri_corners(views):
    Rs = [v.R for v in views]; ts = [v.t for v in views]
    return np.array([dlt(Rs, ts, [v.xn[k] for v in views]) for k in range(4)])


def _view_err(v, X4):
    e, z = v.reproj(X4)
    return (e.mean() if (z > 0).all() else np.inf), e


def _refine(views, X4):
    out = []
    for k in range(4):
        def res(X):
            r = []
            for v in views:
                uv, _ = ci.project(v.cam, v.R, v.t, X[None])
                r.extend(uv[0] - v.uv[k])
            return r
        out.append(least_squares(res, X4[k], method="lm").x)
    return np.array(out)


def triangulate_marker(views, thresh_px, min_views):
    """views: list[View]. Returns (result dict) or raises ValueError(reason)."""
    if len(views) < min_views:
        raise ValueError(f"seen in only {len(views)} registered image(s) < min_views={min_views}")
    best = None
    for i, j in itertools.combinations(range(len(views)), 2):
        X4 = _tri_corners([views[i], views[j]])
        errs = np.array([_view_err(v, X4)[0] for v in views])
        inl = errs < thresh_px
        key = (int(inl.sum()), -float(errs[inl].sum()))
        if best is None or key > best[0]:
            best = (key, inl)
    inl = best[1]
    if inl.sum() < min_views:
        raise ValueError(f"only {int(inl.sum())} view(s) agree within {thresh_px}px < min_views={min_views}")
    use = [v for v, k in zip(views, inl) if k]
    X4 = _refine(use, _tri_corners(use))
    errs = np.array([_view_err(v, X4)[0] for v in views])      # re-assess after refinement
    inl2 = errs < thresh_px
    if inl2.sum() >= min_views and (inl2 != inl).any():
        use = [v for v, k in zip(views, inl2) if k]
        X4 = _refine(use, _tri_corners(use)); inl = inl2
        errs = np.array([_view_err(v, X4)[0] for v in views])
    allres = np.concatenate([_view_err(v, X4)[1] for v, k in zip(views, inl) if k])
    sides = [float(np.linalg.norm(X4[k] - X4[(k + 1) % 4])) for k in range(4)]
    return {"position": X4.mean(0).tolist(), "corners": X4.tolist(),
            "n_views": int(inl.sum()),
            "views": [v.name for v, k in zip(views, inl) if k],
            "outlier_views": [v.name for v, k in zip(views, inl) if not k],
            "reproj_rms_px": float(np.sqrt((allres ** 2).mean())), "reproj_max_px": float(allres.max()),
            "per_view_reproj_px": {v.name: float(e) for v, e, k in zip(views, errs, inl) if k},
            "side_lengths": sides}


def run(model_dir, det, thresh_px, min_views):
    if min_views < 2:
        raise ValueError("min_views must be >= 2 to triangulate")
    cams = ci.read_cameras(model_dir)
    imgs = {Path(i.name).name: i for i in ci.read_images(model_dir, False).values()}
    per_marker = {}
    for name, found in det["detections"].items():
        if name not in imgs:
            continue
        im = imgs[name]
        cam = cams[im.camera_id]
        sz = det.get("image_sizes", {}).get(name)
        if sz is not None and [cam.width, cam.height] != list(sz):
            raise ValueError(f"{name}: detection image size {sz} != COLMAP camera size "
                             f"{[cam.width, cam.height]} (detected on different pixels than COLMAP used?)")
        for mid, corners in found.items():
            per_marker.setdefault(mid, []).append(View(name, cam, im.R, im.tvec, corners))
    out = {"markers": {}, "rejected": {},
           "params": {"reproj_thresh_px": thresh_px, "min_views": min_views}}
    all_ids = {m for f in det["detections"].values() for m in f}
    for mid in sorted(all_ids, key=lambda s: int(s)):
        views = per_marker.get(mid, [])
        try:
            out["markers"][mid] = triangulate_marker(views, thresh_px, min_views)
        except ValueError as e:
            out["rejected"][mid] = str(e)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="COLMAP sparse model dir (bin or txt)")
    ap.add_argument("--detections", required=True, help="output of detect_markers.py")
    ap.add_argument("--reproj-thresh-px", type=float, required=True)
    ap.add_argument("--min-views", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = run(a.model, json.load(open(a.detections)), a.reproj_thresh_px, a.min_views)
    json.dump(res, open(a.out, "w"), indent=2)
    for m, r in res["markers"].items():
        print(f"marker {m}: {r['n_views']} views, rms {r['reproj_rms_px']:.3f}px, pos {np.round(r['position'], 4).tolist()}")
    for m, why in res["rejected"].items():
        print(f"marker {m}: REJECTED ({why})")


if __name__ == "__main__":
    main()
