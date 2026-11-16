"""3D scenes attached to a case: a Gaussian splat, its source views, a text-query index and
pins that tie entities of the case graph to points in the scene.

A scene is a folder cases/<case>/scenes/<id>/ holding
  scene.json      what it is, which place of the case it stands for, hashes, units
  scene.ply|.spz  the splat (image pipeline: nerfstudio Splatfacto export)
  views.json      source camera poses in the splat frame (from the pipeline's camera_poses.json)
  labels.json     per-photo SAM+CLIP labels (from photo_labels.json)
  queries.json    text queries already run through the pipeline, with their rendered results
  photos/         source photographs, when available
  anchors.json    pins: entity name -> xyz, placed by a person in the dashboard
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

SPLAT_EXT = (".spz", ".ply", ".splat", ".ksplat")
CAVEAT = ("Similarity alone does not separate real matches from absent-object queries: an absent 'a car' scored "
          "0.2592 against 0.3226 for 'blood spatter'. Treat every result as a suggestion to check against the photo.")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _queries_from_summary(md: Path, img_dir: Path, dest: Path) -> list:
    """Parse the pipeline's query_summary.md table into queries.json and copy the rendered results."""
    out = []
    (dest / "queries").mkdir(exist_ok=True)
    for line in md.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not cells[0].startswith('"'):
            continue
        q = cells[0].strip('"')
        render = re.sub(r"[^a-z0-9]+", "_", q.lower()).strip("_") + ".jpg"
        if (img_dir / render).exists():
            shutil.copy2(img_dir / render, dest / "queries" / render)
        verdict = cells[3]
        out.append({"query": q, "similarity": float(cells[1]), "sift_support": int(cells[2]), "verdict": verdict,
                    "ok": verdict.startswith("plausible"), "image": cells[4],
                    "render": "queries/" + render if (dest / "queries" / render).exists() else None})
    return out


