# Image pipeline (Phase 1) -- dev environment

3D Gaussian Splatting reconstruction pipeline (nerfstudio + gsplat + COLMAP)
for crime-scene photo sets. This doc covers the `crime-image` conda env setup
and the GPU-specific gotchas found while getting it working on an RTX 5060
Laptop GPU (Blackwell, sm_120).

## Setup

```
conda env create -f pipelines/image/environment.yml
conda activate crime-image
```

`environment.yml` was produced with `conda env export --no-builds` and had
its machine-local `prefix:` line stripped, so it's portable across machines.
Most of the stack (nerfstudio, gsplat, torch, etc.) comes in as pip
dependencies inside the file -- that's expected, not a mistake.

COLMAP itself is a system package (`/usr/bin/colmap`, not managed by this
conda env). Confirm it's present separately:

```
colmap -h
```

**Note:** on this machine COLMAP reports `(Commit Unknown on Unknown without
CUDA)` -- it's a CPU-only build. Feature extraction / matching / mapping will
be slower than a CUDA-accelerated COLMAP, but it works. If SfM on the real
photo sets turns out to be a bottleneck, building COLMAP with CUDA support is
the next lever to pull -- not needed for anything done so far.

GPU-accelerated SIFT (SiftGPU) is OpenGL-based, not CUDA-specific, so it's a
separate concern from the note above -- it fails under native Wayland/EGL,
but works if you force XWayland with `QT_QPA_PLATFORM=xcb`. The pinned
config still uses CPU SIFT (`--SiftExtraction.use_gpu 0` /
`--SiftMatching.use_gpu 0`) regardless -- GPU SIFT was tested directly and
didn't improve registration. See [`docs/colmap_config.md`](docs/colmap_config.md)
for the full pinned COLMAP command sequence used on the real `galanakis2021`
dataset, including that test and a registration-nondeterminism finding
(20-22/30, not a fixed number) worth knowing about before comparing
registration numbers across runs. [`docs/splatfacto_config.md`](docs/splatfacto_config.md)
has the pinned Splatfacto training config and results for the same dataset,
and [`docs/p1_decision.md`](docs/p1_decision.md) is the running decision log
for both.

## CUDA_HOME / MAX_JOBS -- required for gsplat on this GPU

gsplat JIT-compiles its CUDA rasterization kernels via `nvcc` the first time
they're used (`fully_fused_projection`, etc. -- needed to target this GPU's
Blackwell/sm_120 architecture). Two things about that:

1. **gsplat needs `CUDA_HOME` (and `nvcc` on `PATH`) to find a toolkit at
   all.** Without it, gsplat prints `gsplat: No CUDA toolkit found. gsplat
   will be disabled.` and training crashes on the very first forward pass
   with `AttributeError: 'NoneType' object has no attribute
   'CameraModelType'` -- a confusing error that has nothing to do with the
   data or the model. A CUDA 12.8 toolkit matching torch's cu128 build is
   already installed system-wide at `/usr/local/cuda-12.8`; it's just not on
   `PATH` by default.
2. **The JIT build defaults to one `nvcc` job per CPU core**, which on this
   machine (32 cores, ~23GB RAM) is enough parallel `nvcc` processes to get
   OOM-killed partway through the first compile (`ninja: ... FAILED
   [code=137]`). `MAX_JOBS` caps that parallelism.

Both are set automatically via conda activate hooks, so `conda activate
crime-image` is all you need:

```
~/miniforge3/envs/crime-image/etc/conda/activate.d/env_vars.sh
~/miniforge3/envs/crime-image/etc/conda/deactivate.d/env_vars.sh
```

**Important:** these hook scripts live inside the conda env's own directory,
*not* in this repo, and `environment.yml` does not capture them --
`conda env create -f environment.yml` will **not** recreate them. If you're
setting this env up fresh (new machine, or env deleted and recreated), you
need to add them by hand once, after `conda env create`:

`activate.d/env_vars.sh`:
```sh
#!/bin/sh
export _CRIME_IMAGE_OLD_CUDA_HOME="${CUDA_HOME:-}"
export _CRIME_IMAGE_OLD_PATH="${PATH:-}"
export _CRIME_IMAGE_OLD_MAX_JOBS="${MAX_JOBS:-}"
export CUDA_HOME=/usr/local/cuda-12.8
export PATH="$CUDA_HOME/bin:$PATH"
export MAX_JOBS=4
```

`deactivate.d/env_vars.sh`:
```sh
#!/bin/sh
if [ -n "$_CRIME_IMAGE_OLD_CUDA_HOME" ]; then export CUDA_HOME="$_CRIME_IMAGE_OLD_CUDA_HOME"; else unset CUDA_HOME; fi
export PATH="$_CRIME_IMAGE_OLD_PATH"
if [ -n "$_CRIME_IMAGE_OLD_MAX_JOBS" ]; then export MAX_JOBS="$_CRIME_IMAGE_OLD_MAX_JOBS"; else unset MAX_JOBS; fi
unset _CRIME_IMAGE_OLD_CUDA_HOME _CRIME_IMAGE_OLD_PATH _CRIME_IMAGE_OLD_MAX_JOBS
```

(`chmod +x` both, and adjust the `/usr/local/cuda-12.8` path if a different
machine has its toolkit installed somewhere else.)

This was verified from a genuinely fresh shell with zero manual exports --
`conda activate crime-image` alone was enough to set `CUDA_HOME`/`MAX_JOBS`
and put a working `nvcc` on `PATH`, and a full `ns-train` + checkpoint-reload
smoke test passed off the back of that.

## GPU runtime PM -- udev rule needed to avoid mid-startup CUDA failures

