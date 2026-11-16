#!/usr/bin/env python3
"""COLMAP sparse-model reader (TEXT or BINARY, auto-detected) + camera models.

Self-contained (numpy only). scripts/colmap_model.py reads TEXT only and
mishandles images with zero keypoints, so it is not reused (and must not be
edited); this module reads both formats.

Conventions (COLMAP): image pose is WORLD->CAMERA, x_cam = R x_world + t, with
R = qvec_to_rotmat(qvec), qvec = (w,x,y,z). Camera axes (OpenCV style): +x right,
+y down, +z forward. Camera centre C = -R^T t. Camera-to-world = [R^T | C].
"""
from __future__ import annotations

import dataclasses
import struct
from pathlib import Path

import numpy as np

# model_id -> (name, num_params); from COLMAP src/colmap/sensor/models.h
CAMERA_MODELS = {
    0: ("SIMPLE_PINHOLE", 3), 1: ("PINHOLE", 4), 2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5), 4: ("OPENCV", 8), 5: ("OPENCV_FISHEYE", 8),
    6: ("FULL_OPENCV", 12), 7: ("FOV", 5), 8: ("SIMPLE_RADIAL_FISHEYE", 4),
    9: ("RADIAL_FISHEYE", 5), 10: ("THIN_PRISM_FISHEYE", 12),
}
MODEL_NUM_PARAMS = {n: k for n, k in CAMERA_MODELS.values()}


@dataclasses.dataclass
class Camera:
    camera_id: int
    model: str
    width: int
    height: int
    params: np.ndarray


@dataclasses.dataclass
class ImageRec:
    image_id: int
    qvec: np.ndarray
    tvec: np.ndarray
    camera_id: int
    name: str
    xys: np.ndarray | None = None
    point3D_ids: np.ndarray | None = None

    @property
    def R(self) -> np.ndarray:
        return qvec_to_rotmat(self.qvec)

    @property
    def center(self) -> np.ndarray:
        return -self.R.T @ self.tvec

    def cam_to_world(self) -> np.ndarray:
        M = np.eye(4)
        M[:3, :3] = self.R.T
        M[:3, 3] = self.center
        return M


@dataclasses.dataclass
class Points3D:
    ids: np.ndarray
    xyz: np.ndarray
    rgb: np.ndarray
    error: np.ndarray


def qvec_to_rotmat(q) -> np.ndarray:
    w, x, y, z = np.asarray(q, float) / np.linalg.norm(q)
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w],
        [2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w],
        [2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y]])


def rotmat_to_qvec(R) -> np.ndarray:
    R = np.asarray(R, float).T  # K below is written for the transposed index convention
    K = np.array([
        [R[0, 0] - R[1, 1] - R[2, 2], 0, 0, 0],
        [R[1, 0] + R[0, 1], R[1, 1] - R[0, 0] - R[2, 2], 0, 0],
        [R[2, 0] + R[0, 2], R[2, 1] + R[1, 2], R[2, 2] - R[0, 0] - R[1, 1], 0],
        [R[1, 2] - R[2, 1], R[2, 0] - R[0, 2], R[0, 1] - R[1, 0], R[0, 0] + R[1, 1] + R[2, 2]]]) / 3.0
    vals, vecs = np.linalg.eigh(K)
    q = vecs[[3, 0, 1, 2], np.argmax(vals)]
    return -q if q[0] < 0 else q


# ------------------------------------------------------------------ text
def _read_cameras_txt(p):
    cams = {}
    for line in p.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        s = line.split()
        cams[int(s[0])] = Camera(int(s[0]), s[1], int(s[2]), int(s[3]), np.array(s[4:], float))
    return cams


def _read_images_txt(p, read_points2d):
    lines = [l for l in p.read_text().splitlines() if not l.startswith("#")]
    # blank lines are meaningful (an image with zero keypoints has an empty 2nd line)
    while lines and not lines[-1].strip() and len(lines) % 2:
        lines.pop()
    imgs = {}
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        h = lines[i].split()
        pts = lines[i + 1].split() if i + 1 < len(lines) else []
        rec = ImageRec(int(h[0]), np.array(h[1:5], float), np.array(h[5:8], float), int(h[8]), h[9])
        if read_points2d:
            v = np.array(pts, float).reshape(-1, 3)
            rec.xys, rec.point3D_ids = v[:, :2], v[:, 2].astype(np.int64)
        imgs[rec.image_id] = rec
        i += 2
    return imgs


def _read_points_txt(p):
    ids, xyz, rgb, err = [], [], [], []
    for line in p.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        s = line.split()
        ids.append(int(s[0])); xyz.append([float(v) for v in s[1:4]])
        rgb.append([int(v) for v in s[4:7]]); err.append(float(s[7]))
    return Points3D(np.array(ids, np.int64), np.array(xyz).reshape(-1, 3),
                    np.array(rgb, np.uint8).reshape(-1, 3), np.array(err))


