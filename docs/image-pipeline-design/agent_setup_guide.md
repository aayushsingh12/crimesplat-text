# Agent setup guide — crime-graph image pipeline

This document is written for an autonomous coding agent (LLM) setting up or
operating this repository, not for a human reader. It is deliberately
mechanical: exact commands, exact expected output, exact failure signatures
mapped to exact fixes, and explicit constraints on what not to do
autonomously. If you are a human, read `README.md` instead — it has the
narrative version of everything here.

If `quickstart.sh` exists at the repo root, prefer invoking it
(`./quickstart.sh setup`, `./quickstart.sh pipeline --photos-dir DIR`,
`./quickstart.sh web`, `./quickstart.sh demo`) over reproducing these steps
by hand. This document exists for the case where you need to debug a
failure inside one of those stages, run a step in isolation, or operate in
an environment where that script doesn't apply.

## 0. Hard constraints — do not violate these

- **Never run `sudo` without the user explicitly asking you to, in this
  session, for this specific command.** Two steps below (installing the
  COLMAP system package, writing a GPU runtime-PM udev rule) normally
  require it. Print the exact command and stop; do not execute it.
- **Never delete or overwrite `pipelines/image/data/`.** It holds real
  source photographs (gitignored, not reproducible from anything else in
  the repo). If it's missing, that's expected on a fresh clone — ask the
  user for a photo set rather than fabricating one.
- **Never treat a single COLMAP run's registration count as ground
  truth.** This build's structure-from-motion stage is not deterministic
  across clean reruns (confirmed: 8 independent runs on the reference
  scene ranged 66.67%–73.33% registered, even fully single-threaded). If
  you need to report a number, report the range or the specific run you
  measured, not "the" number.
- **Never present a text-query result as reliable without the
  caveat.** There is no similarity threshold. A query about something
  absent from the scene can score close to a query about something
  present (0.2592 vs. 0.3226 in the one documented comparison). If you
  write UI copy, logs, or a report describing a query result, the
  no-threshold caveat must be present, not summarized away.
- **Never point `weights_only=False` checkpoint-loading wrappers
  (`eval_checkpoint.py`, `export_checkpoint.py`, `render_checkpoint.py`,
  `run_viewer_patched.py`) at a checkpoint you did not train in this
  environment.** That flag disables PyTorch's unpickling safety check.
- **Do not `conda env remove` or recreate an existing env unless asked, or
  unless this guide's own `--force` path is what the user requested.**
  Training checkpoints and conda envs are expensive to rebuild; prefer
  additive, skip-if-exists operations.

## 1. What this repository is

A pipeline that turns crime-scene photographs into an interactive 3D
reconstruction with text-query region lookup:

```
photos --[EXIF fix]--> photos_corrected
       --[COLMAP SfM]--> sparse model + transforms.json
       --[Splatfacto / 3D Gaussian Splatting]--> trained checkpoint
       --[pruning]--> cleaned checkpoint
       --[SAM + CLIP]--> region_lookup.json (314 localized regions, reference scene)
       --[CLIP text query + cosine similarity]--> best-match region
       --[render / WebGL viewer]--> highlighted output
```

Two conda environments exist on purpose and must stay separate:

| env | purpose | hardware | key packages |
|---|---|---|---|
| `crime-image` | COLMAP-adjacent scripts, Splatfacto training, checkpoint load/export/render | GPU (CUDA) | `torch==2.11.0+cu128`, `torchvision==0.26.0+cu128`, `nerfstudio==1.1.5`, `gsplat==1.4.0` |
| `crime-image-tag` | SAM mask generation, CLIP embedding/query | CPU-only | `torch==2.13.0+cpu`, `torchvision==0.28.0+cpu`, `open_clip_torch==3.3.0`, `segment-anything==1.0`, `opencv-python-headless==5.0.0.93`, `Flask==3.1.3` |

Both are Python 3.10. Reason for the split: `open_clip_torch` requires
`timm>=1.0.17`; `crime-image`'s pinned `environment.yml` has
`timm==0.6.7` (a `nerfstudio` dependency). Installing CLIP into
`crime-image` would silently bump that pin. **Do not merge these
environments** even if it looks convenient.

The only data crossing the env boundary is JSON files
(`pipelines/image/query/region_lookup.json`, `last_match.json`) — neither
env imports code from the other's install.

## 2. Preflight checks (run these first, in order)

