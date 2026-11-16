#!/usr/bin/env python3
"""Cloud-to-reference error of an estimated point cloud against a reference PLY/mesh.

Inputs
  estimated : COLMAP model dir (points3D) OR a PLY (vertices used: splat centres,
              depth-derived points, ...).
  reference : PLY point cloud, or PLY mesh (has faces). A mesh is turned into
              --mesh-samples surface points, area-weighted, seeded; distances are
              then nearest-SAMPLE distances (a discretisation error of order
              the sample spacing; use enough samples).

Alignment (est -> reference frame), exactly one of
  --sim3 FILE : Sim(3) JSON ({"scale","R","t"} or a file with key "sim3", e.g. the
                output of pose_error.py). Use this whenever GT camera poses exist.
  --icp       : trimmed point-to-point Sim(3) ICP (--with-scale chooses Sim(3)/SE(3)).
                COARSE INITIALISATION (documented, deterministic):
                  1. translate: estimated centroid -> reference centroid;
                  2. scale (only if --with-scale true): ratio of RMS distances to the
                     centroids (reference / estimated);
                  3. rotate: align PCA axes (eigenvectors of the covariance, sorted by
                     eigenvalue); the 4 proper sign combinations are each refined by
                     ICP and the one with the lowest trimmed RMSE is kept.
                Known failure modes: near-isotropic shapes (PCA axes ill-defined),
                strong partial overlap (centroid/scale biased), gross symmetry. If the
                result looks wrong, supply --sim3 or --init-sim3 instead.
  --init-sim3 FILE (optional with --icp): replaces the PCA initialisation.

Metrics (d = nearest-neighbour Euclidean distance after alignment)
  accuracy     : d(est_i -> reference)   mean/median/RMSE/p95, fraction <= each threshold
  completeness : d(ref_j -> estimated)   mean/median/RMSE/p95, fraction <= each threshold
  fscore(tau)  : 2PR/(P+R) with P=accuracy fraction, R=completeness fraction at tau
Thresholds, trim fraction, iteration cap, convergence tolerance, seed: all explicit.
Units are those of the reference.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from plyfile import PlyData
from scipy.spatial import cKDTree

import colmap_io
from align import Sim3, umeyama


def read_ply(path):
    """Returns (vertices (N,3) float64, faces (M,3) int or None)."""
    ply = PlyData.read(str(path))
    v = ply["vertex"]
    verts = np.stack([np.asarray(v["x"]), np.asarray(v["y"]), np.asarray(v["z"])], 1).astype(np.float64)
    faces = None
    if "face" in ply:
        f = ply["face"]
        name = "vertex_indices" if "vertex_indices" in f.data.dtype.names else f.data.dtype.names[0]
        tri = []
        for row in f[name]:
            row = np.asarray(row)
            for k in range(1, len(row) - 1):  # fan-triangulate polygons
                tri.append((row[0], row[k], row[k + 1]))
        faces = np.array(tri, dtype=np.int64).reshape(-1, 3)
    return verts, faces


def sample_mesh(verts, faces, n, seed):
    tri = verts[faces]
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    if area.sum() <= 0:
        raise ValueError("mesh has zero total area")
    rng = np.random.default_rng(seed)
    fi = rng.choice(len(faces), n, p=area / area.sum())
    u, w = rng.random(n), rng.random(n)
    flip = u + w > 1
    u[flip], w[flip] = 1 - u[flip], 1 - w[flip]
    a, b, c = tri[fi, 0], tri[fi, 1], tri[fi, 2]
    return a + u[:, None] * (b - a) + w[:, None] * (c - a), float(area.sum())


def load_reference(path, mesh_samples, seed):
    v, f = read_ply(path)
    if f is not None and len(f):
        pts, area = sample_mesh(v, f, mesh_samples, seed)
        return pts, True, float(np.sqrt(area / mesh_samples))
    return v, False, None


def load_estimated(path):
    p = Path(path)
    if p.is_dir():
        return colmap_io.read_points3D(p).xyz
    return read_ply(p)[0]


# ------------------------------------------------------------------ ICP
def _icp(est, ref_tree, ref, init: Sim3, with_scale, trim, max_iters, tol):
    sim = init
    prev = np.inf
    rmse = np.inf
    for _ in range(max_iters):
        cur = sim.apply(est)
        d, idx = ref_tree.query(cur)
        k = max(3, int(np.ceil(trim * len(est))))
        keep = np.argsort(d)[:k]
        rmse = float(np.sqrt((d[keep] ** 2).mean()))
        if abs(prev - rmse) < tol:
            break
        prev = rmse
        sim = umeyama(est[keep], ref[idx[keep]], with_scale)
    return sim, rmse


def coarse_candidates(est, ref, with_scale):
    ce, cr = est.mean(0), ref.mean(0)
    xe, xr = est - ce, ref - cr
    s = np.sqrt((xr ** 2).sum(1).mean() / (xe ** 2).sum(1).mean()) if with_scale else 1.0
    _, Ve = np.linalg.eigh(np.cov(xe.T))
    _, Vr = np.linalg.eigh(np.cov(xr.T))
    for V in (Ve, Vr):  # eigenvector frames may be left-handed; make both proper
        if np.linalg.det(V) < 0:
            V[:, 2] *= -1
    cands = []
    for sg in ([1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]):
        R = Vr @ np.diag(sg) @ Ve.T
        cands.append(Sim3(s, R, cr - s * R @ ce))
    return cands


def icp_align(est, ref, with_scale, trim, max_iters, tol, init: Sim3 | None = None):
    """Returns (Sim3 est->ref, trimmed_rmse, init_used)."""
    tree = cKDTree(ref)
    cands = [init] if init is not None else coarse_candidates(est, ref, with_scale)
    best = None
    for c in cands:
        sim, rmse = _icp(est, tree, ref, c, with_scale, trim, max_iters, tol)
        if best is None or rmse < best[1]:
            best = (sim, rmse, c)
    return best


# -------------------------------------------------------------- metrics
def _dist_stats(d):
    return {"mean": float(d.mean()), "median": float(np.median(d)),
            "rmse": float(np.sqrt((d ** 2).mean())), "p95": float(np.percentile(d, 95))}


def cloud_metrics(est_aligned, ref, thresholds):
    d_acc = cKDTree(ref).query(est_aligned)[0]
    d_cmp = cKDTree(est_aligned).query(ref)[0]
    out = {"n_est": int(len(est_aligned)), "n_ref": int(len(ref)),
           "accuracy": _dist_stats(d_acc), "completeness": _dist_stats(d_cmp),
           "at_threshold": {}}
    for t in thresholds:
        P, R = float((d_acc <= t).mean()), float((d_cmp <= t).mean())
        out["at_threshold"][repr(float(t))] = {
            "accuracy_fraction": P, "completeness_fraction": R,
            "fscore": (2 * P * R / (P + R)) if P + R > 0 else 0.0}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--est", required=True, help="COLMAP model dir or PLY")
    ap.add_argument("--ref", required=True, help="reference PLY (cloud or mesh)")
    ap.add_argument("--mesh-samples", type=int, required=True, help="surface samples if --ref is a mesh")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--thresholds", type=float, nargs="+", required=True, help="reference units")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sim3")
    g.add_argument("--icp", action="store_true")
    ap.add_argument("--with-scale", choices=["true", "false"], help="required with --icp")
    ap.add_argument("--init-sim3")
    ap.add_argument("--icp-trim", type=float, help="fraction of closest correspondences kept, (0,1]")
    ap.add_argument("--icp-iters", type=int)
    ap.add_argument("--icp-tol", type=float, help="stop when |delta trimmed RMSE| < tol (reference units)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ref, was_mesh, spacing = load_reference(a.ref, a.mesh_samples, a.seed)
    est = load_estimated(a.est)
    res = {"reference_was_mesh": was_mesh,
           "reference_sample_spacing_approx": spacing,  # sqrt(area/n): discretisation floor of distances
           }
    if a.sim3:
        sim = Sim3.from_dict(json.load(open(a.sim3)))
        res["alignment"] = {"method": "given Sim(3)", "file": a.sim3}
    else:
        for k in ("with_scale", "icp_trim", "icp_iters", "icp_tol"):
            if getattr(a, k) is None:
                ap.error(f"--icp requires --{k.replace('_', '-')}")
        init = Sim3.from_dict(json.load(open(a.init_sim3))) if a.init_sim3 else None
        sim, rmse, used = icp_align(est, ref, a.with_scale == "true", a.icp_trim, a.icp_iters, a.icp_tol, init)
        res["alignment"] = {"method": "trimmed point-to-point ICP",
                            "init": "given" if init else "centroid+rms-scale+PCA (4 sign candidates)",
                            "trimmed_rmse": rmse}
    res["sim3"] = sim.to_dict()
    res["metrics"] = cloud_metrics(sim.apply(est), ref, a.thresholds)
    json.dump(res, open(a.out, "w"), indent=2)
    print(json.dumps({"alignment": res["alignment"], "scale": sim.scale, **res["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
