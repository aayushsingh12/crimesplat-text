#!/usr/bin/env python3
"""Scale-fixed landmark distances per COLMAP model, from clicked pixels (click_landmarks.py).

For every model: triangulate each named point from its clicks in the images REGISTERED in that
model (SIMPLE_RADIAL etc. undistorted via colmap_io), compute the configured pairwise distances,
fix the metric scale with ONE reference distance, and report the error of the OTHER distances
(mm and %). Also: scale-free ratio checks and leave-one-reference-out (every distance in turn is
the reference). `primary_reference` in the config was fixed before any clicking.

Frames: clicks are in the UPRIGHT frame, index convention (+0.5 -> COLMAP continuous). Models built
from `photos_corrected/` ("upright" frame) use them directly; models built from raw `photos/`
("raw" frame, images with an EXIF Orientation tag stored sideways) get the click mapped into the stored
pixel frame (EXIF 1/3/6/8 supported; anything else is an error).

No threshold has a default: --min-ray-angle-deg and --max-reproj-px are required.
A point is dropped for a model if < 2 registered views, max pairwise ray angle < min, any depth <= 0,
or RMS reprojection > max (reason is logged in per_point.csv). Precision is bounded by click error
(~1-2 px); see --click-noise-px simulation in tests / the summary stage.

Inputs : --config landmarks_config.json --clicks clicks.csv
         --runs-json-dir pipelines/image/results/json   (Task-D run JSONs)   OR   --models-spec spec.json
         [{"run_id","condition","model_dir","frame":"upright"|"raw"}]
         --raw-images-dir pipelines/image/data/galanakis2021/photos   (needed for "raw" frame models)
Outputs: <out-dir>/per_point.csv  per_distance.csv  errors_long.csv  ratios.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import itertools
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colmap_io

FLIP_IMAGES = ["IMG_0474.jpg", "IMG_0475.jpg", "IMG_0476.jpg"]


# ------------------------------------------------------------------ frames
def upright_to_stored(x, y, tag, w_stored, h_stored):
    """Continuous coords (corner origin). Upright frame -> stored (raw) frame for EXIF tag."""
    if tag == 1:
        return x, y
    if tag == 3:
        return w_stored - x, h_stored - y
    if tag == 6:   # stored image must be rotated 90 deg CW to be upright
        return y, h_stored - x
    if tag == 8:   # rotated 90 deg CCW
        return w_stored - y, x
    raise NotImplementedError(f"EXIF orientation {tag} (mirrored) not supported")


def stored_size_and_tag(path: Path):
    with Image.open(path) as im:
        return im.size, int(im.getexif().get(0x0112, 1) or 1)


# ------------------------------------------------------------------ triangulation
def triangulate(views):
    """views: list of (R, t, cam, uv_pixels(2,)) world->camera. Returns dict or None-reason string."""
    P, nrm, fs = [], [], []
    for R, t, cam, uv in views:
        n = colmap_io.undistort_to_normalized(cam, np.array([uv]))[0]
        P.append(np.hstack([R, t.reshape(3, 1)])); nrm.append(n); fs.append(float(cam.params[0]))
    A = []
    for Pi, (u, v) in zip(P, nrm):
        A.append(u * Pi[2] - Pi[0]); A.append(v * Pi[2] - Pi[1])
    X = np.linalg.svd(np.array(A))[2][-1]
    if abs(X[3]) < 1e-14:
        return "degenerate"
    X = X[:3] / X[3]

    def resid(x):
        out = []
        for Pi, (u, v), f in zip(P, nrm, fs):
            xc = Pi[:, :3] @ x + Pi[:, 3]
            out += [f * (xc[0] / xc[2] - u), f * (xc[1] / xc[2] - v)]
        return np.array(out)
    X = least_squares(resid, X, xtol=1e-14, ftol=1e-14).x
    depths = [(Pi[:, :3] @ X + Pi[:, 3])[2] for Pi in P]
    rays = []
    for Pi, (u, v) in zip(P, nrm):
        d = Pi[:, :3].T @ np.array([u, v, 1.0]); rays.append(d / np.linalg.norm(d))
    ang = max(np.degrees(np.arccos(np.clip(a @ b, -1, 1))) for a, b in itertools.combinations(rays, 2))
    r = resid(X)
    return dict(X=X, rms_px=float(np.sqrt((r ** 2).mean())), max_ray_deg=float(ang),
                min_depth=float(min(depths)), n_views=len(P))


# ------------------------------------------------------------------ per-model computation
def load_clicks(path):
    obs = {}
    for r in csv.DictReader(open(path)):
        obs.setdefault(r["point_name"], []).append(
            (r["image"], float(r["x"]) + 0.5, float(r["y"]) + 0.5, int(r["img_w"]), int(r["img_h"])))
    return obs


def model_points(model_dir, frame, obs, raw_dir, min_ray_deg, max_reproj_px):
    cams = colmap_io.read_cameras(model_dir)
    ims = {im.name: im for im in colmap_io.read_images(model_dir, False).values()}
    pts, diag = {}, []
    for pname, lst in obs.items():
        views, nreg = [], 0
        for name, x, y, w, h in lst:
            im = ims.get(name)
            if im is None:
                continue
            nreg += 1
            cam = cams[im.camera_id]
            if frame == "raw":
                (ws, hs), tag = stored_size_and_tag(Path(raw_dir) / name)
                x, y = upright_to_stored(x, y, tag, ws, hs)
                assert (cam.width, cam.height) == (ws, hs), (name, cam.width, cam.height, ws, hs)
            else:
                assert (cam.width, cam.height) == (w, h), (name, "click image size vs camera", (w, h), (cam.width, cam.height))
            views.append((im.R, im.tvec, cam, np.array([x, y])))
        row = dict(point=pname, n_clicks_registered=nreg, n_views=len(views), status="", rms_px="", max_ray_deg="")
        if len(views) < 2:
            row["status"] = "dropped: <2 registered views"
        else:
            tr = triangulate(views)
            if isinstance(tr, str):
                row["status"] = "dropped: " + tr
            else:
                row.update(rms_px=round(tr["rms_px"], 4), max_ray_deg=round(tr["max_ray_deg"], 3))
                if tr["min_depth"] <= 0:
                    row["status"] = "dropped: point behind a camera"
                elif tr["max_ray_deg"] < min_ray_deg:
                    row["status"] = f"dropped: max ray angle {tr['max_ray_deg']:.2f} < {min_ray_deg}"
                elif tr["rms_px"] > max_reproj_px:
                    row["status"] = f"dropped: rms reprojection {tr['rms_px']:.2f} px > {max_reproj_px}"
                else:
                    row["status"] = "ok"; pts[pname] = tr["X"]
        diag.append(row)
    return pts, diag, set(ims)


def distance_table(cfg, pts):
    d = {}
    for dd in cfg["distances"]:
        if dd["a"] in pts and dd["b"] in pts:
            d[dd["name"]] = float(np.linalg.norm(pts[dd["a"]] - pts[dd["b"]]))
    return d


def errors_for_reference(cfg, dist, ref_name):
    """scale from ref distance; errors on all others. -> list of dict"""
    mm = {d["name"]: d["mm"] for d in cfg["distances"]}
    if ref_name not in dist:
        return []
    s = mm[ref_name] / dist[ref_name]  # mm per model unit
    out = []
    for n, v in dist.items():
        if n == ref_name:
            continue
        est = v * s
        out.append(dict(distance=n, est_mm=est, pdf_mm=mm[n], err_mm=est - mm[n], err_pct=100 * (est / mm[n] - 1)))
    return out


def run_model(cfg, obs, spec, raw_dir, min_ray_deg, max_reproj_px, include_optional):
    pts, diag, regnames = model_points(spec["model_dir"], spec["frame"], obs, raw_dir, min_ray_deg, max_reproj_px)
    dist = distance_table(cfg, pts)
    flip = "+".join(n[4:8] for n in FLIP_IMAGES if n in regnames) or "none"
    base = dict(run_id=spec["run_id"], condition=spec["condition"], flipset=flip, n_registered=len(regnames))
    errs, ratios = [], []
    for ref in dist:
        for e in errors_for_reference(cfg, dist, ref):
            errs.append({**base, "reference": ref, "is_primary": ref == cfg["primary_reference"], **e})
    mm = {d["name"]: d["mm"] for d in cfg["distances"]}
    for a, b in cfg["ratios"]:
        if a in dist and b in dist:
            mr, pr = dist[a] / dist[b], mm[a] / mm[b]
            ratios.append({**base, "ratio": f"{a}/{b}", "model_ratio": mr, "pdf_ratio": pr, "err_pct": 100 * (mr / pr - 1)})
    return base, diag, dist, errs, ratios


def collect_specs(a):
    if a.models_spec:
        return json.load(open(a.models_spec))
    specs = []
    for f in sorted(glob.glob(str(Path(a.runs_json_dir) / "galanakis2021__*.json"))):
        d = json.load(open(f))
        if d["status"] != "ok" or not d["condition"].startswith("taskD"):
            continue
        c = d["condition"]
        cond = "without_fix" if "no-exif-fix" in c else ("with_fix_seed0_repeat" if "fixed-seed0" in c else "with_fix")
        run_dir = Path(a.runs_json_dir).parent / "work" / "galanakis2021" / d["run_id"]
        specs.append(dict(run_id=d["run_id"], condition=cond, model_dir=str(run_dir / d["best_model"]),
                          frame="raw" if cond == "without_fix" else "upright"))
    return specs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--clicks", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--runs-json-dir"); g.add_argument("--models-spec")
    ap.add_argument("--raw-images-dir")
    ap.add_argument("--min-ray-angle-deg", type=float, required=True)
    ap.add_argument("--max-reproj-px", type=float, required=True)
    ap.add_argument("--include-optional", action="store_true")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if not a.include_optional:
        cfg["distances"] = [d for d in cfg["distances"] if not d.get("optional")]
    obs = load_clicks(a.clicks)
    specs = collect_specs(a)
    if any(s["frame"] == "raw" for s in specs) and not a.raw_images_dir:
        ap.error("--raw-images-dir is required for raw-frame models")
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    P, D, E, R = [], [], [], []
    for s in specs:
        base, diag, dist, errs, ratios = run_model(cfg, obs, s, a.raw_images_dir, a.min_ray_angle_deg, a.max_reproj_px, a.include_optional)
        P += [{**base, **r} for r in diag]
        D.append({**base, **{k: v for k, v in dist.items()}})
        E += errs; R += ratios
    def w(name, rows):
        if not rows:
            Path(out / name).write_text(""); return
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with open(out / name, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=keys); wr.writeheader(); wr.writerows(rows)
    w("per_point.csv", P); w("per_distance.csv", D); w("errors_long.csv", E); w("ratios.csv", R)
    n_ok = sum(1 for r in P if r["status"] == "ok")
    print(f"{len(specs)} models, {len(P)} (model,point) rows, {n_ok} ok; wrote {out}")


if __name__ == "__main__":
    main()
