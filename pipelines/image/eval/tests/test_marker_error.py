import itertools
import numpy as np
import pytest

import marker_error as me
from align import Sim3
from synth import rand_rot

GT_POS = {"1": [0, 0, 0], "2": [1.0, 0, 0], "3": [1.0, 0.8, 0], "4": [0, 0.8, 0.1], "5": [0.5, 0.4, 0.3], "6": [0.2, 0.7, 0.05]}


def build(sigma_pos=0.0, true=None, seed=0, dist_scale_err=None):
    rng = np.random.default_rng(seed)
    true = true or Sim3(3.2, rand_rot(rng), np.array([5.0, 1.0, -2.0]))     # est -> ref
    inv = true.inverse()
    tri = {"markers": {k: {"position": (inv.apply(np.array([v])) + rng.normal(scale=sigma_pos, size=3))[0].tolist()}
                       for k, v in GT_POS.items()}}
    dists = []
    for a, b in [("1", "2"), ("2", "3"), ("1", "4"), ("3", "5"), ("6", "5")]:
        d = float(np.linalg.norm(np.array(GT_POS[a]) - np.array(GT_POS[b])))
        if dist_scale_err and (a, b) in dist_scale_err:
            d *= dist_scale_err[(a, b)]                    # a wrong measurement
        dists.append({"a": int(a), "b": int(b), "distance": d, "sigma": 0.002})
    return tri, {"units": "m", "markers": GT_POS, "distances": dists}, true


def test_exact_data_zero_errors():
    tri, gt, true = build()
    r = me.evaluate(tri, gt, True)
    assert abs(r["sim3"]["scale"] - true.scale) < 1e-9
    assert r["alignment"]["rmse"] < 1e-9 and r["alignment"]["loo_rmse"] < 1e-9
    s = r["distance_summary"]
    assert s["aligned_abs"]["max_abs"] < 1e-9 and s["loo_abs"]["max_abs"] < 1e-9
    assert r["scale_free_ratio_check"]["err_pct"]["max_abs"] < 1e-9
    assert abs(r["scale_free_ratio_check"]["global_scale_from_distances"] - true.scale) < 1e-9


def test_noise_level_and_loo_larger_than_fit():
    sig_ref = 0.01                 # desired noise in reference units
    sig_est = sig_ref / 3.2        # noise is added in est units; est->ref scale is 3.2
    errs_fit, errs_loo = [], []
    for seed in range(40):
        tri, gt, true = build(sigma_pos=sig_est, seed=seed)
        r = me.evaluate(tri, gt, True)
        errs_fit.append(r["alignment"]["rmse"]); errs_loo.append(r["alignment"]["loo_rmse"])
    # LOO error must exceed in-sample fit error (fit is optimistic with 6 markers)
    assert np.mean(errs_loo) > np.mean(errs_fit)
    # in-sample rmse ~ sigma_ref*sqrt(3)*sqrt((n-~7/3)/n) ; allow 30%
    exp = sig_ref * np.sqrt(3) * np.sqrt(1 - 7 / (3 * 6))
    assert abs(np.mean(errs_fit) - exp) < 0.3 * exp


def test_bad_measurement_is_flagged_by_loo_and_ratios():
    tri, gt, _ = build(dist_scale_err={("3", "5"): 1.05})   # measured distance is 5% too long
    r = me.evaluate(tri, gt, True)
    bad = [p for p in r["distance_pairs"] if (p["a"], p["b"]) == ("3", "5")][0]
    # est distance is the true geometry -> reconstruction is 5% SHORT relative to the (wrong) measurement
    assert abs(bad["aligned_err_pct"] - 100 * (1 / 1.05 - 1)) < 1e-6
    assert abs(bad["loo_err_pct"]) > 3.5
    ratios = [x["err_pct"] for x in r["scale_free_ratio_check"]["ratios"]]
    assert max(abs(x) for x in ratios) > 4.0
    assert r["distance_summary"]["loo_pct"]["max_abs"] > 3.5


def test_scale_error_in_reconstruction_shows_in_distances_not_ratios():
    # a reconstruction with a UNIFORM scale error is invisible to ratios (scale-free) and to LOO
    tri, gt, _ = build()
    for v in tri["markers"].values():
        v["position"] = (np.array(v["position"]) * 1.1).tolist()
    r = me.evaluate(tri, gt, True)
    assert r["scale_free_ratio_check"]["err_pct"]["max_abs"] < 1e-9
    assert r["distance_summary"]["loo_abs"]["max_abs"] < 1e-9


def test_distances_only_and_missing_markers():
    tri, gt, true = build()
    gt_d = {"units": "m", "distances": gt["distances"]}
    r = me.evaluate(tri, gt_d, True)
    assert r["sim3"] is None and "aligned_abs" not in r["distance_summary"]
    assert r["distance_summary"]["loo_abs"]["max_abs"] < 1e-9
    del tri["markers"]["5"]
    r = me.evaluate(tri, gt, True)
    assert len(r["distance_pairs"]) == 3 and len(r["distances_not_evaluated"]) == 2
    assert r["markers_gt_not_triangulated"] == ["5"]
    # fewer than 3 positioned markers -> no Sim(3), no crash
    tri["markers"] = {k: tri["markers"][k] for k in ("1", "2")}
    assert me.evaluate(tri, gt, True)["sim3"] is None
