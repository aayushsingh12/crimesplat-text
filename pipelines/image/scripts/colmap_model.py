#!/usr/bin/env python3
"""
Minimal reader for a COLMAP TEXT sparse model (cameras.txt / images.txt /
points3D.txt), used by tag_regions.py to get each registered image's known
camera intrinsics/pose and its SIFT-track 2D<->3D correspondences.

Deliberately reads the TEXT format, not the binary one: the pinned model at
pipelines/image/data/galanakis2021/colmap/sparse/0 is binary, so it was
converted once with:

    colmap model_converter \\
      --input_path pipelines/image/data/galanakis2021/colmap/sparse/0 \\
      --output_path pipelines/image/data/galanakis2021/colmap/sparse_txt \\
      --output_type TXT

This module only parses the resulting TEXT files -- plain numpy, no
pycolmap/torch dependency, so it runs unmodified in either the crime-image
or crime-image-tag env.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np


@dataclasses.dataclass
class Camera:
    camera_id: int
    model: str
    width: int
    height: int
    params: np.ndarray  # model-specific, e.g. SIMPLE_RADIAL: [f, cx, cy, k]


@dataclasses.dataclass
class Image:
    image_id: int
    qvec: np.ndarray  # (qw, qx, qy, qz), world-to-camera rotation
    tvec: np.ndarray  # world-to-camera translation
    camera_id: int
    name: str
    xys: np.ndarray  # (N, 2) 2D keypoint pixel coords, full source resolution
    point3D_ids: np.ndarray  # (N,) int64, -1 if this keypoint has no 3D point


@dataclasses.dataclass
class Point3D:
    point3D_id: int
    xyz: np.ndarray  # (3,), raw COLMAP world space (pre applied_transform)
    rgb: np.ndarray


def qvec_to_rotmat(qvec: np.ndarray) -> np.ndarray:
    """Standard COLMAP quaternion (w, x, y, z) -> 3x3 rotation matrix."""
    w, x, y, z = qvec
    return np.array(
        [
            [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w],
            [2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w],
            [2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y],
        ]
    )


def read_cameras_txt(path: Path) -> dict[int, Camera]:
    cameras = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        camera_id = int(parts[0])
        model = parts[1]
        width, height = int(parts[2]), int(parts[3])
        params = np.array([float(p) for p in parts[4:]])
        cameras[camera_id] = Camera(camera_id, model, width, height, params)
    return cameras


def read_images_txt(path: Path) -> dict[int, Image]:
    images = {}
    lines = [l for l in path.read_text().splitlines() if l and not l.startswith("#")]
    for i in range(0, len(lines), 2):
        header = lines[i].split()
        image_id = int(header[0])
        qvec = np.array([float(x) for x in header[1:5]])
        tvec = np.array([float(x) for x in header[5:8]])
        camera_id = int(header[8])
        name = header[9]

        points_raw = lines[i + 1].split()
        vals = np.array([float(x) for x in points_raw]).reshape(-1, 3)
        xys = vals[:, :2]
        point3D_ids = vals[:, 2].astype(np.int64)

        images[image_id] = Image(image_id, qvec, tvec, camera_id, name, xys, point3D_ids)
    return images


def read_points3D_txt(path: Path) -> dict[int, Point3D]:
    points = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        point3D_id = int(parts[0])
        xyz = np.array([float(x) for x in parts[1:4]])
        rgb = np.array([int(x) for x in parts[4:7]])
        points[point3D_id] = Point3D(point3D_id, xyz, rgb)
    return points


def load_model(sparse_txt_dir: Path):
    cameras = read_cameras_txt(sparse_txt_dir / "cameras.txt")
    images = read_images_txt(sparse_txt_dir / "images.txt")
    points3D = read_points3D_txt(sparse_txt_dir / "points3D.txt")
    return cameras, images, points3D
