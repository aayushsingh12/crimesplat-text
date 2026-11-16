#!/usr/bin/env python3
"""
Drop-in replacement for `ns-viewer`, same reason as eval_checkpoint.py /
render_checkpoint.py: nerfstudio 1.1.5's checkpoint loading calls
torch.load() without accounting for PyTorch 2.6+'s change of the
`weights_only` default from False to True. This wrapper forces
weights_only=False for this process's torch.load calls and then runs
nerfstudio's real ns-viewer entrypoint unmodified -- no marker injection,
no scene modification, just the stock viewer.

    WARNING -- weights_only=False disables the exact safety check PyTorch
    added to guard against arbitrary code execution from a malicious pickle.
    Only ever use this on checkpoints YOU trained yourself on this machine.

Usage (same flags as ns-viewer):
    python pipelines/image/scripts/run_viewer_patched.py \\
        --load-config outputs/<experiment>/splatfacto/<timestamp>/config.yml
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

from nerfstudio.scripts.viewer.run_viewer import entrypoint  # noqa: E402

if __name__ == "__main__":
    sys.exit(entrypoint())
