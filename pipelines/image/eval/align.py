#!/usr/bin/env python3
"""Sim(3) alignment (Umeyama 1991) between corresponding 3D point sets.

Model:  dst_i ~= scale * R @ src_i + t       (R proper rotation, det = +1)

No default tolerances: every threshold / iteration count / seed is an
explicit argument.
"""
from __future__ import annotations

import argparse
import dataclasses
import json

import numpy as np


@dataclasses.dataclass
class Sim3:
    scale: float
    R: np.ndarray  # (3,3)
    t: np.ndarray  # (3,)

    def apply(self, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, dtype=float)
        return self.scale * pts @ self.R.T + self.t

    def inverse(self) -> "Sim3":
        s = 1.0 / self.scale
        R = self.R.T
        return Sim3(s, R, -s * R @ self.t)

    def matrix(self) -> np.ndarray:
        M = np.eye(4)
        M[:3, :3] = self.scale * self.R
        M[:3, 3] = self.t
        return M

    def to_dict(self) -> dict:
        return {"scale": float(self.scale), "R": self.R.tolist(), "t": self.t.tolist()}

    @staticmethod
    def from_dict(d: dict) -> "Sim3":
        if "sim3" in d:  # accept the output files of pose_error.py / marker_error.py
            d = d["sim3"]
        return Sim3(float(d["scale"]), np.array(d["R"], float), np.array(d["t"], float))


def residuals(sim: Sim3, src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Euclidean distance |dst_i - sim(src_i)| per correspondence."""
    return np.linalg.norm(np.asarray(dst, float) - sim.apply(src), axis=1)


def umeyama(src: np.ndarray, dst: np.ndarray, with_scale: bool) -> Sim3:
    """Least-squares Sim(3) (or SE(3) if with_scale is False) mapping src -> dst.

    Needs >= 3 non-collinear points (rank of the centred source cloud >= 2;
    numpy's default matrix_rank tolerance, i.e. machine-eps based).
    """
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError(f"src/dst must both be (N,3); got {src.shape} and {dst.shape}")
    n = len(src)
    if n < 3:
        raise ValueError(f"need >= 3 correspondences, got {n}")
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    if np.linalg.matrix_rank(xs) < 2 or np.linalg.matrix_rank(xd) < 2:
        raise ValueError("degenerate configuration (points collinear / coincident)")
    cov = xd.T @ xs / n
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1.0
    R = U @ S @ Vt
    if with_scale:
        var_s = (xs ** 2).sum() / n
        scale = float(np.trace(np.diag(D) @ S) / var_s)
    else:
        scale = 1.0
    t = mu_d - scale * R @ mu_s
    return Sim3(scale, R, t)


def umeyama_ransac(src, dst, inlier_thresh: float, n_iters: int, seed: int,
                   with_scale: bool, min_inliers: int = 3):
    """RANSAC around umeyama(). Minimal sample = 3 points.

    inlier_thresh is in dst units. Final model is refit on the best inlier set.
    Returns (Sim3, inlier_mask). Raises RuntimeError if no model with
    >= min_inliers inliers is found.
    """
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    n = len(src)
    if n < 3:
        raise ValueError(f"need >= 3 correspondences, got {n}")
    rng = np.random.default_rng(seed)
    best_mask, best_cnt, best_err = None, -1, np.inf
    for _ in range(n_iters):
        idx = rng.choice(n, 3, replace=False)
        try:
            sim = umeyama(src[idx], dst[idx], with_scale)
        except ValueError:
            continue
        r = residuals(sim, src, dst)
        mask = r < inlier_thresh
        cnt = int(mask.sum())
        err = float((r[mask] ** 2).sum())
        if cnt > best_cnt or (cnt == best_cnt and err < best_err):
            best_mask, best_cnt, best_err = mask, cnt, err
    if best_mask is None or best_cnt < max(3, min_inliers):
        raise RuntimeError(f"RANSAC found no model with >= {max(3, min_inliers)} inliers")
    sim = umeyama(src[best_mask], dst[best_mask], with_scale)
    # one reassignment pass with the refit model
    mask = residuals(sim, src, dst) < inlier_thresh
    if mask.sum() >= 3:
        sim = umeyama(src[mask], dst[mask], with_scale)
        best_mask = mask
    return sim, best_mask


def _load_pts(path):
    a = np.array(json.load(open(path)), float)
    return a


def main():
    ap = argparse.ArgumentParser(description="Sim(3) Umeyama alignment of two (N,3) JSON point lists.")
    ap.add_argument("--src", required=True, help="JSON [[x,y,z],...]")
    ap.add_argument("--dst", required=True, help="JSON [[x,y,z],...], same order")
    ap.add_argument("--with-scale", required=True, choices=["true", "false"])
    ap.add_argument("--ransac-thresh", type=float, help="enable RANSAC; inlier threshold in dst units")
    ap.add_argument("--ransac-iters", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src, dst = _load_pts(a.src), _load_pts(a.dst)
    ws = a.with_scale == "true"
    mask = None
    if a.ransac_thresh is not None:
        if a.ransac_iters is None or a.seed is None:
            ap.error("--ransac-thresh requires --ransac-iters and --seed")
        sim, mask = umeyama_ransac(src, dst, a.ransac_thresh, a.ransac_iters, a.seed, ws)
    else:
        sim = umeyama(src, dst, ws)
    r = residuals(sim, src, dst)
    out = {"sim3": sim.to_dict(), "residuals": r.tolist(),
           "rmse": float(np.sqrt((r ** 2).mean())),
           "inliers": None if mask is None else mask.tolist()}
    json.dump(out, open(a.out, "w"), indent=2)
    print(f"scale={sim.scale:.6g} rmse={out['rmse']:.6g}")


if __name__ == "__main__":
    main()
