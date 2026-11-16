#!/usr/bin/env python3
"""
Task 5 -- post-training Gaussian pruning for a trained Splatfacto checkpoint.

Two modes:

  --report                Load a checkpoint, print the real opacity/scale
                           distributions (percentiles), and exit. No file
                           written. Run this FIRST to pick thresholds from
                           actual data, not guessed round numbers.

  --prune --output PATH   Load a checkpoint, drop Gaussians below
                           --opacity-thresh and/or above --scale-thresh,
                           and write a new checkpoint (same structure,
                           gauss_params replaced) to PATH.

Uses the same weights_only=False checkpoint-load workaround as
eval_checkpoint.py (nerfstudio checkpoints carry numpy globals that trip
PyTorch 2.6+'s default safe-unpickling allowlist) -- same warning applies:
only ever run this against checkpoints trained on this machine.

Splatfacto stores opacities/scales UNACTIVATED (checked directly against
nerfstudio 1.1.5's splatfacto.py, not assumed):
  - gauss_params["opacities"] are logits -- real opacity is sigmoid(x)
  - gauss_params["scales"] are log-scales -- real world-space scale is exp(x)
(confirmed at the call into gsplat's `rasterization()`, which is handed
`torch.sigmoid(opacities_crop)` and `torch.exp(scales_crop)` directly.)
All thresholds and reported percentiles in this script are in the
ACTIVATED (real opacity / real world-space scale) space, not raw logit/log
values, since that's the physically meaningful space to threshold in.

Usage:
    python pipelines/image/scripts/prune_checkpoint.py --report \\
        --load-checkpoint outputs/colmap/splatfacto/<ts>/nerfstudio_models/step-000029999.ckpt

    python pipelines/image/scripts/prune_checkpoint.py --prune \\
        --load-checkpoint outputs/colmap/splatfacto/<ts>/nerfstudio_models/step-000029999.ckpt \\
        --opacity-thresh 0.01 --scale-thresh 1.2 \\
        --output outputs/colmap_pruned/splatfacto/<ts>/nerfstudio_models/step-000029999.ckpt
"""
import argparse
import functools
from pathlib import Path

import torch

_orig_load = torch.load