```bash
uname -s                          # expect: Linux
command -v colmap && colmap -h    # expect: a COLMAP version banner; CPU-only build is fine
command -v nvidia-smi && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
command -v conda || ls -d ~/miniforge3 ~/miniconda3 ~/anaconda3 2>/dev/null
```

Interpretation:
- `colmap` missing → system package, not conda-managed. Print
  `sudo apt install colmap` (Debian/Ubuntu) or the equivalent for the
  detected distro. **Do not run it.** Ask the user to run it, or wait for
  explicit authorization.
- `nvidia-smi` missing or reports 0 GPUs → Splatfacto training
  (`ns-train`) and gsplat's CUDA JIT compile will not work. The
  SAM+CLIP/`crime-image-tag` stages and the Streamlit mock demo
  (`pipelines/image/ui/`) still work with no GPU at all — fall back to
  those if asked to "demo this" without GPU access.
- VRAM reported under ~8GB → flag before training: this build's
  documented OOM boundary is 18 training images stable / 17 crashing on
  an 8GB card (sparse-view Gaussian densification runaway, not a leak;
  see `pipelines/image/docs/splatfacto_config.md`). More VRAM raises the
  boundary; it does not remove it.
- `conda` not found anywhere → stop and ask the user to install
  Miniforge/conda; do not attempt a silent install of a package manager.

## 3. Environment setup

### 3.1 `crime-image` (GPU env)

```bash
conda env list | grep -q '^crime-image '   # idempotency check -- skip create if this matches
conda env create -f pipelines/image/environment.yml
```

Success signal: command exits 0, `conda env list` now shows
`crime-image`. This step can take several minutes (large pip-based
dependency set, GPU torch wheel).

**Known failure modes and fixes:**

| stdout/stderr contains | cause | fix |
|---|---|---|
| `CondaValueError: prefix already exists` | env already created | this is not an error for your purposes — skip, don't `--force` recreate unless asked |
| pip resolution error on a `+cu128` wheel | no matching CUDA wheel index reachable, or wrong Python/platform | do not silently change the pin; report the exact pip error to the user, do not substitute a different torch version |

### 3.2 CUDA activate/deactivate hooks (required for gsplat, not captured by `environment.yml`)

gsplat JIT-compiles CUDA kernels via `nvcc` on first use. Without
`CUDA_HOME` set, it silently disables itself and training crashes on the
first forward pass with `AttributeError: 'NoneType' object has no
attribute 'CameraModelType'` — an error that looks unrelated to CUDA.
Without `MAX_JOBS` capped, the JIT build's default one-`nvcc`-per-core
parallelism gets OOM-killed on multi-core machines (`ninja: ... FAILED
[code=137]`).

Detect the toolkit, then write both hook files:

```bash
CONDA_BASE="$(conda info --base)"
ENV_DIR="$CONDA_BASE/envs/crime-image"
CUDA_HOME=""
for c in /usr/local/cuda-12.8 /usr/local/cuda; do
  [ -d "$c" ] && CUDA_HOME="$c" && break
done
# if CUDA_HOME is still empty, search more broadly before giving up:
#   ls -d /usr/local/cuda-* 2>/dev/null
```

If no CUDA toolkit directory is found anywhere, **do not invent a path**
— report this to the user; gsplat cannot JIT-compile without it.

If found, write (substituting the real `$ENV_DIR` and `$CUDA_HOME`):

`$ENV_DIR/etc/conda/activate.d/env_vars.sh`:
```sh
#!/bin/sh
export _CRIME_IMAGE_OLD_CUDA_HOME="${CUDA_HOME:-}"
export _CRIME_IMAGE_OLD_PATH="${PATH:-}"
export _CRIME_IMAGE_OLD_MAX_JOBS="${MAX_JOBS:-}"
export CUDA_HOME=/usr/local/cuda-12.8
export PATH="$CUDA_HOME/bin:$PATH"
export MAX_JOBS=4
```

`$ENV_DIR/etc/conda/deactivate.d/env_vars.sh`:
```sh
#!/bin/sh
if [ -n "$_CRIME_IMAGE_OLD_CUDA_HOME" ]; then export CUDA_HOME="$_CRIME_IMAGE_OLD_CUDA_HOME"; else unset CUDA_HOME; fi
export PATH="$_CRIME_IMAGE_OLD_PATH"
if [ -n "$_CRIME_IMAGE_OLD_MAX_JOBS" ]; then export MAX_JOBS="$_CRIME_IMAGE_OLD_MAX_JOBS"; else unset MAX_JOBS; fi
unset _CRIME_IMAGE_OLD_CUDA_HOME _CRIME_IMAGE_OLD_PATH _CRIME_IMAGE_OLD_MAX_JOBS
```