def add(case_dir: Path, source: Path, scene_id: str, title: str, location: str, note="", pipeline_dir: Path | None = None,
        up="z", log=print):
    """Register a splat. `pipeline_dir` is the image pipeline folder (pipelines/image) whose ui_web/ and
    demo_assets/ hold the camera poses, photo labels and query results that belong to this splat."""
    if source.suffix.lower() not in SPLAT_EXT:
        raise ValueError(f"not a splat file: {source}")
    dest = case_dir / "scenes" / scene_id
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / ("scene" + source.suffix.lower())
    if not out.exists() or out.stat().st_size != source.stat().st_size:
        shutil.copy2(source, out)
    meta = {"id": scene_id, "title": title, "location": location, "note": note, "units": "unitless", "up": up,
            "pipeline": "image (COLMAP + nerfstudio Splatfacto + SAM/CLIP)", "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "splat": out.name, "splat_sha256": _sha(out), "splat_bytes": out.stat().st_size}
    if pipeline_dir:
        cams = pipeline_dir / "ui_web" / "camera_poses.json"
        if cams.exists():
            (dest / "views.json").write_text(cams.read_text())
            meta["views"] = "views.json"
        labels = pipeline_dir / "ui_web" / "photo_labels.json"
        if labels.exists():
            (dest / "labels.json").write_text(labels.read_text())
            meta["labels"] = "labels.json"
        summary = pipeline_dir / "demo_assets" / "query_summary.md"
        if summary.exists():
            q = _queries_from_summary(summary, pipeline_dir / "demo_assets" / "queries", dest)
            (dest / "queries.json").write_text(json.dumps(q, indent=1))
            meta["queries"] = "queries.json"
    (dest / "photos").mkdir(exist_ok=True)
    (dest / "scene.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    if not (dest / "anchors.json").exists():
        (dest / "anchors.json").write_text("[]")
    log(f"scene {scene_id}: {out.name} ({meta['splat_bytes'] / 1e6:.1f} MB) -> {location}")
    return meta


def add_package(case_dir: Path, package: Path, scene_id: str, title: str, location: str, note="", log=print):
    """Import a Scene Package written by the video pipeline (crimesplat-video): splat, camera path,
    frame thumbnails. The camera path becomes views.json in the convention the viewer already uses."""
    man = json.loads((package / "manifest.json").read_text())
    splat = package / man["scene"]["splat"]
    dest = case_dir / "scenes" / scene_id
    (dest / "photos").mkdir(parents=True, exist_ok=True)
    out = dest / ("scene" + splat.suffix.lower())
    shutil.copy2(splat, out)
    up = man.get("up", [0, 1, 0])
    meta = {"id": scene_id, "title": title, "location": location, "note": note, "units": man.get("units", "unitless"),
            "up": "xyz"[max(range(3), key=lambda i: abs(up[i]))], "pipeline": "video (crimesplat-video: COLMAP + gsplat MCMC)",
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "splat": out.name, "splat_sha256": _sha(out),
            "splat_bytes": out.stat().st_size, "quality": man.get("quality"),
            "source_media": [{k: s.get(k) for k in ("id", "sha256", "duration_s", "fps")} for s in man.get("sources", [])]}
    traj = package / man["scene"].get("trajectory", "_none_")
    if traj.is_file():
        cams = []
        for f in json.loads(traj.read_text())["frames"]:
            m = f["c2w"]            # OpenCV camera-to-world -> the viewer's +Z-forward convention: R * diag(-1, -1, 1)
            cams.append({"image": f["name"], "t": f.get("t"), "position": [m[0][3], m[1][3], m[2][3]],
                         "rotation_matrix_row_major": [-m[0][0], -m[0][1], m[0][2], -m[1][0], -m[1][1], m[1][2], -m[2][0], -m[2][1], m[2][2]]})
        (dest / "views.json").write_text(json.dumps({"cameras": cams}))
        meta["views"] = "views.json"
    thumbs = package / man["scene"].get("thumbs", "_none_")
    if thumbs.is_dir():
        shutil.copytree(thumbs, dest / "photos", dirs_exist_ok=True)
    (dest / "scene.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    if not (dest / "anchors.json").exists():
        (dest / "anchors.json").write_text("[]")
    log(f"scene {scene_id}: imported video Scene Package -> {location}")
    return meta


def load_all(case_dir: Path) -> list:
    out = []
    for f in sorted((case_dir / "scenes").glob("*/scene.json")) if (case_dir / "scenes").exists() else []:
        meta = json.loads(f.read_text())
        d = f.parent
        for k in ("anchors", "queries", "labels"):
            p = d / f"{k}.json"
            meta[k if k != "labels" else "label_data"] = json.loads(p.read_text()) if p.exists() else ([] if k != "labels" else None)
        meta["photos"] = sorted(p.name for p in (d / "photos").iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")) if (d / "photos").exists() else []
        meta["live_query"] = (d / "region_lookup.json").exists()
        out.append(meta)
    return out


def set_anchor(case_dir: Path, scene_id: str, entity: str, xyz, placed_by="", remove=False, demo=False) -> list:
    """One pin per entity per scene. Entities are stored by name so pins survive a rebuild."""
    f = case_dir / "scenes" / scene_id / "anchors.json"
    if not f.parent.is_dir() or "/" in scene_id or ".." in scene_id:
        raise ValueError("unknown scene")
    anchors = [a for a in (json.loads(f.read_text()) if f.exists() else []) if a["entity"] != entity]
    if not remove:
        anchors.append({"entity": entity, "xyz": [round(float(v), 4) for v in xyz][:3], "method": "human pin",
                        "placed_by": placed_by[:80], "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "demo": bool(demo)})
    f.write_text(json.dumps(anchors, indent=1, ensure_ascii=False))
    return anchors


def query(case_dir: Path, scene_id: str, text: str, top_k=6) -> dict:
    """Text query against a scene, in the response shape of the image pipeline's query_server.py.

    Live mode needs the pipeline's region_lookup.json (SAM regions + CLIP embeddings + 3D points) in the
    scene folder and open_clip installed. Without them the answer comes from the queries the pipeline
    already ran (queries.json) and from the per-photo labels, and says so."""
    d = case_dir / "scenes" / scene_id
    text = text.strip()
    if not text:
        return {"matched": False, "message": "Empty query."}
    lookup = d / "region_lookup.json"
    if lookup.exists():
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipelines" / "image" / "scripts"))
            import query_regions  # the image pipeline's own matcher
            ms = query_regions.top_k_matches(str(lookup), text, top_k)
            res = [{"image": Path(m.get("frame_path", m.get("image", ""))).name, "similarity": round(float(m["similarity"]), 4),
                    "sift_support": m.get("n_support_points"), "point3d": m.get("point3d_final"), "localized": True,
                    "viewpoint_id": Path(m.get("frame_path", m.get("image", ""))).name} for m in ms]
            return {"matched": bool(res), "mode": "live CLIP", "query": text, "results": res, "caveat": CAVEAT}
        except Exception as e:      # fall through to the precomputed answers, and say why
            why = f"live CLIP unavailable ({type(e).__name__}: {e})"
    else:
        why = "the pipeline's region_lookup.json is not in this scene folder"
    qs = json.loads((d / "queries.json").read_text()) if (d / "queries.json").exists() else []
    labels = json.loads((d / "labels.json").read_text()) if (d / "labels.json").exists() else {"images": []}
    views = {c["image"] for c in json.loads((d / "views.json").read_text())["cameras"]} if (d / "views.json").exists() else set()
    words = set(re.findall(r"[a-z]+", text.lower()))

    def overlap(s):
        w = set(re.findall(r"[a-z]+", s.lower()))
        return len(words & w) / max(1, len(words | w))
    results = []
    best = max(qs, key=lambda q: overlap(q["query"]), default=None)
    if best and overlap(best["query"]) >= 0.5:
        results.append({"image": best["image"], "similarity": best["similarity"], "sift_support": best["sift_support"],
                        "localized": best["image"] in views, "viewpoint_id": best["image"] if best["image"] in views else None,
                        "render": best["render"], "verdict": best["verdict"], "ok": best["ok"], "matched_query": best["query"]})
    for im in labels.get("images", []):
        for lab in im.get("top_labels", []):
            if overlap(lab["label"]) >= 0.5:
                results.append({"image": im["filename"], "similarity": lab["similarity"], "sift_support": None,
                                "localized": im["filename"] in views, "viewpoint_id": im["filename"] if im["filename"] in views else None,
                                "bbox_resized": lab.get("bbox_resized"), "label": lab["label"]})
    seen, uniq = set(), []
    for r in sorted(results, key=lambda r: (not r.get("render"), -r["similarity"])):
        if r["image"] not in seen:
            seen.add(r["image"]); uniq.append(r)
    known = sorted({q["query"] for q in qs} | set(labels.get("vocabulary", [])))
    return {"matched": bool(uniq), "mode": "precomputed", "mode_reason": why, "query": text, "results": uniq[:top_k],
            "known_queries": known, "caveat": CAVEAT,
            "message": None if uniq else "No stored result for that text. Stored queries: " + ", ".join(known)}
