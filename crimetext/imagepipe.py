"""Run the image pipeline (pipelines/image: COLMAP -> nerfstudio Splatfacto -> pruning -> SAM/CLIP
tagging -> export) on a scene's photos, from the dashboard.

This module does not reimplement any stage. It checks that the pipeline's requirements are on the
machine, starts pipelines/image/quickstart.sh on the scene's photos/ folder, and reports the log.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipelines" / "image"
STAGES = [
    ("EXIF orientation fix", "scripts/fix_exif_orientation.py"),
    ("Structure-from-motion", "colmap feature_extractor, exhaustive_matcher, mapper"),
    ("nerfstudio format", "ns-process-data"),
    ("3D Gaussian Splatting training", "ns-train splatfacto (30,000 iterations)"),
    ("Post-training cleanup", "scripts/prune_checkpoint.py"),
    ("SAM + CLIP region tagging", "scripts/tag_regions.py"),
    ("Text query index", "scripts/query_regions.py"),
    ("Export splat and camera poses", "scripts/export_checkpoint.py, scripts/extract_camera_poses.py"),
]
_job = {}


def _conda_envs() -> list:
    out = []
    for base in ("miniforge3", "miniconda3", "anaconda3"):
        d = Path.home() / base / "envs"
        if d.is_dir():
            out += [p.name for p in d.iterdir() if p.is_dir()]
    return out


def requirements() -> list:
    envs = _conda_envs()
    gpu = ""
    if shutil.which("nvidia-smi"):
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True).stdout.strip()
    mem = int(gpu.split(",")[-1].split()[0]) if gpu else 0
    return [
        {"name": "COLMAP 3.8+", "ok": bool(shutil.which("colmap")), "detail": shutil.which("colmap") or "not installed (system package `colmap`)"},
        {"name": "conda / Miniforge", "ok": bool(shutil.which("conda")) or bool(envs), "detail": "found" if envs or shutil.which("conda") else "not installed"},
        {"name": "conda env crime-image (nerfstudio, gsplat)", "ok": "crime-image" in envs, "detail": "found" if "crime-image" in envs else "missing: run `pipelines/image/quickstart.sh setup`"},
        {"name": "conda env crime-image-tag (SAM, CLIP)", "ok": "crime-image-tag" in envs, "detail": "found" if "crime-image-tag" in envs else "missing: run `pipelines/image/quickstart.sh setup`"},
        {"name": "NVIDIA GPU, 8 GB or more", "ok": mem >= 8000, "detail": gpu or "no NVIDIA GPU found",
         "warn": "the pipeline's documented floor is 8 GB with 18+ training images" if 0 < mem < 8000 else ""},
    ]


def status(case_dir: Path, scene_id: str) -> dict:
    d = case_dir / "scenes" / scene_id
    photos = sorted(p.name for p in (d / "photos").iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")) if (d / "photos").exists() else []
    req = requirements()
    log = d / "pipeline.log"
    job = _job.get(scene_id)
    running = bool(job and job.poll() is None)
    return {"scene": scene_id, "photos": photos, "requirements": req, "ready": all(r["ok"] for r in req) and len(photos) >= 18,
            "min_photos": 18, "stages": [{"name": n, "tool": t} for n, t in STAGES], "running": running,
            "exit_code": None if (not job or running) else job.returncode,
            "log_tail": log.read_text(errors="replace")[-3000:] if log.exists() else "",
            "command": f"pipelines/image/quickstart.sh pipeline --photos-dir {d / 'photos'}"}


def run(case_dir: Path, scene_id: str) -> dict:
    st = status(case_dir, scene_id)
    if st["running"]:
        raise RuntimeError("the pipeline is already running for this scene")
    missing = [r["name"] for r in st["requirements"] if not r["ok"]]
    if missing:
        raise RuntimeError("cannot start, missing on this machine: " + "; ".join(missing))
    if len(st["photos"]) < st["min_photos"]:
        raise RuntimeError(f"need at least {st['min_photos']} overlapping photos, have {len(st['photos'])}")
    d = case_dir / "scenes" / scene_id
    log = (d / "pipeline.log").open("w")
    log.write(f"# started {time.strftime('%Y-%m-%d %H:%M:%S')}\n"); log.flush()
    _job[scene_id] = subprocess.Popen(["bash", str(PIPE / "quickstart.sh"), "pipeline", "--photos-dir", str((d / "photos").resolve())],
                                      cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    return status(case_dir, scene_id)