Then `chmod +x` both files. **Verify, don't assume**: open a fresh shell,
`conda activate crime-image`, run `echo $CUDA_HOME && which nvcc`, confirm
both are non-empty and point at the expected toolkit, before proceeding to
training.

This step is safe to automate (writes two small files inside the conda
env's own directory, no system-wide effect, fully reversible by deleting
the env) — unlike the udev step in §5, it does not need the sudo
exception.

### 3.3 `crime-image-tag` (CPU env)

```bash
conda env list | grep -q '^crime-image-tag '   # idempotency check
conda create -n crime-image-tag python=3.10 -y
conda run -n crime-image-tag --no-capture-output pip install \
  torch==2.13.0+cpu torchvision==0.28.0+cpu --index-url https://download.pytorch.org/whl/cpu
conda run -n crime-image-tag --no-capture-output pip install \
  open_clip_torch==3.3.0 segment-anything==1.0 opencv-python-headless==5.0.0.93 flask==3.1.3
```

Verify: `conda run -n crime-image-tag python -c "import torch, open_clip, segment_anything, cv2, flask; print('ok')"`
must print `ok` with no traceback. `ModuleNotFoundError: No module named
'cv2'` means the `opencv-python-headless` install step was skipped or
failed — SAM's automatic mask generator needs it; it's not optional.

### 3.4 SAM checkpoint

```bash
mkdir -p pipelines/image/models
curl -L --fail -o pipelines/image/models/sam_vit_b_01ec64.pth \
  https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth
```

Verify by size, not just exit code (truncated downloads can still exit 0
if the connection drops mid-stream after headers): expect **~375MB**
(`stat -c%s pipelines/image/models/sam_vit_b_01ec64.pth` should read
roughly `375000000`–`376000000`). If it's dramatically smaller, the
download failed partway — delete and retry, don't pass a truncated file
to `tag_regions.py`.

### 3.5 Things to print, not execute

```
echo 'SUBSYSTEM=="pci", KERNELS=="<PCI address>", ATTR{power/control}="on"' \
    | sudo tee /etc/udev/rules.d/81-nvidia-runtime-pm.rules
sudo udevadm control --reload-rules
```

Only relevant if training dies at startup with an `NVRM:` /
`NV_ERR_NO_MEMORY` message and no Python traceback (laptop GPU runtime
power management racing fresh CUDA context creation — see
`pipelines/image/README.md`'s "GPU runtime PM" section for the full
diagnosis). Find the real PCI address first (`lspci | grep -i nvidia`,
look for the matching `/sys/bus/pci/devices/<addr>/`); do not guess
`0000:01:00.0` from the example in the docs — that's this project's
reference machine's address, not a universal constant.

## 4. Running the pipeline

Parameters: `DATASET` (a name, default `galanakis2021`), `PHOTOS_DIR`
(default `pipelines/image/data/$DATASET/photos`).

