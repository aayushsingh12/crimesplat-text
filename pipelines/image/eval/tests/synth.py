"""Synthetic-data helpers shared by the tests (known cameras, points, models)."""
import struct
from pathlib import Path

import numpy as np

import colmap_io as ci


def rand_rot(rng):
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def look_at_w2c(center, target, up=(0, 0, 1)):
    """OpenCV-style world->camera (R,t): +z toward target, +y roughly down."""
    center, target, up = map(lambda v: np.asarray(v, float), (center, target, up))
    z = target - center; z /= np.linalg.norm(z)
    x = np.cross(z, up); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    Rc2w = np.stack([x, y, z], 1)  # columns = camera axes in world
    R = Rc2w.T
    return R, -R @ center


def ring_cameras(n, radius=4.0, height=1.5, target=(0, 0, 0.5), jitter=0.0, rng=None):
    out = []
    for i in range(n):
        a = 2 * np.pi * i / n
        c = np.array([radius * np.cos(a), radius * np.sin(a), height])
        if rng is not None and jitter:
            c = c + rng.normal(scale=jitter, size=3)
        out.append(look_at_w2c(c, target))
    return out


def write_model_txt(d, cameras, images, points=None):
    """cameras {id: ci.Camera}; images list of ci.ImageRec (xys/point3D_ids may be None);
    points: ci.Points3D or None."""
    d = Path(d); d.mkdir(parents=True, exist_ok=True)
    with open(d / "cameras.txt", "w") as f:
        for c in cameras.values():
            f.write(f"{c.camera_id} {c.model} {c.width} {c.height} " + " ".join(repr(float(p)) for p in c.params) + "\n")
    with open(d / "images.txt", "w") as f:
        for im in images:
            f.write(f"{im.image_id} " + " ".join(repr(float(v)) for v in im.qvec) + " "
                    + " ".join(repr(float(v)) for v in im.tvec) + f" {im.camera_id} {im.name}\n")
            if im.xys is not None and len(im.xys):
                f.write(" ".join(f"{float(x)!r} {float(y)!r} {int(i)}" for (x, y), i in zip(im.xys, im.point3D_ids)) + "\n")
            else:
                f.write("\n")
    with open(d / "points3D.txt", "w") as f:
        if points is not None:
            for i, p, c, e in zip(points.ids, points.xyz, points.rgb, points.error):
                f.write(f"{i} {float(p[0])!r} {float(p[1])!r} {float(p[2])!r} {c[0]} {c[1]} {c[2]} {float(e)!r}\n")


def write_model_bin(d, cameras, images, points=None):
    d = Path(d); d.mkdir(parents=True, exist_ok=True)
    inv = {n: k for k, (n, _) in ci.CAMERA_MODELS.items()}
    with open(d / "cameras.bin", "wb") as f:
        f.write(struct.pack("<Q", len(cameras)))
        for c in cameras.values():
            f.write(struct.pack("<iiQQ", c.camera_id, inv[c.model], c.width, c.height))
            f.write(struct.pack(f"<{len(c.params)}d", *c.params))
    with open(d / "images.bin", "wb") as f:
        f.write(struct.pack("<Q", len(images)))
        for im in images:
            f.write(struct.pack("<i4d", im.image_id, *im.qvec))
            f.write(struct.pack("<3d", *im.tvec))
            f.write(struct.pack("<i", im.camera_id))
            f.write(im.name.encode() + b"\x00")
            n = 0 if im.xys is None else len(im.xys)
            f.write(struct.pack("<Q", n))
            for k in range(n):
                f.write(struct.pack("<ddq", im.xys[k][0], im.xys[k][1], int(im.point3D_ids[k])))
    with open(d / "points3D.bin", "wb") as f:
        n = 0 if points is None else len(points.ids)
        f.write(struct.pack("<Q", n))
        for k in range(n):
            f.write(struct.pack("<Q3d3BdQ", int(points.ids[k]), *points.xyz[k], *map(int, points.rgb[k]),
                                float(points.error[k]), 2))
            f.write(struct.pack("<iiii", 1, 0, 2, 1))  # two dummy track elements


def make_images(w2c_list, names=None, camera_id=1):
    out = []
    for i, (R, t) in enumerate(w2c_list):
        out.append(ci.ImageRec(i + 1, ci.rotmat_to_qvec(R), np.asarray(t, float), camera_id,
                               names[i] if names else f"img_{i:03d}.jpg"))
    return out
