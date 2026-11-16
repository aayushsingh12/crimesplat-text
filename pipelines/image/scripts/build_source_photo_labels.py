#!/usr/bin/env python3
"""
Builds the data for the source-photo fallback panel in pipelines/image/ui_web/
(all 30 galanakis2021 photos, browsable, each labeled).

Context: an untracked, uncommitted directory (pipelines/image/label_browser/)
was found on disk with a similar-looking tool already built. Read directly
before writing anything here (not assumed from the PDF someone mentioned,
and not assumed from that directory's own README either): its build_data.py
scores each image's regions against 8 "prototype" embeddings pulled from
pipelines/image/query/batch/*_match.json -- but those files are query_regions.py's
--out-match output, i.e. the WINNING REGION's *image* embedding for each text
query, not the text embedding itself. So that tool's scores are image-to-image
CLIP similarity (one region crop vs. another), which is a different, much
higher-scoring metric (checked: 0.90-0.94 range on a real run) than the
text-to-image similarity documented everywhere else in this project
(phase2_decision.md's score-compression finding is specifically about text
queries, ~0.25-0.35 range). Displaying those two ranges side by side without
extreme care would be actively misleading, and running the required sanity
check against that tool exposed a real problem with just presenting its
top-1 label uncritically: IMG_0463.jpg's top label came out "mannequin"
(0.9367), with "blood stain" only 3rd (0.8986) -- not wrong exactly (that
tool never claimed text relevance), but not what a reader would expect
either.

So: rebuilt fresh here, scoring against genuine CLIP TEXT embeddings of the
same 8-word vocabulary (kept as-is -- it's not the vocabulary that was the
problem, and it's already the exact set query_summary.md documents actually
being run and verified) via query_regions.py's own build_clip_model() /
encode_query() (imported, not reimplemented). This keeps scores in the same
metric space, and therefore the same honest caveat, as every other query
result in this project.

Covers all 30 images: the 20 registered ones (region_lookup.json) AND the 10
2D-only ones (region_lookup_2d_only.json) -- the fallback panel's whole point
is to show real content for images the 3D viewer can't reach, so they get
real labels too, just visually marked as not-3D-locatable (same convention
encoding_coverage.png already uses: desaturated + distinguishing marker).

Also copies the 30 corrected source photos into pipelines/image/ui_web/photos/
so the static file server (rooted at ui_web/) can actually serve them --
they live outside that directory otherwise. Gitignored, like every other
regenerable derived artifact in this project.

Usage:
    conda activate crime-image-tag
    python pipelines/image/scripts/build_source_photo_labels.py
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import query_regions  # noqa: E402  -- imported, not copied/rewritten

REPO_ROOT = Path(__file__).resolve().parents[3]
PHOTOS_DIR = REPO_ROOT / "pipelines/image/data/galanakis2021/photos_corrected"
LOOKUP = REPO_ROOT / "pipelines/image/query/region_lookup.json"
LOOKUP_2D_ONLY = REPO_ROOT / "pipelines/image/query/region_lookup_2d_only.json"
UI_WEB_DIR = REPO_ROOT / "pipelines/image/ui_web"
OUT_JSON = UI_WEB_DIR / "photo_labels.json"
OUT_PHOTOS_DIR = UI_WEB_DIR / "photos"

# Kept from the existing (uncommitted, image-to-image-scored) label_browser/
# tool's vocabulary -- these 8 words are exactly query_summary.md's already-
# verified batch of test queries, not invented fresh.
VOCABULARY = [
    "blood stain", "body", "evidence marker", "floor",
    "footprint", "mannequin", "shoe", "weapon",
]


def main() -> None:
    photos = sorted(PHOTOS_DIR.glob("*.jpg"))
    print(f"[build_source_photo_labels] {len(photos)} source photos found")

    localized_records = json.loads(LOOKUP.read_text())["records"]
    unlocalized_records = json.loads(LOOKUP_2D_ONLY.read_text())["records"]

    regions_by_image: dict[str, list[dict]] = defaultdict(list)
    for r in localized_records:
        regions_by_image[r["image"]].append(r)
    registered_images = set(regions_by_image.keys())
    for r in unlocalized_records:
        regions_by_image[r["image"]].append(r)

    model, tokenizer = query_regions.build_clip_model()
    vocab_embeddings = {word: query_regions.encode_query(model, tokenizer, word) for word in VOCABULARY}
    print(f"[build_source_photo_labels] encoded {len(VOCABULARY)} vocabulary text embeddings")

    images = []
    OUT_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    for photo in photos:
        shutil.copy2(photo, OUT_PHOTOS_DIR / photo.name)

        regions = regions_by_image.get(photo.name, [])
        registered = photo.name in registered_images
        has_any_regions = bool(regions)

        label_scores = []
        if regions:
            region_embeddings = np.array([r["clip_embedding"] for r in regions])
            for word, text_emb in vocab_embeddings.items():
                sims = region_embeddings @ text_emb
                best_idx = int(np.argmax(sims))
                label_scores.append(
                    {
                        "label": word,
                        "similarity": round(float(sims[best_idx]), 4),
                        "region_mask_idx": regions[best_idx].get("mask_idx"),
                        "bbox_resized": regions[best_idx].get("bbox_resized"),
                    }
                )
            label_scores.sort(key=lambda item: item["similarity"], reverse=True)

        images.append(
            {
                "filename": photo.name,
                "photo_path": f"photos/{photo.name}",
                "registered": registered,
                "region_count": len(regions),
                "top_labels": label_scores[:3],
                "note": (
                    "3D-queryable (COLMAP-registered)."
                    if registered
                    else "2D-only -- not part of the 3D reconstruction, cannot be located in the scene."
                ),
            }
        )
        print(
            f"  {photo.name}: registered={registered} regions={len(regions)} "
            + (f"top={label_scores[0]['label']} ({label_scores[0]['similarity']})" if label_scores else "(no regions)")
        )

    payload = {
        "vocabulary": VOCABULARY,
        "generated_from": {
            "lookup": str(LOOKUP.relative_to(REPO_ROOT)),
            "lookup_2d_only": str(LOOKUP_2D_ONLY.relative_to(REPO_ROOT)),
        },
        "summary": {
            "total_images": len(images),
            "registered_images": sum(1 for i in images if i["registered"]),
            "unregistered_images": sum(1 for i in images if not i["registered"]),
        },
        "images": images,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=1))
    print(f"[build_source_photo_labels] wrote {OUT_JSON} and {len(photos)} photos to {OUT_PHOTOS_DIR}")


if __name__ == "__main__":
    main()
