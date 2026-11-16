#!/usr/bin/env python3
"""
Drop-in replacement for `ns-export`, same reason as eval_checkpoint.py /
render_checkpoint.py / run_viewer_patched.py: nerfstudio 1.1.5's
checkpoint loading calls torch.load() without accounting for PyTorch
2.6+'s change of the `weights_only` default from False to True. This
wrapper forces weights_only=False for this process's torch.load calls
and then runs nerfstudio's real ns-export entrypoint unmodified.

    WARNING -- weights_only=False disables the exact safety check PyTorch
    added to guard against arbitrary code execution from a malicious pickle.
    Only ever use this on checkpoints YOU trained yourself on this machine.

Usage (same flags/subcommands as ns-export):
    python pipelines/image/scripts/export_checkpoint.py gaussian-splat \\
        --load-config outputs/<experiment>/splatfacto/<timestamp>/config.yml \\
        --output-dir pipelines/image/ui_web/export --output-filename splat.ply
"""
import functools
import sys

import torch

_orig_load = torch.load


@functools.wraps(_orig_load)
def _load_trusted(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_load(*args, **kwargs)


torch.load = _load_trusted

from nerfstudio.scripts.exporter import entrypoint  # noqa: E402

if __name__ == "__main__":
    sys.exit(entrypoint())
