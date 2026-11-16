"""Connector to the video pipeline (the crimesplat-video repository).

Nothing of that pipeline is copied here. This module finds the repository, checks that it can
run, starts `crimesplat init` + `crimesplat run` on a stored footage file, and when the pipeline
has written its Scene Package, imports that package as a 3D scene of the case.

Where the repository is: "video_pipeline_dir" in case.json, else $CRIMESPLAT_VIDEO, else
~/Projects/crimesplat-video.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import scenes

VID = (".mp4", ".mov", ".mkv", ".avi", ".webm")
FOOTAGE = ["handheld", "bodycam", "drone", "news"]
STAGES = ["ingest (hash, probe)", "keyframes (sharpest per time bin)", "masks (people, vehicles)", "camera poses (COLMAP)",
          "normalise (floor, up, scale)", "train splat (gsplat MCMC)", "package (splat, camera path, thumbnails, hashes)"]
_jobs = {}


def repo_dir(case_dir: Path) -> Path:
    cfg = json.loads((case_dir / "case.json").read_text())
    return Path(cfg.get("video_pipeline_dir") or os.environ.get("CRIMESPLAT_VIDEO") or Path.home() / "Projects" / "crimesplat-video").expanduser()


def _gpu_mb() -> tuple[str, int]:
    if not shutil.which("nvidia-smi"):
        return "", 0
    out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    try:
        return out, int(out.split(",")[-1].split()[0])
    except Exception:
        return out, 0


def profile_for(mem_mb: int) -> str:
    return "laptop-4gb" if mem_mb < 7000 else "gpu-8gb" if mem_mb < 20000 else "gpu-24gb"


def requirements(case_dir: Path) -> list:
    repo = repo_dir(case_dir)
    gpu, mem = _gpu_mb()
    has_repo = (repo / "pipeline" / "pyproject.toml").exists()
    return [
        {"name": "crimesplat-video repository", "ok": has_repo, "detail": str(repo) if has_repo else f"not found at {repo}: set video_pipeline_dir in case.json"},
        {"name": "uv", "ok": bool(shutil.which("uv")), "detail": shutil.which("uv") or "not installed"},
        {"name": "pipeline environment", "ok": (repo / "pipeline" / ".venv").exists(), "detail": "found" if (repo / "pipeline" / ".venv").exists() else "missing: run scripts/setup.sh in the repository"},
        {"name": "ffmpeg", "ok": bool(shutil.which("ffmpeg")), "detail": shutil.which("ffmpeg") or "not installed"},
        {"name": "NVIDIA GPU", "ok": mem > 0, "detail": f"{gpu} -> profile {profile_for(mem)}" if mem else "no NVIDIA GPU found"},
    ]


def _job_id(case_dir: Path, file: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", f"{case_dir.name}_{Path(file).stem}".lower()).strip("_")[:60]


def _meta(case_dir: Path) -> dict:
    p = case_dir / "video" / "jobs.json"
    return json.loads(p.read_text()) if p.exists() else {}


def status(case_dir: Path) -> dict:
    """Footage on file with the state of each: stored, running, failed, or in the case as a scene.
    A finished job whose Scene Package exists is imported here, once."""
    d, repo, meta = case_dir / "video", repo_dir(case_dir), _meta(case_dir)
    files = []
    for p in sorted(d.iterdir()) if d.exists() else []:
        if p.suffix.lower() not in VID:
            continue
        jid, job = _job_id(case_dir, p.name), _jobs.get(p.name)
        m = meta.get(p.name, {})
        running = bool(job and job.poll() is None)
        package = repo / "workspace" / jid / "package"
        attached = (case_dir / "scenes" / jid / "scene.json").exists()
        state = "stored"
        if running:
            state = "running"
        elif attached:
            state = "in case as 3D scene"
        elif m and (package / "manifest.json").exists():
            scenes.add_package(case_dir, package, jid, m.get("title") or p.stem, m.get("location", ""),
                               note=f"Reconstructed by the video pipeline from {p.name} ({m.get('footage')} footage).")
            from . import fuse
            fuse.build(case_dir, log=lambda *_: None)
            state = "in case as 3D scene"
        elif m and not running:
            state = "failed" if (job is None or job.returncode) else "finished without a package"
        log = d / (p.name + ".log")
        files.append({"file": p.name, "bytes": p.stat().st_size, "job": jid, "state": state, "scene": jid if state.startswith("in case") else None,
                      "footage": m.get("footage"), "location": m.get("location"),
                      "log_tail": log.read_text(errors="replace")[-1500:] if log.exists() and state in ("running", "failed", "finished without a package") else ""})
    req = requirements(case_dir)
    return {"files": files, "requirements": req, "ready": all(r["ok"] for r in req), "footage_types": FOOTAGE, "stages": STAGES,
            "repo": str(repo), "profile": profile_for(_gpu_mb()[1])}


def run(case_dir: Path, file: str, footage: str, location: str, title: str = "") -> dict:
    src = case_dir / "video" / Path(file).name
    if not src.exists():
        raise ValueError("no such footage file")
    if footage not in FOOTAGE:
        raise ValueError("footage type must be one of " + ", ".join(FOOTAGE))
    if not location.strip():
        raise ValueError("say which place of the case this footage shows")
    missing = [r["name"] for r in requirements(case_dir) if not r["ok"]]
    if missing:
        raise RuntimeError("cannot start, missing: " + "; ".join(missing))
    if src.name in _jobs and _jobs[src.name].poll() is None:
        raise RuntimeError("already running for this file")
    repo, jid = repo_dir(case_dir), _job_id(case_dir, src.name)
    meta = _meta(case_dir)
    meta[src.name] = {"job": jid, "footage": footage, "location": location.strip(), "title": title.strip(),
                      "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (case_dir / "video" / "jobs.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    profile = profile_for(_gpu_mb()[1])
    init = "" if (repo / "cases" / f"{jid}.yaml").exists() else \
        f'uv run crimesplat init {jid} --source "{src.resolve()}" --footage {footage} --profile {profile} && '
    log = (case_dir / "video" / (src.name + ".log")).open("w")
    log.write(f"# {time.strftime('%Y-%m-%d %H:%M:%S')} {jid} ({footage}, {profile})\n"); log.flush()
    _jobs[src.name] = subprocess.Popen(["bash", "-c", init + f"uv run crimesplat run {jid}"], cwd=repo / "pipeline",
                                       stdout=log, stderr=subprocess.STDOUT)
    return status(case_dir)