@functools.wraps(_orig_load)
def _load_trusted(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_load(*args, **kwargs)


torch.load = _load_trusted


def _gauss_params(ckpt):
    """Locate the gauss_params sub-dict inside a Splatfacto checkpoint's pipeline state."""
    sd = ckpt["pipeline"]
    prefix = "_model.gauss_params."
    return {k[len(prefix):]: v for k, v in sd.items() if k.startswith(prefix)}, prefix


def _percentiles(x: torch.Tensor):
    qs = [0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9, 100]
    vals = torch.quantile(x.double(), torch.tensor(qs, dtype=torch.float64) / 100.0)
    return dict(zip(qs, vals.tolist()))


def report(load_checkpoint: Path):
    ckpt = torch.load(load_checkpoint, map_location="cpu")
    gp, _ = _gauss_params(ckpt)
    n = gp["opacities"].shape[0]
    print(f"Checkpoint: {load_checkpoint}")
    print(f"Step: {ckpt.get('step')}")
    print(f"Gaussian count: {n}")
    print()

    opacity = torch.sigmoid(gp["opacities"].squeeze(-1))
    scale = torch.exp(gp["scales"])  # [N, 3], per-axis world-space scale
    scale_max = scale.amax(dim=-1)  # largest axis per Gaussian
    scale_mean = scale.mean(dim=-1)

    print(f"opacities raw tensor shape: {tuple(gp['opacities'].shape)}")
    print(f"scales    raw tensor shape: {tuple(gp['scales'].shape)}")
    print()

    def _print_dist(name, x):
        p = _percentiles(x)
        print(f"{name} (n={x.shape[0]}):")
        print(f"  min={x.min().item():.6g}  max={x.max().item():.6g}  "
              f"mean={x.mean().item():.6g}  std={x.std().item():.6g}")
        row = "  ".join(f"p{q}={v:.6g}" for q, v in p.items())
        print(f"  {row}")
        print()

    _print_dist("opacity (sigmoid-activated, real [0,1])", opacity)
    _print_dist("scale_max (exp-activated, largest axis per Gaussian, world units)", scale_max)
    _print_dist("scale_mean (exp-activated, mean of 3 axes, world units)", scale_mean)

    # A few candidate threshold previews, purely informational -- how many
    # Gaussians would be affected at some round-number cut points, to help
    # pick a real threshold rather than assuming one.
    print("Candidate threshold previews (informational only):")
    for t in [0.001, 0.005, 0.01, 0.02, 0.05, 0.1]:
        frac = (opacity < t).float().mean().item()
        print(f"  opacity < {t:<6}: {frac*100:.3f}% of Gaussians ({int((opacity < t).sum())})")
    for t in [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]:
        frac = (scale_max > t).float().mean().item()
        print(f"  scale_max > {t:<6}: {frac*100:.3f}% of Gaussians ({int((scale_max > t).sum())})")


def prune(load_checkpoint: Path, output: Path, opacity_thresh, scale_thresh):
    ckpt = torch.load(load_checkpoint, map_location="cpu")
    gp, prefix = _gauss_params(ckpt)
    n_before = gp["opacities"].shape[0]

    opacity = torch.sigmoid(gp["opacities"].squeeze(-1))
    scale_max = torch.exp(gp["scales"]).amax(dim=-1)

    keep = torch.ones(n_before, dtype=torch.bool)
    if opacity_thresh is not None:
        keep &= opacity >= opacity_thresh
    if scale_thresh is not None:
        keep &= scale_max <= scale_thresh

    n_after = int(keep.sum())
    n_removed_opacity = int((opacity < opacity_thresh).sum()) if opacity_thresh is not None else 0
    n_removed_scale = int((scale_max > scale_thresh).sum()) if scale_thresh is not None else 0
    n_removed_both = int(((opacity < (opacity_thresh if opacity_thresh is not None else -1)) &
                           (scale_max > (scale_thresh if scale_thresh is not None else float("inf")))).sum())

    print(f"Before: {n_before} Gaussians")
    print(f"  would remove (opacity < {opacity_thresh}): {n_removed_opacity}")
    print(f"  would remove (scale_max > {scale_thresh}): {n_removed_scale}")
    print(f"  removed by both criteria (overlap): {n_removed_both}")
    print(f"After:  {n_after} Gaussians ({(n_before - n_after) / n_before * 100:.3f}% removed)")

    for key in list(gp.keys()):
        full_key = prefix + key
        ckpt["pipeline"][full_key] = gp[key][keep]

    # Optimizer state (per-param Adam moments) is keyed to the SAME
    # first-dim index as gauss_params and would silently desync if left as
    # is (wrong shapes on next load into a fresh model -- but this
    # checkpoint is being loaded for eval/inference only, never resumed for
    # further training, so the optimizer state is dropped rather than
    # index-filtered, and load_scheduler/step are left untouched).
    if "optimizers" in ckpt:
        del ckpt["optimizers"]

    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(ckpt, output)
    print(f"Wrote pruned checkpoint: {output}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--load-checkpoint", type=Path, required=True)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--opacity-thresh", type=float, default=None)
    ap.add_argument("--scale-thresh", type=float, default=None)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    if args.report:
        report(args.load_checkpoint)
    elif args.prune:
        if args.output is None:
            ap.error("--prune requires --output")
        if args.opacity_thresh is None and args.scale_thresh is None:
            ap.error("--prune requires at least one of --opacity-thresh / --scale-thresh")
        prune(args.load_checkpoint, args.output, args.opacity_thresh, args.scale_thresh)
    else:
        ap.error("specify --report or --prune")


if __name__ == "__main__":
    main()
