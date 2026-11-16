import json
import numpy as np
import pytest

import colmap_io as ci
import pose_error as pe
from align import Sim3
from synth import *


def cam():
    return {1: ci.Camera(1, "SIMPLE_RADIAL", 640, 480, np.array([500.0, 320.0, 240.0, -0.05]))}


def test_quaternion_roundtrip():
    rng = np.random.default_rng(0)
    for _ in range(50):
        R = rand_rot(rng)
        q = ci.rotmat_to_qvec(R)
        assert np.abs(ci.qvec_to_rotmat(q) - R).max() < 1e-12


def test_text_and_binary_readers_agree(tmp_path):
    rng = np.random.default_rng(1)
    imgs = make_images(ring_cameras(6))
    for k, im in enumerate(imgs):
        n = 0 if k == 2 else 4  # image 2 has zero keypoints (blank line in images.txt)
        im.xys = rng.uniform(0, 400, (n, 2)); im.point3D_ids = np.array([k, -1, k + 1, 7][:n], np.int64)
    pts = ci.Points3D(np.arange(3, dtype=np.int64), rng.normal(size=(3, 3)),
                      rng.integers(0, 255, (3, 3)).astype(np.uint8), rng.uniform(size=3))
    write_model_txt(tmp_path / "t", cam(), imgs, pts)
    write_model_bin(tmp_path / "b", cam(), imgs, pts)
    for fmt, d in (("txt", "t"), ("bin", "b")):
        assert ci.detect_format(tmp_path / d) == fmt
        ims = ci.read_images(tmp_path / d, True)
        assert len(ims) == 6
        for im in imgs:
            r = ims[im.image_id]
            assert r.name == im.name
            assert np.abs(r.qvec - im.qvec).max() < 1e-12 and np.abs(r.tvec - im.tvec).max() < 1e-12
            n = 0 if im.xys is None else len(im.xys)
            assert len(r.xys) == n
            if n:
                assert np.abs(r.xys - im.xys).max() < 1e-12 and (r.point3D_ids == im.point3D_ids).all()
        c = ci.read_cameras(tmp_path / d)[1]
        assert c.model == "SIMPLE_RADIAL" and np.abs(c.params - cam()[1].params).max() == 0
        p = ci.read_points3D(tmp_path / d)
        assert np.abs(p.xyz - pts.xyz).max() < 1e-12 and (p.rgb == pts.rgb).all()


def test_camera_center_and_c2w():
    R, t = look_at_w2c([3, 1, 2], [0, 0, 0])
    im = ci.ImageRec(1, ci.rotmat_to_qvec(R), t, 1, "a.jpg")
    assert np.abs(im.center - [3, 1, 2]).max() < 1e-12
    M = im.cam_to_world()
    assert np.abs(M[:3, 3] - [3, 1, 2]).max() < 1e-12
    fwd = M[:3, 2]  # +z camera axis in world = viewing direction
    expect = -np.array([3, 1, 2]) / np.linalg.norm([3, 1, 2])
    assert np.abs(fwd - expect).max() < 1e-12


def test_project_roundtrip_with_distortion():
    c = ci.Camera(1, "OPENCV", 640, 480, np.array([500, 510, 320, 240, -0.1, 0.02, 0.001, -0.002]))
    R, t = look_at_w2c([3, 1, 2], [0, 0, 0])
    X = np.random.default_rng(0).normal(size=(20, 3)) * 0.5
    uv, z = ci.project(c, R, t, X)
    assert (z > 0).all()
    xn = ci.undistort_to_normalized(c, uv)
    Xc = X @ R.T + t
    assert np.abs(xn - Xc[:, :2] / Xc[:, 2:3]).max() < 1e-8


def test_opengl_to_opencv_conversion():
    # an OpenGL camera (-z forward, +y up) at C looking at the origin
    C = np.array([3.0, 1.0, 2.0])
    f = -C / np.linalg.norm(C)                       # viewing direction
    up = np.array([0, 0, 1.0])
    x = np.cross(f, up); x /= np.linalg.norm(x)      # right
    y = np.cross(x, f)                               # up
    gl = np.eye(4); gl[:3, :3] = np.stack([x, y, -f], 1); gl[:3, 3] = C
    cv = pe.convert_c2w_to_cv(gl, "opengl")
    # same position, +z axis is the viewing direction, +y points down
    assert np.abs(cv[:3, 3] - C).max() < 1e-12
    assert np.abs(cv[:3, 2] - f).max() < 1e-12 and np.abs(cv[:3, 1] + y).max() < 1e-12
    assert abs(np.linalg.det(cv[:3, :3]) - 1) < 1e-12
    # projecting the origin must give the principal point (it is on the optical axis)
    w2c = np.linalg.inv(cv)
    p = w2c[:3, :3] @ np.zeros(3) + w2c[:3, 3]
    assert abs(p[0]) < 1e-12 and abs(p[1]) < 1e-12 and p[2] > 0
    # a point to the camera's right projects to +u (x right), and a point above to -v (y down)
    for pt, sign_u, sign_v in ((x * 0.3, 1, 0), (y * 0.3, 0, -1)):
        q = w2c[:3, :3] @ pt + w2c[:3, 3]
        assert (sign_u == 0 or np.sign(q[0]) == sign_u) and (sign_v == 0 or np.sign(q[1]) == sign_v)
    with pytest.raises(ValueError):
        pe.convert_c2w_to_cv(gl, "bogus")


