#!/usr/bin/env python3
"""Score Phase-2 text-query localisation against ground truth.

predictions.json : {query: [x,y,z] | null}   -- in the COLMAP/splat (estimated) frame
queries_gt.json  : {query: [x,y,z] | null}   -- present query -> true position in the
                   reference frame; ABSENT query (object not in scene) -> null
--sim3           : Sim(3) est -> reference (from pose_error.py / marker_error.py / cloud_error.py;
                   {"scale","R","t"} or any file with a "sim3" key). Predictions are mapped
                   with x_ref = s R x_est + t BEFORE comparing.
--gt-unit-cm     : centimetres per reference unit (100 for metres, 1 for cm). Required.
--tolerance-cm   : top-1 hit tolerance. Required.

Every query in queries_gt.json MUST have a key in predictions.json (null = "not found");
a missing key is an error, not a silent null. Predictions for queries not in the GT are
listed under "unscored_predictions" and otherwise ignored.

Metrics, over PRESENT queries (n_present):
  error_cm_i          = gt_unit_cm * || sim3(pred_i) - gt_i ||        (only if pred_i != null)
  top1_hit_rate       = #(pred_i != null and error_cm_i <= tol) / n_present   (a null prediction
                        for a present query counts as a MISS in the denominator)
  answered_rate       = #(pred_i != null) / n_present
  median / p95 error  = over answered present queries only (reported with n); also
                        *_misses_as_inf: median / p95 with unanswered treated as +inf
Over ABSENT queries (n_absent):
  false_positive_rate = #(pred != null) / n_absent    (null = correct rejection); null if n_absent = 0
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from align import Sim3


def _pct(x, q):
    """Linear-interpolated percentile (numpy 'linear'), but inf-safe: any interpolation
    involving +inf gives +inf instead of nan."""
    x = np.sort(np.asarray(x, float))
    pos = (len(x) - 1) * q / 100.0
    lo, hi = int(np.floor(pos)), int(np.ceil(pos))
    f = pos - lo
    if f == 0 or x[lo] == x[hi]:
        return float(x[lo])
    if np.isinf(x[hi]) or np.isinf(x[lo]):
        return float("inf")
    return float(x[lo] + f * (x[hi] - x[lo]))


def score(preds: dict, gt: dict, sim: Sim3, gt_unit_cm: float, tol_cm: float) -> dict:
    missing = sorted(set(gt) - set(preds))
    if missing:
        raise KeyError(f"predictions missing for GT queries (use null for 'not found'): {missing}")
    present = [q for q, v in gt.items() if v is not None]
    absent = [q for q, v in gt.items() if v is None]
    per, errs, unanswered = {}, [], []
    for q in present:
        p = preds[q]
        if p is None:
            unanswered.append(q); per[q] = {"pred": None, "error_cm": None, "hit": False}
            continue
        p_ref = sim.apply(np.array(p, float)[None])[0]
        e = float(gt_unit_cm * np.linalg.norm(p_ref - np.array(gt[q], float)))
        errs.append(e)
        per[q] = {"pred_ref_frame": p_ref.tolist(), "error_cm": e, "hit": bool(e <= tol_cm)}
    errs_a = np.array(errs)
    hits = sum(v["hit"] for v in per.values())
    n_p = len(present)
    full = np.concatenate([errs_a, np.full(len(unanswered), np.inf)])
    fp = [q for q in absent if preds[q] is not None]
    return {
        "tolerance_cm": tol_cm, "n_present": n_p, "n_absent": len(absent),
        "top1_hit_rate": hits / n_p if n_p else None, "n_hits": hits,
        "answered_rate": len(errs) / n_p if n_p else None, "unanswered_present": unanswered,
        "median_error_cm": float(np.median(errs_a)) if errs else None,
        "p95_error_cm": float(np.percentile(errs_a, 95)) if errs else None,
        "n_answered_for_error_stats": len(errs),
        "median_error_cm_misses_as_inf": _pct(full, 50) if n_p else None,
        "p95_error_cm_misses_as_inf": _pct(full, 95) if n_p else None,
        "false_positive_rate": len(fp) / len(absent) if absent else None,
        "false_positives": fp, "n_correct_rejections": len(absent) - len(fp),
        "unscored_predictions": sorted(set(preds) - set(gt)),
        "per_query": per,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--sim3", required=True)
    ap.add_argument("--gt-unit-cm", type=float, required=True)
    ap.add_argument("--tolerance-cm", type=float, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = score(json.load(open(a.predictions)), json.load(open(a.gt)),
                Sim3.from_dict(json.load(open(a.sim3))), a.gt_unit_cm, a.tolerance_cm)
    json.dump(res, open(a.out, "w"), indent=2)
    print(json.dumps({k: v for k, v in res.items() if k != "per_query"}, indent=2))


if __name__ == "__main__":
    main()
