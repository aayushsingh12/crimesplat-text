import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

import colmap_io as ci
import detect_markers as dm
import triangulate_markers as tm
from synth import *

W, H, F = 1280, 960, 1000.0
HERE = Path(dm.__file__).parent


def cam_obj(model="SIMPLE_RADIAL"):
    p = {"SIMPLE_RADIAL": [F, W / 2, H / 2, -0.03], "OPENCV": [F, F * 1.01, W / 2, H / 2, -0.05, 0.01, 0.001, -0.001]}[model]
    return ci.Camera(1, model, W, H, np.array(p))


S = 0.2
MARKERS = {3: (-0.3, -0.2), 7: (0.1, -0.25), 12: (-0.1, 0.15), 20: (0.25, 0.1)}  # id -> (x0,y0) lower-left, plane z=0


def marker_world_corners(x0, y0):
    # unmirrored when viewed from +z with x right, y up: TL, TR, BR, BL
    return np.array([[x0, y0 + S, 0], [x0 + S, y0 + S, 0], [x0 + S, y0, 0], [x0, y0, 0]], float)


def render(cam, R, t, dictionary):
    img = np.full((H, W), 180, np.uint8)
    N = 200
    src = np.float32([[0, 0], [N, 0], [N, N], [0, N]])
    for mid, (x0, y0) in MARKERS.items():
        m = cv2.aruco.generateImageMarker(dictionary, mid, N)
        uv, z = ci.project(cam, R, t, marker_world_corners(x0, y0))
        assert (z > 0).all()
        Hm = cv2.getPerspectiveTransform(src, uv.astype(np.float32))
        warped = cv2.warpPerspective(m, Hm, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
        mask = cv2.warpPerspective(np.full((N, N), 255, np.uint8), Hm, (W, H), flags=cv2.INTER_NEAREST)
        img[mask > 0] = warped[mask > 0]
    return img


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    d = tmp_path_factory.mktemp("scene")
    cam = cam_obj()
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    w2c = ring_cameras(8, radius=0.9, height=1.3, target=(0, 0, 0))
    names = [f"v{i}.png" for i in range(8)]
    (d / "imgs").mkdir()
    for n, (R, t) in zip(names, w2c):
        cv2.imwrite(str(d / "imgs" / n), render(cam, R, t, dictionary))
    write_model_bin(d / "model", {1: cam}, make_images(w2c, names))
    return d, cam, w2c, names


def test_detect_counts_and_corner_accuracy(scene):
    d, cam, w2c, names = scene
    res = dm.detect_folder(d / "imgs", "DICT_4X4_50", "subpix")
    assert set(res["counts"]) == set(names)
    for n, (R, t) in zip(names, w2c):
        assert res["counts"][n] == len(MARKERS), (n, res["counts"][n])
        assert res["image_sizes"][n] == [W, H]
        for mid, (x0, y0) in MARKERS.items():
            true_uv, _ = ci.project(cam, R, t, marker_world_corners(x0, y0))
            got = np.array(res["detections"][n][str(mid)])
            # corner k must be the same physical corner in every view
            assert np.linalg.norm(got - true_uv, axis=1).max() < 1.5


def test_triangulation_end_to_end_recovers_marker_positions(scene):
    d, cam, w2c, names = scene
    det = dm.detect_folder(d / "imgs", "DICT_4X4_50", "subpix")
    res = tm.run(d / "model", det, thresh_px=2.0, min_views=3)
    assert res["rejected"] == {}
    for mid, (x0, y0) in MARKERS.items():
        truth = marker_world_corners(x0, y0)
        r = res["markers"][str(mid)]
        assert np.linalg.norm(np.array(r["position"]) - truth.mean(0)) < 0.005   # < 5 mm on a 20 cm marker
        assert np.abs(np.array(r["corners"]) - truth).max() < 0.01
        assert r["n_views"] == 8 and r["reproj_rms_px"] < 1.0
        assert max(abs(s - S) for s in r["side_lengths"]) < 0.01


def test_cli_roundtrip(scene, tmp_path):
    d, *_ = scene
    run = lambda *a: subprocess.run([sys.executable, *map(str, a)], capture_output=True, text=True)
    r1 = run(HERE / "detect_markers.py", "--images", d / "imgs", "--dictionary", "DICT_4X4_50",
             "--corner-refinement", "subpix", "--out", tmp_path / "det.json")
    assert r1.returncode == 0, r1.stderr
    r2 = run(HERE / "triangulate_markers.py", "--model", d / "model", "--detections", tmp_path / "det.json",
             "--reproj-thresh-px", "2", "--min-views", "3", "--out", tmp_path / "tri.json")
    assert r2.returncode == 0, r2.stderr
    assert len(json.load(open(tmp_path / "tri.json"))["markers"]) == 4


def test_wrong_dictionary_detects_nothing_and_bad_name_raises(scene):
    d, *_ = scene
    res = dm.detect_folder(d / "imgs", "DICT_6X6_250", "none")
    assert sum(res["counts"].values()) == 0
    with pytest.raises(ValueError):
        dm.get_dictionary("DICT_NOPE")


# ---- noise / outlier / rejection tests on synthetic detections (known truth) -----------
def synth_det(cam, w2c, names, rng, sigma, outlier=None, visible=None, size_override=None):
    det = {"image_sizes": {}, "detections": {}}
    for k, (n, (R, t)) in enumerate(zip(names, w2c)):
        det["image_sizes"][n] = size_override or [W, H]
        det["detections"][n] = {}
        for mid, (x0, y0) in MARKERS.items():
            if visible is not None and (mid, k) not in visible and mid in visible_ids(visible):
                continue
            uv, _ = ci.project(cam, R, t, marker_world_corners(x0, y0))
            uv = uv + rng.normal(scale=sigma, size=uv.shape)
            if outlier == (mid, k):
                uv = uv + [40, -25]
            det["detections"][n][str(mid)] = uv.tolist()
    return det


def visible_ids(v):
    return {m for m, _ in v}


@pytest.mark.parametrize("model", ["SIMPLE_RADIAL", "OPENCV"])
def test_triangulation_noise_scaling_and_distortion_models(tmp_path, model):
    cam = cam_obj(model)
    w2c = ring_cameras(10, radius=0.9, height=1.3, target=(0, 0, 0))
    names = [f"v{i}.png" for i in range(10)]
    write_model_bin(tmp_path / "m", {1: cam}, make_images(w2c, names))
    sigma = 0.5
    rng = np.random.default_rng(0)
    det = synth_det(cam, w2c, names, rng, sigma)
    res = tm.run(tmp_path / "m", det, thresh_px=3.0, min_views=3)
    errs = []
    for mid, (x0, y0) in MARKERS.items():
        r = res["markers"][str(mid)]
        errs.append(np.linalg.norm(np.array(r["position"]) - marker_world_corners(x0, y0).mean(0)))
        # reprojection rms ~ sigma*sqrt(2) (2 coords) * sqrt((n-dof)/n) ~ within 25%
        assert abs(r["reproj_rms_px"] - sigma * np.sqrt(2) * np.sqrt(1 - 3 / (2 * 10))) < 0.25 * sigma * np.sqrt(2)
    assert max(errs) < 0.004


def test_outlier_view_rejected_and_min_views(tmp_path):
    cam = cam_obj()
    w2c = ring_cameras(6, radius=0.9, height=1.3, target=(0, 0, 0))
    names = [f"v{i}.png" for i in range(6)]
    write_model_bin(tmp_path / "m", {1: cam}, make_images(w2c, names))
    rng = np.random.default_rng(1)
    det = synth_det(cam, w2c, names, rng, 0.0, outlier=(3, 2))
    res = tm.run(tmp_path / "m", det, thresh_px=2.0, min_views=3)
    r = res["markers"]["3"]
    assert r["outlier_views"] == ["v2.png"] and r["n_views"] == 5
    assert np.linalg.norm(np.array(r["position"]) - marker_world_corners(*MARKERS[3]).mean(0)) < 1e-6
    assert r["reproj_rms_px"] < 1e-6
    # marker 7 only seen in 2 views -> rejected at min_views=3, accepted at 2
    vis = {(7, 0), (7, 1)} | {(m, k) for m in MARKERS if m != 7 for k in range(6)}
    det2 = synth_det(cam, w2c, names, rng, 0.0, visible=vis)
    res2 = tm.run(tmp_path / "m", det2, thresh_px=2.0, min_views=3)
    assert "7" in res2["rejected"] and "7" not in res2["markers"] and len(res2["markers"]) == 3
    assert "7" in tm.run(tmp_path / "m", det2, thresh_px=2.0, min_views=2)["markers"]
    with pytest.raises(ValueError):
        tm.run(tmp_path / "m", det2, thresh_px=2.0, min_views=1)


def test_image_size_mismatch_is_error(tmp_path):
    cam = cam_obj()
    w2c = ring_cameras(4, radius=0.9, height=1.3, target=(0, 0, 0))
    names = [f"v{i}.png" for i in range(4)]
    write_model_bin(tmp_path / "m", {1: cam}, make_images(w2c, names))
    det = synth_det(cam, w2c, names, np.random.default_rng(0), 0.0, size_override=[H, W])
    with pytest.raises(ValueError, match="size"):
        tm.run(tmp_path / "m", det, thresh_px=2.0, min_views=3)