**`EXP_NAME` naming rule** (important — avoids a real collision): if
`DATASET=galanakis2021`, use `EXP_NAME=colmap` (this matches every exact
path written in `pipelines/image/docs/*.md` — keep it literal so you can
cross-reference those docs' numbers against what you reproduce). For any
other dataset name, pass `--experiment-name "$DATASET"` to `ns-train`
explicitly — nerfstudio otherwise names every run after the literal
string `colmap` (the basename of `.../<dataset>/colmap`), which would
silently collide across datasets.

Each stage below: check the "skip if" condition first. If satisfied,
skip and move on — do not redo expensive work (COLMAP registration is
non-deterministic, so redoing it changes your dataset; Splatfacto
training takes 15–20 minutes).

| stage | command | skip if | verify |
|---|---|---|---|
| EXIF fix | `python pipelines/image/scripts/fix_exif_orientation.py "$PHOTOS_DIR" "$DATA_DIR/photos_corrected"` | `photos_corrected/` exists and is non-empty | file count matches `$PHOTOS_DIR` |
| COLMAP features+matching | `colmap feature_extractor --database_path "$COLMAP_DIR/database.db" --image_path "$DATA_DIR/photos_corrected" --ImageReader.single_camera 0 --SiftExtraction.use_gpu 0 --SiftExtraction.num_threads 4` then `colmap exhaustive_matcher --database_path "$COLMAP_DIR/database.db" --SiftMatching.use_gpu 0 --SiftMatching.num_threads 4` | `database.db` exists | exit 0 on both; log mentions `N` camera entries matching photo count |
| COLMAP mapper | `mkdir -p "$COLMAP_DIR/sparse" && colmap mapper --database_path "$COLMAP_DIR/database.db" --image_path "$DATA_DIR/photos_corrected" --output_path "$COLMAP_DIR/sparse" --Mapper.num_threads 1` | `sparse/0/` exists | `colmap model_analyzer --path "$COLMAP_DIR/sparse/0"` prints a registered-image count > 0 |
| convert to nerfstudio format | `ns-process-data images --data "$DATA_DIR/photos_corrected" --output-dir "$COLMAP_DIR" --skip-colmap --colmap-model-path sparse/0 --no-same-dimensions` | `transforms.json` exists | file has a non-empty `"frames"` list |
| Splatfacto training | `ns-train splatfacto --data "$COLMAP_DIR" --experiment-name "$EXP_NAME" --max-num-iterations 30000 --viewer.quit-on-train-completion True --pipeline.model.random-init False nerfstudio-data --load-3D-points True` | `outputs/$EXP_NAME/splatfacto/*/config.yml` exists | log ends with `🎉 Training Finished 🎉`; `nerfstudio_models/*.ckpt` exists; **absence** of the `load_3D_points set to true but no point cloud found` warning (its presence means the point cloud wasn't actually used) |
| cleanup/pruning | see §4.1 below | `outputs/${EXP_NAME}_pruned/splatfacto/<same-timestamp>/nerfstudio_models/*.ckpt` exists | pruning report shows a nonzero removed count; re-eval metrics (if run) move by less than their own per-image noise, not by an order of magnitude |
| SAM+CLIP tagging | `conda run -n crime-image-tag python pipelines/image/scripts/tag_regions.py --colmap-dir "$COLMAP_DIR" --dataparser-transforms "<pruned_dir>/dataparser_transforms.json" --out pipelines/image/query/region_lookup.json` | `region_lookup.json` exists | JSON parses; `len(records) > 0` |
| export for web | `conda run -n crime-image python pipelines/image/scripts/export_checkpoint.py gaussian-splat --load-config "<pruned_dir>/config.yml" --output-dir pipelines/image/ui_web/export --output-filename splat.ply` | `ui_web/export/splat.ply` exists | file size roughly tracks Gaussian count (reference: 454,084 Gaussians → 108MB) |
| camera poses | `conda run -n crime-image python pipelines/image/scripts/extract_camera_poses.py --colmap-dir "$COLMAP_DIR" --dataparser-transforms "<pruned_dir>/dataparser_transforms.json" --out pipelines/image/ui_web/camera_poses.json` | `camera_poses.json` exists | entry count matches the registered-image count from the mapper stage |

### 4.1 Pruning, in full (the threshold values are not constants to hardcode)

Read `cull_alpha_thresh`/`cull_scale_thresh` from the **trained run's own**
`config.yml` (defaults are 0.1/0.5, but verify rather than assume — a
future nerfstudio version could ship different defaults):

```bash
python3 - "$run_dir/config.yml" <<'PY'
import re
text = open("CONFIG_PATH_HERE").read()
a = re.search(r"cull_alpha_thresh:\s*([0-9.eE+-]+)", text)
s = re.search(r"cull_scale_thresh:\s*([0-9.eE+-]+)", text)
print(a.group(1) if a else "0.1", s.group(1) if s else "0.5")
PY
```

```bash
python pipelines/image/scripts/prune_checkpoint.py --report --load-checkpoint "$ckpt"
python pipelines/image/scripts/prune_checkpoint.py --prune \
  --load-checkpoint "$ckpt" \
  --opacity-thresh "$opacity_thresh" --scale-thresh "$scale_thresh" \
  --output "$pruned_ckpt"
mkdir -p "$(dirname "$pruned_ckpt")/.."
cp "$run_dir/config.yml" "$pruned_dir/config.yml"
cp "$run_dir/dataparser_transforms.json" "$pruned_dir/dataparser_transforms.json"
sed -i "s/^experiment_name: $EXP_NAME\$/experiment_name: ${EXP_NAME}_pruned/" "$pruned_dir/config.yml"
```

Every downstream step (tagging, export, camera poses, render) reads from
`$pruned_dir`, not `$run_dir` — the pruned checkpoint is the one actually
intended for use after this stage runs.

## 5. Error signature reference

Match on these exact substrings when triaging a failure; don't guess from
a generic stack trace.

| exact substring in output | root cause | fix |
|---|---|---|
| `gsplat: No CUDA toolkit found. gsplat will be disabled.` | `CUDA_HOME` not set in the active env | re-check §3.2; confirm `conda activate crime-image` actually set `CUDA_HOME` (`echo $CUDA_HOME`) |
| `AttributeError: 'NoneType' object has no attribute 'CameraModelType'` | same root cause as above, surfaces later/differently | same fix — don't debug this as a data/model issue |
| `ninja: ... FAILED` with exit code `137` | `nvcc` JIT compile OOM-killed by too much parallelism | confirm `MAX_JOBS` is set (§3.2); lower it further (e.g. `MAX_JOBS=2`) on a lower-RAM machine |
| `_pickle.UnpicklingError: Weights only load failed` | PyTorch 2.6+ `weights_only=True` default vs. this project's checkpoints | use `eval_checkpoint.py`/`export_checkpoint.py`/`render_checkpoint.py` instead of bare `ns-eval`/`ns-export`/`ns-render` — never add `weights_only=False` anywhere else without the same trust caveat from §0 |
| `NVRM: ... Check failed: Out of memory [NV_ERR_NO_MEMORY]`, no Python traceback, process just dies | GPU runtime PM race (§3.5) | print the udev fix, do not execute it without authorization |
| `torch.OutOfMemoryError` inside Splatfacto's SSIM loss, Gaussian count still climbing at crash (check the preceding log lines) | sparse-view adaptive-density-control runaway below the 18-training-image boundary on an 8GB card | do not "fix" by lowering batch size or disabling the loss term — the documented fix is more training images or more VRAM; report this rather than papering over it |
| `cameras, images, points3D files do not exist` from `colmap mapper` | `--output_path` directory wasn't created first | `mkdir -p` it; `colmap mapper` does not create its own output directory |
| `ModuleNotFoundError: No module named 'cv2'` | `opencv-python-headless` missing from `crime-image-tag` | §3.3, it's a required (not optional) SAM runtime dependency |
| `QuickGELU mismatch between final model config (quick_gelu=False) and pretrained tag 'openai' (quick_gelu=True)` | wrong CLIP model variant | use `ViT-B-32-quickgelu`, not plain `ViT-B-32`, with `pretrained="openai"` — this is already correct in the committed `tag_regions.py`/`query_regions.py`; only relevant if you're writing new CLIP-loading code |
| `curl: (22)` or similar on the SAM checkpoint download, or a file far short of ~375MB | network interruption mid-download | delete the partial file and retry; don't pass a truncated checkpoint to `tag_regions.py` (it will fail to load, not silently degrade) |
| `port ... already in use` from `run_demo.sh` | a previous demo instance is still listening on 8000 or 5001 | `lsof -i :8000` / `lsof -i :5001`, confirm what it is before killing it (don't blind-kill PIDs you haven't identified) |

## 6. Verifying the end state

After a full pipeline run, before telling the user it succeeded, check all
of:

```bash
test -s pipelines/image/query/region_lookup.json       # non-empty
test -s pipelines/image/ui_web/export/splat.ply         # non-empty
test -s pipelines/image/ui_web/camera_poses.json        # non-empty
python3 -c "import json; d=json.load(open('pipelines/image/query/region_lookup.json')); assert len(d['records'])>0"
```

Then do one real smoke test, not just a file-existence check — run an
actual query end to end and confirm it returns a non-crashing result:

```bash
conda run -n crime-image-tag python pipelines/image/scripts/query_regions.py \
  --lookup pipelines/image/query/region_lookup.json \
  --query "blood spatter" --out-match /tmp/smoke_match.json
python3 -c "import json; d=json.load(open('/tmp/smoke_match.json')); print(d)"
```

A result with a plausible `point3d_final` and a similarity score roughly
in the 0.25–0.35 range (this architecture's observed band on the
reference scene) is consistent with prior behavior. A similarity near 0
or 1, or a crash, means something upstream is broken — don't report
success on the basis of "the script exited 0" alone.
