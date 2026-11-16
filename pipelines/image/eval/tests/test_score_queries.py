import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import score_queries as sq
from align import Sim3
from synth import rand_rot


def setup(seed=0):
    rng = np.random.default_rng(seed)
    true = Sim3(0.5, rand_rot(rng), np.array([1.0, 2.0, 3.0]))      # est -> ref (metres)
    gt = {f"obj{i}": rng.uniform(-2, 2, 3).tolist() for i in range(10)}
    gt.update({"ghost1": None, "ghost2": None, "ghost3": None, "ghost4": None})
    return true, gt


def make_preds(true, gt, errors_cm, rng):
    """predict each present query at gt + offset of exactly errors_cm[i] cm (in the est frame)."""
    inv = true.inverse(); p = {}
    for (q, v), e in zip([(q, v) for q, v in gt.items() if v is not None], errors_cm):
        d = rng.normal(size=3); d /= np.linalg.norm(d)
        p[q] = inv.apply((np.array(v) + d * e / 100.0)[None])[0].tolist()
    return p


def test_known_errors_hits_and_percentiles():
    true, gt = setup()
    errs = [0.5, 1, 2, 3, 4, 4.9, 10, 20, 50, 100.0]            # cm, exact by construction
    p = make_preds(true, gt, errs, np.random.default_rng(1))
    p.update({"ghost1": None, "ghost2": None, "ghost3": None, "ghost4": None})
    assert sq._pct(errs, 95) == pytest.approx(np.percentile(errs, 95)) and sq._pct(errs, 50) == pytest.approx(np.median(errs))
    r = sq.score(p, gt, true, gt_unit_cm=100.0, tol_cm=5.0)
    got = [r["per_query"][f"obj{i}"]["error_cm"] for i in range(10)]
    assert np.allclose(got, errs, atol=1e-9)
    assert r["top1_hit_rate"] == 0.6 and r["n_hits"] == 6          # 0.5,1,2,3,4,4.9 (<= 5)
    assert abs(r["median_error_cm"] - np.median(errs)) < 1e-9
    assert abs(r["p95_error_cm"] - np.percentile(errs, 95)) < 1e-9
    assert r["false_positive_rate"] == 0.0 and r["n_correct_rejections"] == 4


def test_nulls_false_positives_and_unscored():
    true, gt = setup(1)
    p = make_preds(true, gt, [1.0] * 10, np.random.default_rng(2))
    p["obj3"] = None; p["obj4"] = None                              # present but not found
    p.update({"ghost1": [0, 0, 0], "ghost2": None, "ghost3": [1, 1, 1], "ghost4": None, "extra": [9, 9, 9]})
    r = sq.score(p, gt, true, 100.0, 5.0)
    assert r["n_present"] == 10 and r["n_hits"] == 8 and abs(r["top1_hit_rate"] - 0.8) < 1e-12
    assert abs(r["answered_rate"] - 0.8) < 1e-12 and r["unanswered_present"] == ["obj3", "obj4"]
    assert r["false_positive_rate"] == 0.5 and r["false_positives"] == ["ghost1", "ghost3"]
    assert r["unscored_predictions"] == ["extra"]
    assert r["median_error_cm"] == pytest.approx(1.0) and r["n_answered_for_error_stats"] == 8
    assert r["p95_error_cm_misses_as_inf"] == float("inf")          # 20% unanswered -> p95 is inf


def test_unit_conversion_and_frame():
    true, gt = setup(2)
    gt_cm = {k: (None if v is None else (np.array(v) * 100).tolist()) for k, v in gt.items()}   # GT in cm
    p = make_preds(true, gt, [2.0] * 10, np.random.default_rng(3))
    p.update({f"ghost{i}": None for i in range(1, 5)})
    # same predictions, GT expressed in cm and sim3 scaled accordingly: errors identical
    true_cm = Sim3(true.scale * 100, true.R, true.t * 100)
    r = sq.score(p, gt_cm, true_cm, gt_unit_cm=1.0, tol_cm=5.0)
    assert all(abs(v["error_cm"] - 2.0) < 1e-9 for v in r["per_query"].values() if v["error_cm"] is not None)
    # identity sim3 on already-wrong frame gives a big error -> frame handling matters
    r2 = sq.score(p, gt, Sim3(1.0, np.eye(3), np.zeros(3)), 100.0, 5.0)
    assert r2["median_error_cm"] > 20


def test_missing_prediction_key_is_error_and_edge_cases():
    true, gt = setup(3)
    with pytest.raises(KeyError):
        sq.score({}, gt, true, 100.0, 5.0)
    r = sq.score({"a": None}, {"a": None}, true, 100.0, 5.0)           # only absent queries
    assert r["top1_hit_rate"] is None and r["false_positive_rate"] == 0.0 and r["median_error_cm"] is None
    r = sq.score({"a": [0, 0, 0]}, {"a": [0, 0, 0]}, Sim3(1.0, np.eye(3), np.zeros(3)), 100.0, 5.0)
    assert r["false_positive_rate"] is None and r["top1_hit_rate"] == 1.0


def test_cli(tmp_path):
    true, gt = setup(4)
    p = make_preds(true, gt, [1.0] * 10, np.random.default_rng(5)); p.update({f"ghost{i}": None for i in range(1, 5)})
    json.dump(p, open(tmp_path / "p.json", "w")); json.dump(gt, open(tmp_path / "g.json", "w"))
    json.dump({"sim3": true.to_dict()}, open(tmp_path / "s.json", "w"))
    r = subprocess.run([sys.executable, str(Path(sq.__file__)), "--predictions", str(tmp_path / "p.json"),
                        "--gt", str(tmp_path / "g.json"), "--sim3", str(tmp_path / "s.json"),
                        "--gt-unit-cm", "100", "--tolerance-cm", "5", "--out", str(tmp_path / "o.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.load(open(tmp_path / "o.json"))["top1_hit_rate"] == 1.0
