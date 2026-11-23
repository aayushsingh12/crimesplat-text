"""Benchmark the video pipeline (crimesplat-video) on an Aria recording.

Reference: Project Aria's Machine Perception Services (MPS) closed-loop SLAM trajectory, a
visual-inertial estimate from the glasses' own sensors (two SLAM cameras + IMUs), in metres with
gravity. It is a reference, not ground truth; Meta reports centimetre-level accuracy for it.

Time sync is exact: the Aria mp4 carries the device timestamp of every frame in its
`description` tag, and the pipeline keeps each keyframe's frame index, so each estimated camera
is compared with the reference pose at that frame's own timestamp (position interpolated
linearly, rotation by slerp from the 1 kHz trajectory).

What is reported
  run         keyframes, registration, reprojection error, points, Gaussians, held-out PSNR,
              iterations, per-stage time, peak VRAM, units the pipeline assigned.
  ATE         absolute trajectory error of camera centres after a similarity (Sim(3)) alignment,
              mean / median / RMSE / p95 / max, in metres and in % of the reference path extent.
              Two variants: (a) against the device origin as is; (b) also fitting the fixed
              offset between the device origin and the RGB camera (3 extra parameters, declared,
              slightly optimistic). The true camera position lies between the two.
  scale       when the pipeline claims metres: how much its lengths differ from the reference's
              (pipeline length / reference length - 1), and the camera height above the detected
              floor that the reference implies, against the height the pipeline assumed.
  up          angle between the pipeline's up axis and the reference gravity direction.
  rotation    The reference gives the device frame's orientation, not the RGB camera's, so a fixed
              mounting rotation separates them. Two measures:
              ARE  absolute rotation error per camera after fitting that mounting rotation (3
                   parameters, the chordal mean over all cameras);
              RRE  relative rotation error between keyframes 1 and 10 apart, in the reference frame
                   after the same fit;
              RAE  rotation-angle error: the difference in how far the camera turned between two
                   keyframes. Needs no fit at all, since a fixed mounting does not change it.

Run with the video pipeline's Python (it has pycolmap and numpy):

    ~/Projects/crimesplat-video/pipeline/.venv/bin/python benchmarks/aria_video.py \\
        --workspace ~/Projects/crimesplat-video/workspace/<job> \\
        --video cases/short_family/video/aria_sunroom.mp4 \\
        --trajectory <unzipped mps_slam_trajectories>/closed_loop_trajectory.csv \\
        --name sunroom --out benchmarks/results
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pycolmap


# ---------- geometry ----------
def umeyama(src, dst, scale=True):
    """s, R, t minimising sum ||dst - (s R src + t)||^2, no reflection."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    U, S, Vt = np.linalg.svd(xd.T @ xs / len(src))
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = np.trace(np.diag(S) @ D) / (xs ** 2).sum(1).mean() if scale else 1.0
    return s, R, mu_d - s * R @ mu_s


def quat_to_R(q):  # (x, y, z, w)
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def slerp(q0, q1, a):
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + a * (q1 - q0)
        return q / np.linalg.norm(q)
    th = np.arccos(d)
    return (np.sin((1 - a) * th) * q0 + np.sin(a * th) * q1) / np.sin(th)


