#!/usr/bin/env python3
"""Marker-based error of a COLMAP reconstruction against measured ground truth.

ground_truth.json schema (units = whatever you state; all values in the same unit):
  {"units": "m",
   "markers":   {"3": [x,y,z], ...},          # OPTIONAL: marker CENTRES in the reference frame
   "distances": [{"a": 3, "b": 7, "distance": 0.512, "sigma": 0.002}, ...]}
                                              # measured centre-to-centre distances,
                                              # sigma = 1-sigma measurement uncertainty

Reported (est = triangulated marker centres from triangulate_markers.py, arbitrary scale):
  * sim3 (est -> reference), fitted by Umeyama on markers present in both files
    [needs >= 3 non-collinear markers with GT positions]; fit residuals per marker and
    RMSE; leave-one-out (LOO) residuals when >= 4 markers (fit residuals under-state error
    when there are few markers).
  * pair-distance error, three ways, because COLMAP has no metric scale:
      aligned : d_est * sim3.scale                 (scale from marker positions)
      loo     : d_est * s_(-k), s_(-k) = sum_{l!=k} d_est_l d_true_l / sum_{l!=k} d_est_l^2
                (scale fitted from all OTHER distances; honest out-of-sample absolute error;
                 needs >= 2 distances)
    each with abs error (reference units), % of true distance, and z = err / sigma.
  * scale-free check: for every two distances (k,l): ratio_est = d_est_k/d_est_l vs
    ratio_true = d_true_k/d_true_l; error% = 100 (ratio_est/ratio_true - 1). Needs no scale
    and no marker positions; needs >= 2 distances.
"""
from __future__ import annotations

import argparse
import itertools
import json

import numpy as np

from align import Sim3, umeyama, residuals


def _stats(x):
    x = np.asarray(x, float)
    if x.size == 0:
        return None
    return {"n": int(x.size), "mean_abs": float(np.abs(x).mean()), "median_abs": float(np.median(np.abs(x))),
            "rmse": float(np.sqrt((x ** 2).mean())), "max_abs": float(np.abs(x).max()),
            "signed_mean": float(x.mean())}


def evaluate(tri: dict, gt: dict, with_scale: bool) -> dict:
    est = {k: np.array(v["position"], float) for k, v in tri["markers"].items()}
    out = {"units": gt.get("units"), "n_markers_triangulated": len(est),
           "markers_rejected": tri.get("rejected", {})}

    # ---- Sim(3) from marker positions
    sim = None
    gtm = {str(k): np.array(v, float) for k, v in gt.get("markers", {}).items()}
    common = sorted(set(est) & set(gtm), key=int)
    out["markers_used_for_alignment"] = common
    out["markers_gt_not_triangulated"] = sorted(set(gtm) - set(est), key=int)
    if len(common) >= 3:
        src = np.array([est[k] for k in common]); dst = np.array([gtm[k] for k in common])
        sim = umeyama(src, dst, with_scale)
        r = residuals(sim, src, dst)
        out["sim3"] = sim.to_dict()
        out["alignment"] = {"per_marker_residual": dict(zip(common, map(float, r))),
                            "rmse": float(np.sqrt((r ** 2).mean())), "max": float(r.max())}
        if len(common) >= 4:
            loo = {}
            for i, k in enumerate(common):
                m = np.arange(len(common)) != i
                try:
                    s = umeyama(src[m], dst[m], with_scale)
                    loo[k] = float(np.linalg.norm(s.apply(src[i:i + 1])[0] - dst[i]))
                except ValueError:
                    loo[k] = None  # remaining markers collinear
            v = [x for x in loo.values() if x is not None]
            out["alignment"]["loo_residual"] = loo
            out["alignment"]["loo_rmse"] = float(np.sqrt(np.mean(np.square(v)))) if v else None
    else:
        out["sim3"] = None
        out["alignment"] = {"note": f"{len(common)} marker(s) with GT position; need >= 3 for Sim(3)"}

    # ---- pair distances
    rows = []
    for d in gt.get("distances", []):
        a, b = str(d["a"]), str(d["b"])
        if a in est and b in est:
            rows.append({"a": a, "b": b, "true": float(d["distance"]), "sigma": float(d["sigma"]),
                         "est": float(np.linalg.norm(est[a] - est[b]))})
    out["distances_not_evaluated"] = [d for d in gt.get("distances", [])
                                      if str(d["a"]) not in est or str(d["b"]) not in est]
    de = np.array([r["est"] for r in rows]); dt = np.array([r["true"] for r in rows])
    for i, r in enumerate(rows):
        if sim is not None:
            r["aligned_est"] = r["est"] * sim.scale
            r["aligned_err"] = r["aligned_est"] - r["true"]
            r["aligned_err_pct"] = 100 * r["aligned_err"] / r["true"]
            r["aligned_err_z"] = r["aligned_err"] / r["sigma"]
        if len(rows) >= 2:
            m = np.arange(len(rows)) != i
            s = float((de[m] * dt[m]).sum() / (de[m] ** 2).sum())
            r["loo_scale"] = s
            r["loo_est"] = r["est"] * s
            r["loo_err"] = r["loo_est"] - r["true"]
            r["loo_err_pct"] = 100 * r["loo_err"] / r["true"]
            r["loo_err_z"] = r["loo_err"] / r["sigma"]
    out["distance_pairs"] = rows
    out["distance_summary"] = {}
    if sim is not None and rows:
        out["distance_summary"]["aligned_abs"] = _stats([r["aligned_err"] for r in rows])
        out["distance_summary"]["aligned_pct"] = _stats([r["aligned_err_pct"] for r in rows])
    if len(rows) >= 2:
        out["distance_summary"]["loo_abs"] = _stats([r["loo_err"] for r in rows])
        out["distance_summary"]["loo_pct"] = _stats([r["loo_err_pct"] for r in rows])
        rat = []
        for k, l in itertools.combinations(range(len(rows)), 2):
            rat.append({"pair": [k, l],
                        "err_pct": 100 * ((de[k] / de[l]) / (dt[k] / dt[l]) - 1)})
        out["scale_free_ratio_check"] = {"n_ratios": len(rat), "err_pct": _stats([x["err_pct"] for x in rat]),
                                         "ratios": rat}
        out["scale_free_ratio_check"]["global_scale_from_distances"] = float((de * dt).sum() / (de ** 2).sum())
        if sim is not None:
            out["scale_free_ratio_check"]["scale_from_marker_alignment"] = sim.scale
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--triangulated", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--with-scale", required=True, choices=["true", "false"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = evaluate(json.load(open(a.triangulated)), json.load(open(a.gt)), a.with_scale == "true")
    json.dump(res, open(a.out, "w"), indent=2)
    print(json.dumps({k: res.get(k) for k in ("alignment", "distance_summary")}, indent=2))
    if "scale_free_ratio_check" in res:
        print("ratio error %:", res["scale_free_ratio_check"]["err_pct"])


if __name__ == "__main__":
    main()
