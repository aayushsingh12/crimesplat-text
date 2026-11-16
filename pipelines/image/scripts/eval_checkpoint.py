#!/usr/bin/env python3
"""
Drop-in replacement for `ns-eval`, needed because nerfstudio 1.1.5's
eval_load_checkpoint() calls torch.load() without accounting for PyTorch
2.6+'s change of the `weights_only` default from False to True. As shipped,
that makes `ns-eval` fail to unpickle our checkpoints (they contain numpy
globals like numpy.core.multiarray.scalar / numpy.dtype that aren't on
torch's default safe-unpickling allowlist) with:

    _pickle.UnpicklingError: Weights only load failed. ...

This wrapper forces weights_only=False for this process's torch.load calls
and then runs nerfstudio's real ns-eval entrypoint unmodified. No nerfstudio
site-packages files or environment.yml are touched.

    WARNING -- weights_only=False disables the exact safety check PyTorch
    added to guard against arbitrary code execution from a malicious pickle.
    Only ever use this on checkpoints YOU trained yourself on this machine.
    Never point it at a checkpoint you downloaded or received from someone
    else -- run plain `ns-eval` for those (and accept that it may fail on
    the same numpy-global issue) rather than bypassing the check.

Usage (same flags as ns-eval):
    python pipelines/image/scripts/eval_checkpoint.py \\
        --load-config outputs/<experiment>/splatfacto/<timestamp>/config.yml \\
        --output-path /tmp/eval.json
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

from nerfstudio.scripts.eval import entrypoint  # noqa: E402  (must follow the patch above)

if __name__ == "__main__":
    sys.exit(entrypoint())