This laptop's dGPU ships with PCIe runtime power management (RTD3) enabled
by default (`power/control: auto` on its PCI device). That autosuspend/
resume cycle intermittently races a freshly-launching CUDA context: a
training process can die at startup with `NVRM: ... Check failed: Out of
memory [NV_ERR_NO_MEMORY]`, no Python traceback, and no Linux OOM-killer log
entry -- easy to mistake for something else entirely. Diagnosed (via
`dmesg`/`journalctl` timestamps lining up exactly with two separate silent
process deaths) in [`docs/splatfacto_config.md`](docs/splatfacto_config.md)'s
"Verification run" section; full finding in
[`docs/p1_decision.md`](docs/p1_decision.md)'s Task 4b closing entry.

**Fix**: pin `power/control` to `on` for the GPU's PCI device via a udev
rule, so it's applied automatically on every boot instead of needing a
manual `sudo` write each session.

The device's PCI address, `0000:01:00.0` (NVIDIA `[10de:2d59]`), is stable
on this machine -- confirmed identical across every boot in the journal
(6 boots, Aug 17-24), not just assumed. It sits on its own dedicated Intel
root port (`lspci -tv`), not a hot-plug bus (Thunderbolt/eGPU), which is why
that's expected to keep holding: fixed-topology PCIe endpoints on a laptop's
own motherboard don't renumber between boots, only a BIOS update touching
PCIe resource allocation could change it (not something to preemptively
chase).

There's already an `/etc/udev/rules.d/60-nvidia.rules` on this machine from
the driver package (contents not inspected -- machine-local, out of scope
to audit here). The rule below is deliberately numbered **after** it
(`81-`, udev applies rules in filename order) so it wins regardless of
whatever `60-nvidia.rules` sets `power/control` to.

`/etc/udev/rules.d/81-nvidia-runtime-pm.rules`:
```
SUBSYSTEM=="pci", KERNELS=="0000:01:00.0", ATTR{power/control}="on"
```

**Like the conda activate hooks above, this lives outside the repo** (system
udev config, not captured by `environment.yml` or git) -- a fresh machine
(or this one, if `/etc` state is ever lost) needs it applied by hand once:

```sh
echo 'SUBSYSTEM=="pci", KERNELS=="0000:01:00.0", ATTR{power/control}="on"' \
    | sudo tee /etc/udev/rules.d/81-nvidia-runtime-pm.rules
sudo udevadm control --reload-rules
```

Verify it actually works without waiting for a real reboot -- reset the
device to the pre-fix default, then re-trigger udev's device-add event and
confirm the *rule* (not leftover manual state) puts it back:

```sh
echo auto | sudo tee /sys/bus/pci/devices/0000:01:00.0/power/control
cat /sys/bus/pci/devices/0000:01:00.0/power/control   # -> auto
sudo udevadm trigger --action=add --subsystem-match=pci /sys/bus/pci/devices/0000:01:00.0
cat /sys/bus/pci/devices/0000:01:00.0/power/control   # -> on, from the rule this time
```

This confirms the rule itself fires correctly; it doesn't perfectly
replicate cold-boot device enumeration timing, so if `power/control` ever
comes back as `auto` after an actual reboot, that's still worth rechecking
by hand rather than assumed fixed forever.

## `ns-eval` / checkpoint loading: `weights_only` gotcha

`ns-eval` as shipped in nerfstudio 1.1.5 calls `torch.load()` without
accounting for PyTorch 2.6+'s change of the `weights_only` default from
`False` to `True`. Against our checkpoints (which carry a couple of numpy
globals like `numpy.core.multiarray.scalar` / `numpy.dtype` that aren't on
torch's default safe-unpickling allowlist) that makes plain `ns-eval` fail
with `_pickle.UnpicklingError: Weights only load failed. ...`. This has
nothing to do with the GPU or the model -- it's a torch/nerfstudio version
gap.

Use `pipelines/image/scripts/eval_checkpoint.py` instead of `ns-eval`
directly -- same CLI flags, it just forces `weights_only=False` for this
process's `torch.load` calls before handing off to nerfstudio's real eval
entrypoint:

```
python pipelines/image/scripts/eval_checkpoint.py \
    --load-config outputs/<experiment>/splatfacto/<timestamp>/config.yml \
    --output-path /tmp/eval.json
```

**`weights_only=False` disables the exact safety check PyTorch added to
guard against arbitrary code execution from a malicious pickle. Only ever
run this against checkpoints you trained yourself on this machine.** Never
point it at a checkpoint you downloaded or received from someone else --
use plain `ns-eval` for those (and accept it may hit the same
`UnpicklingError`) rather than bypassing the check.

## Smoke-testing training + checkpoint save/load

Before running the real pipeline on forensic photos, it's worth confirming
training and checkpoint round-trip work end to end on whatever GPU you're
on -- e.g. the RTX 5060 Laptop GPU (Blackwell) had a known failure mode
where training could succeed but checkpoint loading breaks. Any tiny
dataset in standard nerfstudio format (`transforms.json` + `images/`) works
for this; content doesn't matter. From the repo root:

```
ns-train splatfacto --data data/<tiny-scene> --max-num-iterations 50 --viewer.quit-on-train-completion True
find outputs -name "*.ckpt"
python pipelines/image/scripts/eval_checkpoint.py \
    --load-config outputs/<experiment>/splatfacto/<timestamp>/config.yml \
    --output-path /tmp/eval.json
```

A successful run ends with `🎉 Training Finished 🎉` and a `.ckpt` under
`outputs/`; a successful eval prints `✅ Done loading checkpoint`.

Note the path convention: ad-hoc/smoke-test data and training output live
under `data/` and `outputs/` at the repo root (not tracked by git). The real
forensic photo sets live under `pipelines/image/data/`, which is gitignored.
