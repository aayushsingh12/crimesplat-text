#!/usr/bin/env python3
"""Second route: Sim(3) from hand-picked point pairs (e.g. CloudCompare 'Align (point pairs picking)').

Input CSV (header required):  name,src_x,src_y,src_z,dst_x,dst_y,dst_z
  src = the MODEL frame (COLMAP sparse / splat points you picked), dst = the SCAN frame (reference).
  Export the picked coordinates from CloudCompare (point list picking tool, or copy the two lists)
  and join them by name; one row per physical landmark.
Fits dst ~= scale * R @ src + t (Umeyama via align.py). Reports scale, rotation, per-pair residuals
(dst units), RMSE/max, leave-one-pair-out residuals (a bad pick shows up as a large LOO residual),
a collinearity/conditioning check, and optional distance checks:
  --check NAME_A NAME_B EXPECTED   (repeatable; EXPECTED in dst units, e.g. the table length 1.80 m)
For each check: distance in the picked dst points, distance after aligning the src points,
and the error of each vs EXPECTED. Output JSON has key "sim3" so cloud_error.py --sim3 can use it.
Units: whatever the scan frame is in (the dataset states none; metres is an assumption).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from align import umeyama, residuals


def read_pairs(path):
    names, src, dst = [], [], []
    for r in csv.DictReader(open(path)):
        names.append(r["name"])
        src.append([float(r[k]) for k in ("src_x", "src_y", "src_z")])
        dst.append([float(r[k]) for k in ("dst_x", "dst_y", "dst_z")])
    return names, np.array(src), np.array(dst)


def analyse(names, src, dst, with_scale, min_pairs, checks):
    n = len(names)
    if n < min_pairs:
        raise SystemExit(f"need >= {min_pairs} pairs, got {n}")
    if len(set(names)) != n:
        raise SystemExit("duplicate pair names")
    sim = umeyama(src, dst, with_scale)
    res = residuals(sim, src, dst)
    sv = np.linalg.svd(src - src.mean(0), compute_uv=False)
    loo = []
    for i in range(n):
        keep = [j for j in range(n) if j != i]
        if len(keep) < 3:
            loo.append(None); continue
        try:
            s_i = umeyama(src[keep], dst[keep], with_scale)
            loo.append(float(np.linalg.norm(dst[i] - s_i.apply(src[i:i + 1])[0])))
        except ValueError:
            loo.append(None)
    out = dict(n_pairs=n, with_scale=with_scale, sim3=sim.to_dict(), scale=sim.scale,
               rmse=float(np.sqrt((res ** 2).mean())), max_residual=float(res.max()),
               median_residual=float(np.median(res)),
               source_singular_values=sv.tolist(), conditioning_sv3_over_sv1=float(sv[2] / sv[0]),
               pairs=[dict(name=nm, residual=float(r), leave_one_out_residual=l) for nm, r, l in zip(names, res, loo)])
    idx = {nm: i for i, nm in enumerate(names)}
    ck = []
    for a, b, exp in checks:
        i, j = idx[a], idx[b]
        d_picked = float(np.linalg.norm(dst[i] - dst[j]))
        al = sim.apply(src[[i, j]]); d_aligned = float(np.linalg.norm(al[0] - al[1]))
        ck.append(dict(a=a, b=b, expected=exp, picked_scan_distance=d_picked, aligned_model_distance=d_aligned,
                       err_picked=d_picked - exp, err_aligned=d_aligned - exp,
                       err_aligned_pct=100 * (d_aligned / exp - 1)))
    out["checks"] = ck
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--with-scale", required=True, choices=["true", "false"])
    ap.add_argument("--min-pairs", type=int, required=True)
    ap.add_argument("--check", nargs=3, action="append", metavar=("NAME_A", "NAME_B", "EXPECTED"), default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    names, src, dst = read_pairs(a.pairs)
    checks = [(x, y, float(e)) for x, y, e in a.check]
    for x, y, _ in checks:
        if x not in names or y not in names:
            raise SystemExit(f"--check names must be in the CSV: {x}, {y}")
    out = analyse(names, src, dst, a.with_scale == "true", a.min_pairs, checks)
    json.dump(out, open(a.out, "w"), indent=2)
    print(json.dumps({k: out[k] for k in ("n_pairs", "scale", "rmse", "max_residual", "median_residual",
                                          "conditioning_sv3_over_sv1", "checks")}, indent=2))
    print("per-pair residual / leave-one-out:")
    for p in out["pairs"]:
        print(f"  {p['name']:20s} {p['residual']:.5g}  {p['leave_one_out_residual']}")


if __name__ == "__main__":
    main()
