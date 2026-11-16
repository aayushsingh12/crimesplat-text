import numpy as np
from plyfile import PlyData, PlyElement
from scipy.spatial import ConvexHull

import cloud_error as ce
from align import Sim3
from synth import rand_rot


def hull_mesh(seed=0):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(40, 3)) * [3.0, 1.5, 0.7] + [0.5, 0, 0]
    h = ConvexHull(v)
    used = np.unique(h.simplices)
    remap = {o: i for i, o in enumerate(used)}
    return v[used], np.vectorize(remap.get)(h.simplices)


def write_ply(path, verts, faces=None):
    vert = np.array([tuple(p) for p in verts], dtype=[("x", "f8"), ("y", "f8"), ("z", "f8")])
    els = [PlyElement.describe(vert, "vertex")]
    if faces is not None:
        f = np.array([(tuple(t),) for t in faces], dtype=[("vertex_indices", "i4", (3,))])
        els.append(PlyElement.describe(f, "face"))
    PlyData(els).write(str(path))


def test_ply_roundtrip_and_mesh_sampling(tmp_path):
    v, f = hull_mesh()
    write_ply(tmp_path / "m.ply", v, f)
    v2, f2 = ce.read_ply(tmp_path / "m.ply")
    assert np.abs(v2 - v).max() < 1e-12 and (f2 == f).all()
    pts, _area = ce.sample_mesh(v2, f2, 20000, 0)
    # every sample must lie on the hull surface: distance to the nearest face plane ~ 0
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); n /= np.linalg.norm(n, axis=1, keepdims=True)
    dist_planes = np.abs((pts[:, None, :] - tri[None, :, 0, :]) @ n.T if False else
                         np.einsum("pfk,fk->pf", pts[:, None, :] - tri[None, :, 0, :], n)).min(1)
    assert dist_planes.max() < 1e-9
    # area-weighted: sample fraction per face ~ area fraction
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    assert abs(pts.mean(0) - (tri.mean(1) * area[:, None]).sum(0) / area.sum()).max() < 0.05


def test_metrics_known_noise_and_completeness(tmp_path):
    v, f = hull_mesh(1)
    ref = ce.sample_mesh(v, f, 400000, 0)[0]
    sigma = 0.05  # >> ref sample spacing, so the discretisation floor is small
    rng = np.random.default_rng(2)
    est = ce.sample_mesh(v, f, 20000, 5)[0] + rng.normal(scale=sigma, size=(20000, 3))
    m = ce.cloud_metrics(est, ref, [sigma, 3 * sigma])
    # distance to a surface = |normal component| of isotropic noise ~ half-normal(sigma)
    assert abs(m["accuracy"]["mean"] - sigma * np.sqrt(2 / np.pi)) < 0.08 * sigma
    assert abs(m["accuracy"]["rmse"] - sigma) < 0.05 * sigma
    # P(|N(0,s)|<=s)=0.6827 ; <=3s = 0.9973
    assert abs(m["at_threshold"][repr(sigma)]["accuracy_fraction"] - 0.6827) < 0.03
    assert abs(m["at_threshold"][repr(3 * sigma)]["accuracy_fraction"] - 0.9973) < 0.01


def test_completeness_exact_for_half_cloud():
    rng = np.random.default_rng(3)
    ref = rng.normal(size=(5000, 3))
    mask = ref[:, 0] < 0
    m = ce.cloud_metrics(ref[mask], ref, [1e-6])
    assert abs(m["at_threshold"]["1e-06"]["completeness_fraction"] - mask.mean()) < 1e-12
    assert m["at_threshold"]["1e-06"]["accuracy_fraction"] == 1.0


def test_icp_recovers_transform_incl_scale_and_outliers():
    v, f = hull_mesh(4)
    ref = ce.sample_mesh(v, f, 300000, 0)[0]
    rng = np.random.default_rng(7)
    true = Sim3(1.0 / 0.4, rand_rot(rng), np.array([3.0, -1.0, 2.0]))   # est -> ref
    inv = true.inverse()
    est = ce.sample_mesh(v, f, 4000, 9)[0] + rng.normal(scale=0.005, size=(4000, 3))
    est = inv.apply(est)
    est[:200] += rng.normal(scale=3.0, size=(200, 3))                    # 5% gross outliers
    sim, rmse, _ = ce.icp_align(est, ref, True, trim=0.85, max_iters=100, tol=1e-9)
    assert abs(sim.scale / true.scale - 1) < 0.01
    assert np.abs(sim.R - true.R).max() < 0.02
    assert np.linalg.norm(sim.apply(est[200:]).mean(0) - true.apply(est[200:]).mean(0)) < 0.03
    assert rmse < 0.02


def test_icp_fixed_scale_mode():
    v, f = hull_mesh(5)
    ref = ce.sample_mesh(v, f, 300000, 0)[0]
    rng = np.random.default_rng(1)
    true = Sim3(1.0, rand_rot(rng), np.array([1.0, 2.0, 3.0]))
    est = true.inverse().apply(ce.sample_mesh(v, f, 3000, 2)[0])
    sim, rmse, _ = ce.icp_align(est, ref, False, trim=1.0, max_iters=100, tol=1e-10)
    assert sim.scale == 1.0 and np.abs(sim.R - true.R).max() < 1e-3 and rmse < 0.02  # rmse floor = ref sample spacing


def test_cli_with_given_sim3_and_colmap_points(tmp_path):
    import json, subprocess, sys
    import colmap_io as ci
    from synth import write_model_txt, make_images, ring_cameras
    v, f = hull_mesh(6)
    write_ply(tmp_path / "ref.ply", v, f)
    true = Sim3(2.0, np.eye(3), np.array([1.0, 0, 0]))
    pts = ce.sample_mesh(v, f, 500, 3)[0]
    est_xyz = true.inverse().apply(pts)
    ptsobj = ci.Points3D(np.arange(500), est_xyz, np.zeros((500, 3), np.uint8), np.zeros(500))
    cams = {1: ci.Camera(1, "PINHOLE", 10, 10, np.array([5, 5, 5, 5.0]))}
    write_model_txt(tmp_path / "m", cams, make_images(ring_cameras(3)), ptsobj)
    json.dump({"sim3": true.to_dict()}, open(tmp_path / "s.json", "w"))
    import pathlib
    r = subprocess.run([sys.executable, str(pathlib.Path(ce.__file__)), "--est", str(tmp_path / "m"),
                        "--ref", str(tmp_path / "ref.ply"), "--mesh-samples", "400000", "--seed", "0",
                        "--thresholds", "0.05", "--sim3", str(tmp_path / "s.json"), "--out", str(tmp_path / "o.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    o = json.load(open(tmp_path / "o.json"))
    assert o["metrics"]["accuracy"]["rmse"] < 0.015 and o["metrics"]["at_threshold"]["0.05"]["accuracy_fraction"] > 0.99
    assert o["reference_sample_spacing_approx"] > 0
