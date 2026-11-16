#!/usr/bin/env python3
"""
Phase 2 language-query layer, step 5 (text side): encode a text query with
CLIP's text encoder, cosine-similarity it against every stored region
embedding, print/save the best match(es). Runs in the `crime-image-tag`
env (CPU-only).

Optionally also searches the 2D-only regions (--lookup-2d-only,
region_lookup_2d_only.json -- the 10 galanakis2021 photos COLMAP never
registered, see phase2_decision.md and Task 3's registration-ceiling
finding). Ranking is over the COMBINED pool of both sets: if a 2D-only
region's embedding is genuinely the closest match to the query, it wins
the #1 slot rather than being silently excluded -- but its match is
reported honestly (localized=False, no 3D point, an explicit message)
instead of being rendered as if it were a real 3D location. This is the
deliberate fix for the earlier design (region_lookup_2d_only.json was
built as a wholly separate, unqueryable artifact) which correctly kept
2D-only content out of the 3D scene, but silently dropped its content
from query results entirely -- crashing or silence are both worse than
an honest "found, but not locatable" answer.

Usage:
    conda activate crime-image-tag
    python pipelines/image/scripts/query_regions.py \\
        --lookup pipelines/image/query/region_lookup.json \\
        --lookup-2d-only pipelines/image/query/region_lookup_2d_only.json \\
        --query "blood splatter" \\
        --top-k 3 \\
        --out-match pipelines/image/query/last_match.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

NOT_LOCALIZED_MESSAGE = (
    "Found in photo evidence, but this image was not part of the 3D "
    "reconstruction and cannot be located in the scene."
)


def load_records(lookup_path: Path, localized: bool) -> list[dict]:
    data = json.loads(lookup_path.read_text())
    records = data["records"]
    for r in records:
        r["localized"] = localized
    return records


def load_combined_records(lookup_path: Path, lookup_2d_only_path: Path | None):
    """Same combined-pool loading main() always did -- extracted verbatim
    (no logic change) so both the CLI and an importer (e.g. a query API
    server) build the identical pool the identical way."""
    records = load_records(lookup_path, localized=True)
    n_localized = len(records)
    n_2d_only = 0
    if lookup_2d_only_path is not None:
        records_2d = load_records(lookup_2d_only_path, localized=False)
        n_2d_only = len(records_2d)
        records = records + records_2d
    if not records:
        raise SystemExit(f"[query_regions] {lookup_path} has zero region records -- run tag_regions.py first")
    return records, n_localized, n_2d_only


def build_clip_model():
    """Same model construction main() always did -- extracted verbatim so
    a long-lived caller (a server) can load it once and reuse it across
    many queries instead of paying this cost per-request."""
    import open_clip

    model, _, _ = open_clip.create_model_and_transforms("ViT-B-32-quickgelu", pretrained="openai")
    tokenizer = open_clip.get_tokenizer("ViT-B-32-quickgelu")
    model.eval()
    return model, tokenizer


def encode_query(model, tokenizer, query: str) -> np.ndarray:
    with torch.no_grad():
        text_tok = tokenizer([query])
        text_emb = model.encode_text(text_tok)
        text_emb = text_emb / text_emb.norm(dim=-1, keepdim=True)
        return text_emb.squeeze(0).numpy()


def rank_records(records: list[dict], text_emb: np.ndarray, top_k: int):
    embeddings = np.array([r["clip_embedding"] for r in records])  # already L2-normalized at tag time
    sims = embeddings @ text_emb
    order = np.argsort(-sims)[:top_k]
    return order, sims


def print_ranking(records, order, sims, query, n_localized, n_2d_only):
    pool_desc = f"{n_localized} 3D-localized" + (f" + {n_2d_only} 2D-only" if n_2d_only else "")
    print(f"[query_regions] query: {query!r} -- top {len(order)} of {len(records)} regions ({pool_desc})")
    for rank, i in enumerate(order):
        r = records[i]
        if r["localized"]:
            print(
                f"  #{rank + 1} sim={sims[i]:.4f}  image={r['image']}  [3D-localized]  "
                f"bbox_resized={r['bbox_resized']}  support_pts={r['num_support_points']}  "
                f"point3d_final={[round(v, 4) for v in r['point3d_final']]}"
            )
        else:
            print(
                f"  #{rank + 1} sim={sims[i]:.4f}  image={r['image']}  [2D-ONLY, NOT IN 3D RECONSTRUCTION]  "
                f"bbox_resized={r['bbox_resized']}"
            )


def best_match_dict(records, order, sims, query, rank: int = 0) -> dict:
    """rank=0 is the original (only) behavior this function had; the rank
    parameter is a pure addition so a caller can build the same dict shape
    for any position in the ranking, not just #1 -- ranking/scoring itself
    (order, sims) is unchanged, this only picks which entry to format."""
    idx = order[rank]
    best = dict(records[idx])
    best["query"] = query
    best["similarity"] = float(sims[idx])
    if not best["localized"]:
        best["message"] = NOT_LOCALIZED_MESSAGE
        best.setdefault("point3d_final", None)
    return best


def top1_match(query: str, lookup_path: Path, lookup_2d_only_path: Path | None = None, model=None, tokenizer=None) -> dict:
    """High-level convenience entry point for importers (e.g. the query
    API server in ui_web/query_server.py): returns the exact same best-
    match dict shape --out-match writes to disk, without needing a
    subprocess or a file round-trip. Pass an already-loaded model/tokenizer
    (from build_clip_model()) to skip reloading CLIP on every call -- the
    matching computation itself is identical to the CLI path either way,
    just re-used via these same functions rather than re-implemented."""
    if model is None or tokenizer is None:
        model, tokenizer = build_clip_model()
    records, n_localized, n_2d_only = load_combined_records(lookup_path, lookup_2d_only_path)
    text_emb = encode_query(model, tokenizer, query)
    order, sims = rank_records(records, text_emb, top_k=1)
    return best_match_dict(records, order, sims, query)


def top_k_matches(
    query: str, lookup_path: Path, lookup_2d_only_path: Path | None = None, k: int = 8, model=None, tokenizer=None
) -> list[dict]:
    """Same as top1_match, generalized to the top k ranked candidates
    (closest match first) -- e.g. for a UI that lets someone step through
    candidates from closest to farthest, not just jump to #1. Reuses the
    identical load/encode/rank pipeline; only the number of results
    returned differs."""
    if model is None or tokenizer is None:
        model, tokenizer = build_clip_model()
    records, n_localized, n_2d_only = load_combined_records(lookup_path, lookup_2d_only_path)
    text_emb = encode_query(model, tokenizer, query)
    order, sims = rank_records(records, text_emb, top_k=k)
    return [best_match_dict(records, order, sims, query, rank=r) for r in range(len(order))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookup", type=Path, required=True, help="region_lookup.json -- 3D-localized regions")
    ap.add_argument(
        "--lookup-2d-only",
        type=Path,
        default=None,
        help="region_lookup_2d_only.json -- optional, the COLMAP-unregistered images' 2D-only regions",
    )
    ap.add_argument("--query", type=str, required=True)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--out-match", type=Path, default=None, help="save the single best match as JSON, for the render handoff")
    args = ap.parse_args()

    records, n_localized, n_2d_only = load_combined_records(args.lookup, args.lookup_2d_only)
    model, tokenizer = build_clip_model()
    text_emb = encode_query(model, tokenizer, args.query)
    order, sims = rank_records(records, text_emb, args.top_k)
    print_ranking(records, order, sims, args.query, n_localized, n_2d_only)

    if args.out_match is not None:
        best = best_match_dict(records, order, sims, args.query)
        if not best["localized"]:
            print(f"[query_regions] NOTE: best match is 2D-only -- {NOT_LOCALIZED_MESSAGE}")
        args.out_match.parent.mkdir(parents=True, exist_ok=True)
        args.out_match.write_text(json.dumps(best, indent=1))
        print(f"[query_regions] wrote best match to {args.out_match}")


if __name__ == "__main__":
    main()
