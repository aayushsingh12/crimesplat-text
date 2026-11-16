#!/usr/bin/env python3
"""
Minimal local query API for the web splat viewer: GET /query?text=...
returns the top-k ranked matches (closest first) from the existing
SAM+CLIP region lookup, in a shape the viewer's JS can use to snap the
camera to one of the 20 preset viewpoints
(pipelines/image/ui_web/camera_poses.json), show the matched region's
real source photo (pipelines/image/ui_web/photos/, built alongside
photo_labels.json), and let someone step through candidates from closest
to farthest match -- or, honestly, tell the user a given candidate can't
be located in the scene (a 2D-only region).

Does NOT reimplement matching: imports query_regions.py's existing
functions directly (build_clip_model / load_combined_records /
encode_query / rank_records / best_match_dict / top_k_matches, all
unchanged from the CLI path -- see query_regions.py's own docstring for
how the original refactor was verified byte-identical to the pre-refactor
CLI output before this file was written) and calls them. The only new
thing here is the HTTP layer and loading CLIP once at startup instead of
once per request.

Run:
    conda activate crime-image-tag
    python pipelines/image/ui_web/query_server.py
    # serves http://localhost:5001/query?text=...

Then serve the viewer itself separately (different origin/port -- CORS is
handled below):
    cd pipelines/image/ui_web && python3 -m http.server 8000
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import query_regions  # noqa: E402  -- imported, not copied/rewritten

REPO_ROOT = Path(__file__).resolve().parents[3]
LOOKUP = REPO_ROOT / "pipelines/image/query/region_lookup.json"
LOOKUP_2D_ONLY = REPO_ROOT / "pipelines/image/query/region_lookup_2d_only.json"
CAMERA_POSES = Path(__file__).parent / "camera_poses.json"

# Standing caveat, reused VERBATIM from pipelines/image/ui/app.py's
# permanent bottom banner -- not reworded, not conditionally shown based
# on a similarity threshold (no threshold logic is built here, same
# standing rule as every other task this session: phase2_decision.md's
# finding is that score alone does not reliably separate real matches
# from wrong ones, so this caveat accompanies EVERY localized match,
# always, rather than the server pretending it can classify confidence).
CAVEAT = (
    "Similarity score alone does not reliably separate real matches from "
    "absent-object queries in this scene — 0.2592 (\"a car\", absent) and "
    "0.3226 (\"blood spatter\", present) both sit in the same moderate "
    "CLIP-similarity band, not the wide separation a safe fixed threshold "
    "would need. Consistent with known CLIP zero-shot score compression. "
    "As it stands, the system will confidently mark a wrong answer for a "
    "query about something that isn't in the scene, with nothing in the "
    "output to distinguish that from a real match. Full detail in "
    "pipelines/image/docs/phase2_decision.md."
)

app = Flask(__name__)

print("[query_server] loading CLIP once at startup (not per-request)...")
_t0 = time.time()
_model, _tokenizer = query_regions.build_clip_model()
print(f"[query_server] CLIP loaded in {time.time() - _t0:.1f}s")

_camera_image_names = {
    c["image"] for c in __import__("json").loads(CAMERA_POSES.read_text())["cameras"]
}
print(f"[query_server] {len(_camera_image_names)} preset viewpoints available")


@app.after_request
def add_cors_headers(resp):
    # The viewer is served from a different origin (its own static file
    # server, a different port) -- allow it to fetch this API.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def _format_candidate(m: dict) -> dict:
    localized = m["localized"]
    viewpoint_id = m["image"] if localized else None
    if localized and viewpoint_id not in _camera_image_names:
        # Shouldn't happen (region_lookup.json's images are exactly the
        # 20 registered/camera_poses.json images), but check rather than
        # assume -- if it ever does, don't silently pretend there's a
        # viewpoint to jump to.
        print(f"[query_server] WARNING: matched image {viewpoint_id!r} has no entry in camera_poses.json")
        localized = False
    return {
        "image": m["image"],
        "photo_path": f"photos/{m['image']}",
        "localized": localized,
        "viewpoint_id": viewpoint_id,
        "similarity": round(m["similarity"], 4),
        "sift_support": m.get("num_support_points") if localized else None,
        # bbox is in the resized-for-SAM pixel space (see tag_regions.py);
        "bbox_resized": m.get("bbox_resized"),
        "resized_wh": m.get("resized_wh"),
        "message": None if localized else query_regions.NOT_LOCALIZED_MESSAGE,
    }


@app.route("/query")
def query():
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify({"matched": False, "message": "Empty query."}), 400
    try:
        top_k = max(1, min(20, int(request.args.get("top_k", 8))))
    except ValueError:
        top_k = 8

    t0 = time.time()
    matches = query_regions.top_k_matches(
        text, LOOKUP, LOOKUP_2D_ONLY if LOOKUP_2D_ONLY.exists() else None,
        k=top_k, model=_model, tokenizer=_tokenizer,
    )
    elapsed = time.time() - t0
    results = [_format_candidate(m) for m in matches]
    top = results[0] if results else None
    print(
        f"[query_server] query={text!r} top_k={top_k} "
        f"top1=({top['image']!r} sim={top['similarity']} localized={top['localized']}) "
        f"({elapsed:.2f}s)" if top else f"[query_server] query={text!r} -- no results ({elapsed:.2f}s)"
    )

    response = {
        "matched": bool(results),
        "results": results,
        # top-level fields mirror results[0], kept for the original
        # single-result client code path -- additive, not a breaking change.
        "localized": top["localized"] if top else False,
        "viewpoint_id": top["viewpoint_id"] if top else None,
        "similarity": top["similarity"] if top else None,
        "sift_support": top["sift_support"] if top else None,
        "message": top["message"] if top else None,
        "caveat": CAVEAT,
    }
    return jsonify(response)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