# ---------------------------------------------------------------- binary
def _read_cameras_bin(p):
    cams = {}
    with open(p, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        for _ in range(n):
            cid, mid, w, h = struct.unpack("<iiQQ", f.read(24))
            name, npar = CAMERA_MODELS[mid]
            params = np.array(struct.unpack(f"<{npar}d", f.read(8 * npar)))
            cams[cid] = Camera(cid, name, w, h, params)
    return cams


def _read_images_bin(p, read_points2d):
    imgs = {}
    with open(p, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        for _ in range(n):
            iid, *q = struct.unpack("<i4d", f.read(36))
            t = struct.unpack("<3d", f.read(24))
            cid = struct.unpack("<i", f.read(4))[0]
            name = b""
            while (c := f.read(1)) != b"\x00":
                name += c
            npts = struct.unpack("<Q", f.read(8))[0]
            raw = f.read(24 * npts)
            rec = ImageRec(iid, np.array(q), np.array(t), cid, name.decode())
            if read_points2d:
                arr = np.frombuffer(raw, dtype=np.dtype([("x", "<f8"), ("y", "<f8"), ("id", "<i8")]))
                rec.xys = np.c_[arr["x"], arr["y"]]
                rec.point3D_ids = arr["id"].astype(np.int64)
            imgs[iid] = rec
    return imgs


def _read_points_bin(p):
    ids, xyz, rgb, err = [], [], [], []
    with open(p, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        for _ in range(n):
            pid, x, y, z, r, g, b, e, tl = struct.unpack("<Q3d3BdQ", f.read(8 + 24 + 3 + 8 + 8))
            f.seek(8 * tl, 1)
            ids.append(pid); xyz.append((x, y, z)); rgb.append((r, g, b)); err.append(e)
    return Points3D(np.array(ids, np.int64), np.array(xyz).reshape(-1, 3),
                    np.array(rgb, np.uint8).reshape(-1, 3), np.array(err))


def detect_format(model_dir: Path) -> str:
    model_dir = Path(model_dir)
    if (model_dir / "images.bin").exists():
        return "bin"
    if (model_dir / "images.txt").exists():
        return "txt"
    raise FileNotFoundError(f"no COLMAP model (images.bin / images.txt) in {model_dir}")


def read_cameras(model_dir):
    d = Path(model_dir)
    return _read_cameras_bin(d / "cameras.bin") if detect_format(d) == "bin" else _read_cameras_txt(d / "cameras.txt")


def read_images(model_dir, read_points2d=False):
    d = Path(model_dir)
    if detect_format(d) == "bin":
        return _read_images_bin(d / "images.bin", read_points2d)
    return _read_images_txt(d / "images.txt", read_points2d)


def read_points3D(model_dir) -> Points3D:
    d = Path(model_dir)
    return _read_points_bin(d / "points3D.bin") if detect_format(d) == "bin" else _read_points_txt(d / "points3D.txt")


# ------------------------------------------------------- camera models
def camera_matrix_and_dist(cam: Camera):
    """(K 3x3, dist (k1,k2,p1,p2)) in OpenCV convention for the supported models.

    COLMAP SIMPLE_RADIAL / RADIAL / OPENCV use the same radial+tangential
    polynomial as OpenCV's (k1,k2,p1,p2) model on normalised coordinates.
    Other models (fisheye, FOV, FULL_OPENCV, THIN_PRISM) raise NotImplementedError.
    """
    p, m = cam.params, cam.model
    if m == "SIMPLE_PINHOLE":
        fx = fy = p[0]; cx, cy = p[1], p[2]; d = (0, 0, 0, 0)
    elif m == "PINHOLE":
        fx, fy, cx, cy = p; d = (0, 0, 0, 0)
    elif m == "SIMPLE_RADIAL":
        fx = fy = p[0]; cx, cy = p[1], p[2]; d = (p[3], 0, 0, 0)
    elif m == "RADIAL":
        fx = fy = p[0]; cx, cy = p[1], p[2]; d = (p[3], p[4], 0, 0)
    elif m == "OPENCV":
        fx, fy, cx, cy = p[:4]; d = tuple(p[4:8])
    else:
        raise NotImplementedError(f"camera model {m} not supported")
    return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1.0]]), np.array(d, float)


def project(cam: Camera, R, t, X):
    """Project world points X (N,3) with world->camera (R,t). Returns (uv (N,2), depth (N,))."""
    import cv2
    X = np.asarray(X, float).reshape(-1, 3)
    K, d = camera_matrix_and_dist(cam)
    Xc = X @ np.asarray(R).T + t
    uv, _ = cv2.projectPoints(Xc.reshape(-1, 1, 3), np.zeros(3), np.zeros(3), K, d)
    return uv.reshape(-1, 2), Xc[:, 2]


def undistort_to_normalized(cam: Camera, uv):
    """Pixel coords -> undistorted normalised image coords (x/z, y/z), (N,2)."""
    import cv2
    K, d = camera_matrix_and_dist(cam)
    uv = np.asarray(uv, float).reshape(-1, 1, 2)
    return cv2.undistortPointsIter(uv, K, d, None, None,
                                   (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-12)).reshape(-1, 2)