def _setup(tmp_path, n=20, noise=0.0, drop=(), gl=False, seed=0):
    """Estimated model = GT cameras pushed through a known inverse Sim(3) + noise."""
    rng = np.random.default_rng(seed)
    gt_w2c = ring_cameras(n, jitter=0.2, rng=rng)
    gt_names = [f"img_{i:03d}.jpg" for i in range(n)]
    gt_c2w = {}
    for nm, (R, t) in zip(gt_names, gt_w2c):
        M = np.eye(4); M[:3, :3] = R.T; M[:3, 3] = -R.T @ t
        gt_c2w[nm] = M
    true = Sim3(0.37, rand_rot(rng), np.array([1.0, -2.0, 0.5]))  # est->gt
    inv = true.inverse()
    est_images = []
    for i, nm in enumerate(gt_names):
        if i in drop:
            continue
        M = gt_c2w[nm]
        C = inv.apply(M[None, :3, 3])[0] + rng.normal(scale=noise, size=3)
        Rc2w = inv.R @ M[:3, :3]
        Rw2c = Rc2w.T
        est_images.append(ci.ImageRec(len(est_images) + 1, ci.rotmat_to_qvec(Rw2c), -Rw2c @ C, 1, nm))
    write_model_bin(tmp_path / "est", cam(), est_images)
    if gl:
        gtj = {k: (v @ pe.GL_TO_CV).tolist() for k, v in gt_c2w.items()}  # store as OpenGL
    else:
        gtj = {k: v.tolist() for k, v in gt_c2w.items()}
    json.dump(gtj, open(tmp_path / "gt.json", "w"))
    return true, gt_c2w


def test_pose_error_exact(tmp_path):
    true, gt = _setup(tmp_path)
    r = pe.evaluate(pe.load_colmap_poses(tmp_path / "est"), pe.load_gt_poses(tmp_path / "gt.json", "opencv"),
                    True, None)
    assert abs(r["sim3"]["scale"] - true.scale) < 1e-9
    assert np.abs(np.array(r["sim3"]["R"]) - true.R).max() < 1e-9
    assert r["ate"]["max"] < 1e-9 and r["abs_rotation_error_deg"]["max"] < 1e-4
    assert r["relative_rotation_error_deg"]["max"] < 1e-4
    assert r["registered_fraction"] == 1.0 and r["relative_rotation_error_deg"]["n_pairs"] == 190


def test_pose_error_known_noise_and_missing_images(tmp_path):
    sigma = 0.02  # noise added to estimated camera centres, in est units (before scale 1/0.37 -> GT)
    true, gt = _setup(tmp_path, n=40, noise=sigma, drop=(3, 7, 11, 19))
    r = pe.evaluate(pe.load_colmap_poses(tmp_path / "est"), pe.load_gt_poses(tmp_path / "gt.json", "opencv"),
                    True, None)
    assert r["n_matched"] == 36 and abs(r["registered_fraction"] - 0.9) < 1e-12
    assert r["gt_not_in_model"] == ["img_003.jpg", "img_007.jpg", "img_011.jpg", "img_019.jpg"]
    expected_rmse = sigma * true.scale * np.sqrt(3)       # noise mapped into GT units
    assert abs(r["ate"]["rmse"] - expected_rmse) < 0.25 * expected_rmse
    assert abs(r["sim3"]["scale"] / true.scale - 1) < 0.02
    ext = r["scene_extent"]
    assert abs(r["ate_percent_of_extent"]["rmse"] - 100 * r["ate"]["rmse"] / ext) < 1e-9


def test_opengl_gt_json_equivalent(tmp_path):
    _setup(tmp_path, gl=True)
    r = pe.evaluate(pe.load_colmap_poses(tmp_path / "est"), pe.load_gt_poses(tmp_path / "gt.json", "opengl"),
                    True, None)
    assert r["ate"]["max"] < 1e-9 and r["abs_rotation_error_deg"]["max"] < 1e-4
    # wrong convention must show up as a large rotation error, not silently pass
    r2 = pe.evaluate(pe.load_colmap_poses(tmp_path / "est"), pe.load_gt_poses(tmp_path / "gt.json", "opencv"),
                     True, None)
    assert r2["abs_rotation_error_deg"]["max"] > 10


def test_gt_as_colmap_images_txt_and_extent_arg(tmp_path):
    true, gt = _setup(tmp_path)
    # write GT as images.txt (w2c)
    ims = []
    for i, (nm, M) in enumerate(gt.items()):
        Rw = M[:3, :3].T
        ims.append(ci.ImageRec(i + 1, ci.rotmat_to_qvec(Rw), -Rw @ M[:3, 3], 1, nm))
    write_model_txt(tmp_path / "gtm", cam(), ims)
    r = pe.evaluate(pe.load_colmap_poses(tmp_path / "est"), pe.load_gt_poses(tmp_path / "gtm", None),
                    True, 10.0)
    assert r["ate"]["max"] < 1e-9 and r["scene_extent"] == 10.0


def test_outlier_pose_ransac(tmp_path):
    true, gt = _setup(tmp_path, n=30)
    est = pe.load_colmap_poses(tmp_path / "est")
    k = "img_005.jpg"
    est[k] = est[k].copy(); est[k][:3, 3] += [50, 0, 0]  # one badly mis-registered image
    gtp = pe.load_gt_poses(tmp_path / "gt.json", "opencv")
    plain = pe.evaluate(est, gtp, True, None)
    rob = pe.evaluate(est, gtp, True, None, ransac_thresh=0.05, ransac_iters=300, seed=0)
    assert rob["ate"]["median"] < 1e-6 < plain["ate"]["median"]
    assert rob["per_image"][k]["alignment_inlier"] is False and rob["n_alignment_inliers"] == 29
