#!/usr/bin/env python3
"""
Build a train/eval split view over the pinned galanakis2021 COLMAP
reconstruction, for a given random seed and eval count.

Why this exists: nerfstudio's default --eval-mode fraction
(get_train_eval_split_fraction in nerfstudio/data/utils/dataparsers_utils.py)
is NOT random -- it picks training images via np.linspace over the frame
list, a fully deterministic strided selection with no seed involved anywhere
in the code path. There is no CLI flag to randomize it because there is
nothing to randomize. To get genuinely different, seed-varied held-out sets
across repeated runs, this script uses nerfstudio's other supported split
mechanism instead: --eval-mode filename, which splits on whether "train" or
"eval" appears in each image's filename. This script does the (seeded,
reproducible) random assignment of which images get which tag.

Does not touch the pinned pipelines/image/data/galanakis2021/colmap/
directory at all -- writes a self-contained new directory with a copy of
transforms.json (frame file_paths renamed) plus symlinks back to the real
image files and the real sparse_pc.ply. No pixel data is duplicated, and the
underlying COLMAP reconstruction (poses, points) is unchanged.

Usage:
    python pipelines/image/scripts/make_eval_split.py \\
        --source pipelines/image/data/galanakis2021/colmap \\
        --output pipelines/image/data/galanakis2021/eval_splits/seed1 \\
        --seed 1 --eval-count 4
"""
import argparse
import json
import os
import random
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, type=Path, help="pinned colmap/ dir with transforms.json")
    p.add_argument("--output", required=True, type=Path, help="new dir to write the split view into")
    p.add_argument("--seed", required=True, type=int)
    p.add_argument("--eval-count", required=True, type=int)
    args = p.parse_args()

    src_transforms_path = args.source / "transforms.json"
    data = json.loads(src_transforms_path.read_text())
    frames = data["frames"]
    n = len(frames)
    if args.eval_count >= n:
        raise SystemExit(f"eval-count {args.eval_count} >= total frames {n}")

    rng = random.Random(args.seed)
    eval_indices = set(rng.sample(range(n), args.eval_count))

    args.output.mkdir(parents=True, exist_ok=True)
    images_out = args.output / "images"
    images_out.mkdir(exist_ok=True)

    eval_files = []
    train_files = []
    new_frames = []
    for i, frame in enumerate(frames):
        src_rel = frame["file_path"]  # e.g. "images/frame_00001.jpg"
        src_basename = os.path.basename(src_rel)
        tag = "eval" if i in eval_indices else "train"
        new_basename = f"{tag}_{src_basename}"
        (eval_files if tag == "eval" else train_files).append(new_basename)

        link_path = images_out / new_basename
        real_src = (args.source / src_rel).resolve()
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(os.path.relpath(real_src, images_out))

        new_frame = dict(frame)
        new_frame["file_path"] = f"images/{new_basename}"
        new_frames.append(new_frame)

    data["frames"] = new_frames

    # symlink sparse_pc.ply too, so point-cloud init still works unchanged
    ply_name = data.get("ply_file_path")
    if ply_name:
        real_ply = (args.source / ply_name).resolve()
        link_ply = args.output / ply_name
        if link_ply.exists() or link_ply.is_symlink():
            link_ply.unlink()
        link_ply.symlink_to(os.path.relpath(real_ply, args.output))

    (args.output / "transforms.json").write_text(json.dumps(data, indent=2))

    print(f"seed={args.seed} total={n} train={len(train_files)} eval={len(eval_files)}")
    print(f"eval files: {sorted(eval_files)}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