def angle_deg(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def stats(e):
    e = np.asarray(e)
    return {"mean": float(e.mean()), "median": float(np.median(e)), "rmse": float(np.sqrt((e ** 2).mean())),
            "p95": float(np.percentile(e, 95)), "max": float(e.max())}


# ---------- inputs ----------
def frame_timestamps_us(video: Path) -> list[float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=description", "-of", "json", str(video)],
                         capture_output=True, text=True, check=True).stdout
    ts = json.loads(json.loads(out)["format"]["tags"]["description"])
    return [t / 1000.0 for t in ts]  # ns -> us, same clock as tracking_timestamp_us


def load_reference(csv_path: Path):
    t, p, q, g = [], [], [], []
    with csv_path.open() as f:
        for r in csv.DictReader(f):
            t.append(float(r["tracking_timestamp_us"]))
            p.append([float(r[k]) for k in ("tx_world_device", "ty_world_device", "tz_world_device")])
            q.append([float(r[k]) for k in ("qx_world_device", "qy_world_device", "qz_world_device", "qw_world_device")])
            g.append([float(r[k]) for k in ("gravity_x_world", "gravity_y_world", "gravity_z_world")])
    return np.array(t), np.array(p), np.array(q), np.mean(g, 0)


def reference_at(t_us, T, P, Q):
    if t_us < T[0] or t_us > T[-1]:
        return None
    i = int(np.searchsorted(T, t_us))
    i = min(max(i, 1), len(T) - 1)
    a = (t_us - T[i - 1]) / max(T[i] - T[i - 1], 1e-9)
    return P[i - 1] + a * (P[i] - P[i - 1]), quat_to_R(slerp(Q[i - 1], Q[i], a))


def cam_pose(im):
    """Camera centre and camera-to-world rotation from a pycolmap Image (3.x and 4.x APIs)."""
    cfw = im.cam_from_world() if callable(getattr(im, "cam_from_world", None)) else im.cam_from_world
    Rcw = np.array(cfw.rotation.matrix())
    return np.array(im.projection_center()), Rcw.T


def read_json(p: Path):
    return json.loads(p.read_text()) if p.exists() else {}


# ---------- benchmark ----------
def run(ws: Path, video: Path, traj: Path, name: str):
    frames = read_json(ws / "frames" / "frames.json")
    index_of = {k["name"]: k["frame_index"] for k in frames.get("keyframes", [])}
    ts = frame_timestamps_us(video)
    T, P, Q, grav = load_reference(traj)
    up_ref = -grav / np.linalg.norm(grav)

    sfm, norm, train = read_json(ws / "sfm" / "report.json"), read_json(ws / "normalize" / "report.json"), read_json(ws / "train" / "metrics.json")
    out = {"name": name, "generated": time.strftime("%Y-%m-%d %H:%M"), "workspace": str(ws), "video": video.name,
           "reference": f"Aria MPS closed-loop SLAM ({traj.name})",
           "run": {"keyframes_in": sfm.get("keyframes_in"), "registered": sfm.get("registered"), "registered_frac": sfm.get("registered_frac"),
                   "reprojection_px": sfm.get("mean_reprojection_error_px"), "points3D": sfm.get("points3D"), "camera_model": (sfm.get("camera") or {}).get("model"),
                   "units": norm.get("units"), "normalize_status": norm.get("status"), "normalize_warnings": norm.get("warnings", []),
                   "train_views": train.get("train_views"), "holdout_views": train.get("holdout_views"), "iterations": train.get("iterations"),
                   "gaussians": train.get("gaussians"), "psnr_holdout": train.get("psnr_masked"), "psnr_holdout_min": train.get("psnr_min"),
                   "psnr_holdout_color_corrected": train.get("psnr_color_corrected"), "train_seconds": train.get("train_seconds"),
                   "peak_vram_gib": train.get("peak_vram_gib"), "train_resolution": train.get("resolution")}}

    stage_s = {}
    prov = ws / "provenance.jsonl"
    if prov.exists():
        for line in prov.read_text().splitlines():
            r = json.loads(line)
            if r.get("status") in ("ok", "degraded"):
                stage_s[r["stage"]] = r.get("duration_s")
            out["gpu"] = r.get("gpu")
    out["run"]["stage_seconds"] = stage_s
    out["run"]["total_seconds"] = round(sum(v for v in stage_s.values() if v), 1)

    for stage in ("sfm", "normalize"):
        sp = ws / stage / "sparse"
        if not (sp / "images.bin").exists() and not (sp / "images.txt").exists():
            sp = next((d for d in sorted(sp.glob("*")) if d.is_dir()), sp)
        rec = pycolmap.Reconstruction(str(sp))
        names, est_c, est_R, ref_c, ref_R = [], [], [], [], []
        for iid in rec.reg_image_ids():
            im = rec.images[iid]
            fi = index_of.get(im.name)
            if fi is None or fi >= len(ts):
                continue
            ref = reference_at(ts[fi], T, P, Q)
            if ref is None:
                continue
            c, Rwc = cam_pose(im)
            names.append((fi, im.name)); est_c.append(c); est_R.append(Rwc); ref_c.append(ref[0]); ref_R.append(ref[1])
        order = np.argsort([n[0] for n in names])
        est_c, ref_c = np.array(est_c)[order], np.array(ref_c)[order]
        est_R, ref_R = [est_R[i] for i in order], [ref_R[i] for i in order]
        n = len(est_c)
        if n < 3:
            out[stage] = {"error": f"only {n} cameras could be matched to the reference"}
            continue
        extent = float(np.linalg.norm(ref_c.max(0) - ref_c.min(0)))
        path_len = float(np.linalg.norm(np.diff(ref_c, axis=0), axis=1).sum())

        # (a) device origin as is
        s, R, t = umeyama(est_c, ref_c)
        err_a = np.linalg.norm((s * (R @ est_c.T)).T + t - ref_c, axis=1)

        # (b) also fit the fixed device->RGB-camera offset l (in the device frame)
        l = np.zeros(3)
        for _ in range(30):
            target = ref_c + np.array([Rd @ l for Rd in ref_R])
            s_b, R_b, t_b = umeyama(est_c, target)
            aligned = (s_b * (R_b @ est_c.T)).T + t_b
            A = np.vstack(ref_R)
            l_new, *_ = np.linalg.lstsq(A, (aligned - ref_c).reshape(-1), rcond=None)
            if np.linalg.norm(l_new - l) < 1e-6:
                l = l_new
                break
            l = l_new
        target = ref_c + np.array([Rd @ l for Rd in ref_R])
        s_b, R_b, t_b = umeyama(est_c, target)
        err_b = np.linalg.norm((s_b * (R_b @ est_c.T)).T + t_b - target, axis=1)

        # camera orientation in the reference world, then the fixed device->camera mounting rotation
        cam_in_ref = [R @ Rw for Rw in est_R]
        M = sum(ref_R[i].T @ cam_in_ref[i] for i in range(n))
        U, _, Vt = np.linalg.svd(M)
        R_mount = U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt
        ref_cam = [Rd @ R_mount for Rd in ref_R]
        are = [angle_deg(ref_cam[i].T @ cam_in_ref[i]) for i in range(n)]

        def rre(k):
            e = [angle_deg((cam_in_ref[i].T @ cam_in_ref[i + k]).T @ (ref_cam[i].T @ ref_cam[i + k])) for i in range(n - k)]
            return stats(e) if e else None

        def rae(k):
            e = [abs(angle_deg(est_R[i].T @ est_R[i + k]) - angle_deg(ref_R[i].T @ ref_R[i + k])) for i in range(n - k)]
            return stats(e) if e else None

        res = {"cameras_compared": n, "reference_extent_m": round(extent, 3), "reference_path_m": round(path_len, 2),
               "ate_m": {k: round(v, 4) for k, v in stats(err_a).items()},
               "ate_pct_extent": {k: round(100 * v / extent, 2) for k, v in stats(err_a).items()},
               "ate_with_lever_arm_m": {k: round(v, 4) for k, v in stats(err_b).items()},
               "lever_arm_m": [round(float(x), 4) for x in l], "lever_arm_norm_m": round(float(np.linalg.norm(l)), 4),
               "are_deg": {k: round(v, 3) for k, v in stats(are).items()},
               "mount_rotation_deg": round(angle_deg(R_mount), 2),
               "rae_deg_step1": {k: round(v, 3) for k, v in (rae(1) or {}).items()},
               "rae_deg_step10": {k: round(v, 3) for k, v in (rae(10) or {}).items()},
               "rre_deg_step1": {k: round(v, 3) for k, v in (rre(1) or {}).items()},
               "rre_deg_step10": {k: round(v, 3) for k, v in (rre(10) or {}).items()},
               "sim3_scale": round(float(s), 5)}
        if stage == "normalize":
            up_est = R @ np.array([0.0, 1.0, 0.0])          # the pipeline's normalised frame is y-up
            res["up_error_deg"] = round(float(np.degrees(np.arccos(np.clip(up_est @ up_ref, -1, 1)))), 3)
            if norm.get("units") == "metres":
                # pipeline length / reference length - 1: positive means the pipeline's metres are too long
                res["scale_error_pct"] = round(100 * (1 / s - 1), 2)
                prior = norm.get("camera_height_prior_m")
                if prior:
                    res["camera_height_prior_m"] = prior
                    res["implied_camera_height_m"] = round(prior * s, 3)
        out[stage] = res
    return out


def to_markdown(r: dict) -> str:
    run, n = r["run"], r.get("normalize", {})
    sf = r.get("sfm", {})
    f = lambda v, d=2: "–" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))
    a, b = n.get("ate_m", {}), n.get("ate_with_lever_arm_m", {})
    lines = [f"# Video pipeline benchmark: {r['name']}", "",
             f"Generated {r['generated']} on {r.get('gpu', 'unknown GPU')}. Reference: {r['reference']}. "
             f"Footage: `{r['video']}`. Every number below is read from the pipeline's own reports or computed by "
             f"`benchmarks/aria_video.py`; the raw values are in the `.json` file next to this one.", "",
             "## Run", "", "| Measure | Value |", "|---|---|",
             f"| Keyframes registered | {run['registered']} / {run['keyframes_in']} ({f(100 * (run['registered_frac'] or 0), 1)} %) |",
             f"| Mean reprojection error | {f(run['reprojection_px'], 3)} px |",
             f"| Sparse points | {run['points3D']} |",
             f"| Camera model | {run['camera_model']} |",
             f"| Units assigned by the pipeline | {run['units']}{' (' + '; '.join(run['normalize_warnings']) + ')' if run['normalize_warnings'] else ''} |",
             f"| Training | {run['iterations']} iterations, {run['train_views']} views at {run['train_resolution']}, {f(run['train_seconds'], 1)} s, peak VRAM {run['peak_vram_gib']} GiB |",
             f"| Gaussians | {run['gaussians']} |",
             f"| Held-out PSNR ({run['holdout_views']} views) | {f(run['psnr_holdout'])} dB (worst view {f(run['psnr_holdout_min'])} dB, colour-corrected {f(run['psnr_holdout_color_corrected'])} dB) |",
             f"| Total pipeline time | {f(run['total_seconds'], 1)} s ({', '.join(f'{k} {v}' for k, v in run['stage_seconds'].items())}) |", "",
             "## Camera poses against the Aria reference", "",
             f"{n.get('cameras_compared', '–')} registered keyframes matched to the reference by frame timestamp. "
             f"Reference path {f(n.get('reference_path_m'))} m, extent {f(n.get('reference_extent_m'))} m.", "",
             "| Measure | Mean | Median | RMSE | p95 | Max |", "|---|---|---|---|---|---|",
             f"| ATE, device origin (m) | {f(a.get('mean'), 3)} | {f(a.get('median'), 3)} | {f(a.get('rmse'), 3)} | {f(a.get('p95'), 3)} | {f(a.get('max'), 3)} |",
             f"| ATE, lever arm fitted (m) | {f(b.get('mean'), 3)} | {f(b.get('median'), 3)} | {f(b.get('rmse'), 3)} | {f(b.get('p95'), 3)} | {f(b.get('max'), 3)} |",
             f"| ATE, % of extent | {f(n.get('ate_pct_extent', {}).get('mean'))} | {f(n.get('ate_pct_extent', {}).get('median'))} | {f(n.get('ate_pct_extent', {}).get('rmse'))} | {f(n.get('ate_pct_extent', {}).get('p95'))} | {f(n.get('ate_pct_extent', {}).get('max'))} |",
             f"| Absolute rotation error, mounting fitted (deg) | {f(n.get('are_deg', {}).get('mean'), 3)} | {f(n.get('are_deg', {}).get('median'), 3)} | {f(n.get('are_deg', {}).get('rmse'), 3)} | {f(n.get('are_deg', {}).get('p95'), 3)} | {f(n.get('are_deg', {}).get('max'), 3)} |",
             f"| Rotation-angle error, next keyframe, no fit (deg) | {f(n.get('rae_deg_step1', {}).get('mean'), 3)} | {f(n.get('rae_deg_step1', {}).get('median'), 3)} | {f(n.get('rae_deg_step1', {}).get('rmse'), 3)} | {f(n.get('rae_deg_step1', {}).get('p95'), 3)} | {f(n.get('rae_deg_step1', {}).get('max'), 3)} |",
             f"| Rotation-angle error, 10 keyframes apart, no fit (deg) | {f(n.get('rae_deg_step10', {}).get('mean'), 3)} | {f(n.get('rae_deg_step10', {}).get('median'), 3)} | {f(n.get('rae_deg_step10', {}).get('rmse'), 3)} | {f(n.get('rae_deg_step10', {}).get('p95'), 3)} | {f(n.get('rae_deg_step10', {}).get('max'), 3)} |",
             f"| Relative rotation error, next keyframe (deg) | {f(n.get('rre_deg_step1', {}).get('mean'), 3)} | {f(n.get('rre_deg_step1', {}).get('median'), 3)} | {f(n.get('rre_deg_step1', {}).get('rmse'), 3)} | {f(n.get('rre_deg_step1', {}).get('p95'), 3)} | {f(n.get('rre_deg_step1', {}).get('max'), 3)} |",
             f"| Relative rotation error, 10 keyframes apart (deg) | {f(n.get('rre_deg_step10', {}).get('mean'), 3)} | {f(n.get('rre_deg_step10', {}).get('median'), 3)} | {f(n.get('rre_deg_step10', {}).get('rmse'), 3)} | {f(n.get('rre_deg_step10', {}).get('p95'), 3)} | {f(n.get('rre_deg_step10', {}).get('max'), 3)} |", "",
             f"- Fitted device-to-camera offset: {f(n.get('lever_arm_norm_m'), 3)} m; fitted mounting rotation {f(n.get('mount_rotation_deg'), 1)}°.",
             f"- Up-axis error against reference gravity: {f(n.get('up_error_deg'), 2)}°.",
             (f"- Metric scale error: {f(n.get('scale_error_pct'))} % (lengths in the pipeline's metres divided by the reference's, minus 1). "
              f"The pipeline sets scale by assuming the camera is {n.get('camera_height_prior_m')} m above the floor it detects; the reference implies {f(n.get('implied_camera_height_m'))} m." if "scale_error_pct" in n
              else f"- Metric scale: not assessed, the pipeline left the scene {run['units']}; alignment scale {n.get('sim3_scale')}."),
             f"- Raw structure-from-motion poses (before normalisation) give the same ATE up to scale: mean {f(sf.get('ate_pct_extent', {}).get('mean'))} % of extent.", "",
             "## How to read this", "",
             "- The reference is Aria's own SLAM estimate, not surveyed ground truth.",
             "- ATE is measured after a best-fit similarity transform, so it shows the shape of the recovered path, not its placement.",
             "- Rows marked 'fitted' estimate the camera's fixed mounting on the glasses from this same data (3 parameters each), so they are slightly optimistic. Rows marked 'no fit' make no such assumption.",
             "- The lever-arm row fits 3 extra parameters to this same data, so it is slightly optimistic; the true error lies between the two ATE rows.",
             "- One recording. It characterises this run, not the pipeline in general.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--trajectory", type=Path, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/results"))
    a = ap.parse_args()
    r = run(a.workspace.expanduser(), a.video, a.trajectory.expanduser(), a.name)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"{a.name}.json").write_text(json.dumps(r, indent=1))
    (a.out / f"{a.name}.md").write_text(to_markdown(r))
    print(to_markdown(r))
