import numpy as np
import pytest
from align import Sim3, umeyama, umeyama_ransac, residuals


def rand_rot(rng):
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def make(rng, n=200, noise=0.0, scale=2.5):
    src = rng.normal(size=(n, 3)) * [3, 2, 1]
    R, t = rand_rot(rng), rng.normal(size=3) * 5
    true = Sim3(scale, R, t)
    dst = true.apply(src) + rng.normal(scale=noise, size=(n, 3))
    return src, dst, true


def test_exact_recovery():
    rng = np.random.default_rng(0)
    src, dst, true = make(rng)
    sim = umeyama(src, dst, True)
    assert abs(sim.scale - true.scale) < 1e-10
    assert np.abs(sim.R - true.R).max() < 1e-10
    assert np.abs(sim.t - true.t).max() < 1e-9
    assert residuals(sim, src, dst).max() < 1e-9


def test_noisy_recovery_and_residual_level():
    rng = np.random.default_rng(1)
    sigma = 0.05
    src, dst, true = make(rng, n=500, noise=sigma)
    sim = umeyama(src, dst, True)
    assert abs(sim.scale / true.scale - 1) < 5e-3
    assert np.abs(sim.R - true.R).max() < 5e-3
    rmse = np.sqrt((residuals(sim, src, dst) ** 2).mean())
    # per-point residual RMSE ~ sigma*sqrt(3)
    assert abs(rmse - sigma * np.sqrt(3)) < 0.1 * sigma * np.sqrt(3)


def test_no_scale_mode():
    rng = np.random.default_rng(2)
    src, dst, true = make(rng, scale=1.0)
    sim = umeyama(src, dst, False)
    assert sim.scale == 1.0 and np.abs(sim.t - true.t).max() < 1e-9


def test_reflection_not_returned():
    rng = np.random.default_rng(3)
    src = rng.normal(size=(50, 3))
    dst = src * [1, 1, -1]  # mirrored data: best proper rotation must still be det +1
    sim = umeyama(src, dst, True)
    assert np.linalg.det(sim.R) > 0.999


def test_inverse_and_matrix():
    rng = np.random.default_rng(4)
    src, dst, true = make(rng)
    p = rng.normal(size=(5, 3))
    assert np.abs(true.inverse().apply(true.apply(p)) - p).max() < 1e-10
    h = np.c_[p, np.ones(5)] @ true.matrix().T
    assert np.abs(h[:, :3] - true.apply(p)).max() < 1e-10


def test_degenerate_raises():
    line = np.c_[np.arange(5.0), np.zeros(5), np.zeros(5)]
    with pytest.raises(ValueError):
        umeyama(line, line, True)
    with pytest.raises(ValueError):
        umeyama(line[:2], line[:2], True)


def test_ransac_beats_plain_with_outliers():
    rng = np.random.default_rng(5)
    src, dst, true = make(rng, n=300, noise=0.02)
    bad = rng.choice(300, 90, replace=False)  # 30% gross outliers
    dst[bad] += rng.normal(scale=20, size=(90, 3))
    plain = umeyama(src, dst, True)
    sim, mask = umeyama_ransac(src, dst, inlier_thresh=0.2, n_iters=500, seed=0, with_scale=True)
    assert abs(plain.scale / true.scale - 1) > abs(sim.scale / true.scale - 1)
    assert abs(sim.scale / true.scale - 1) < 5e-3
    assert np.abs(sim.R - true.R).max() < 5e-3
    truth_inl = np.ones(300, bool); truth_inl[bad] = False
    assert (mask & ~truth_inl).sum() == 0          # no outlier accepted
    assert (mask & truth_inl).sum() >= 0.95 * truth_inl.sum()


def test_ransac_fails_loudly():
    rng = np.random.default_rng(6)
    src = rng.normal(size=(20, 3)); dst = rng.normal(size=(20, 3)) * 50
    with pytest.raises(RuntimeError):
        umeyama_ransac(src, dst, inlier_thresh=1e-6, n_iters=50, seed=0, with_scale=True, min_inliers=10)
