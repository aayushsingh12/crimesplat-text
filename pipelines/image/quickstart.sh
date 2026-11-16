#!/usr/bin/env bash
# One entry point for this repo: environment setup, the full photo -> 3D
# Gaussian Splat -> language-queryable-region pipeline, and both demo UIs.
#
# Usage:
#   ./quickstart.sh demo                      # fastest path: Streamlit mock demo, no GPU/COLMAP/conda needed
#   ./quickstart.sh setup                     # create conda envs, fetch SAM checkpoint, write CUDA hooks
#   ./quickstart.sh pipeline --photos-dir DIR [--dataset NAME]   # run the real pipeline on your own photos
#   ./quickstart.sh web                       # launch the real WebGL viewer + query API (needs pipeline output)
#   ./quickstart.sh all --photos-dir DIR      # setup + pipeline + web, end to end
#
# Every stage is skip-if-already-done (checks its own output first) so this
# is safe to re-run after an interruption. Pass --force to redo a stage
# anyway. Nothing here runs `sudo` -- system-level steps (COLMAP package
# install, the GPU runtime-PM udev rule) are printed as instructions, not
# executed, same policy this project has followed everywhere else.
#
# See README.md for what each stage actually does and why; this script is
# the "just run it" version of the commands pinned in pipelines/image/docs/.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

IMG="$REPO_ROOT/pipelines/image"
SCRIPTS="$IMG/scripts"

DATASET="galanakis2021"
PHOTOS_DIR=""
FORCE=0

log() { echo "[quickstart] $*"; }
die() { echo "[quickstart] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

case "${1:-}" in
  -h|--help)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
esac

MODE="${1:-demo}"
[ $# -gt 0 ] && shift || true

while [ $# -gt 0 ]; do
  case "$1" in
    --dataset) DATASET="$2"; shift 2 ;;
    --photos-dir) PHOTOS_DIR="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

DATA_DIR="$IMG/data/$DATASET"
[ -z "$PHOTOS_DIR" ] && PHOTOS_DIR="$DATA_DIR/photos"
PHOTOS_CORR="$DATA_DIR/photos_corrected"
COLMAP_DIR="$DATA_DIR/colmap"
# nerfstudio names a run after --experiment-name (we pass it explicitly so
# two different --dataset values never collide in outputs/). The reference
# scene (galanakis2021) keeps the literal "colmap" name to match the exact
# paths every doc under pipelines/image/docs/ was written against.
if [ "$DATASET" = "galanakis2021" ]; then
  EXP_NAME="colmap"
else
  EXP_NAME="$DATASET"
fi
PRUNED_EXP_NAME="${EXP_NAME}_pruned"

conda_base() {
  if command -v conda >/dev/null 2>&1; then
    conda info --base
    return
  fi
  for d in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3"; do
    [ -x "$d/bin/conda" ] && { echo "$d"; return; }
  done
  return 1
}

run_in_env() {
  # run_in_env <conda-env-name> <command...>
  local env="$1"; shift
  local base; base="$(conda_base)" || die "conda not found -- run './quickstart.sh setup' first"
  # shellcheck disable=SC1091
  source "$base/etc/profile.d/conda.sh"
  conda run -n "$env" --no-capture-output "$@"
}

# ---------------------------------------------------------------------------
# setup: conda envs, SAM checkpoint, CUDA activate hooks, udev reminder
# ---------------------------------------------------------------------------

setup_preflight() {
  log "preflight checks..."
  if command -v colmap >/dev/null 2>&1; then
    log "  colmap: $(colmap -h 2>&1 | head -1)"
  else
    log "  WARNING: colmap not found on PATH. Install it (system package, not"
    log "  managed by conda), e.g.: sudo apt install colmap"
    log "  (Only needed for './quickstart.sh pipeline' / 'all', not for 'demo'.)"
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | while read -r line; do
      log "  gpu: $line"
    done
  else
    log "  WARNING: no nvidia-smi found. Splatfacto training needs an NVIDIA GPU"
    log "  (8GB+ VRAM recommended -- see README.md's 'Hardware' section for the"
    log "  documented OOM boundary on an 8GB card)."
  fi
}

setup_crime_image_env() {
  local base; base="$(conda_base)" || die "conda/miniforge not found. Install Miniforge first: https://github.com/conda-forge/miniforge"
  # shellcheck disable=SC1091
  source "$base/etc/profile.d/conda.sh"

  if conda env list | grep -q '^crime-image '; then
    log "crime-image env already exists, skipping create (pass --force to recreate)"
    [ "$FORCE" -eq 1 ] && { conda env remove -n crime-image -y; conda env create -f "$IMG/environment.yml"; }
  else
    log "creating crime-image env from environment.yml (GPU: torch/nerfstudio/gsplat)..."
    conda env create -f "$IMG/environment.yml"
  fi

  local env_dir="$base/envs/crime-image"
  local cuda_home=""
  for c in /usr/local/cuda-12.8 /usr/local/cuda; do
    [ -d "$c" ] && { cuda_home="$c"; break; }
  done
  if [ -z "$cuda_home" ]; then
    log "  WARNING: no CUDA toolkit found at /usr/local/cuda-12.8 or /usr/local/cuda."
    log "  gsplat JIT-compiles CUDA kernels and needs CUDA_HOME + nvcc on PATH --"
    log "  edit $env_dir/etc/conda/activate.d/env_vars.sh by hand once you know"
    log "  where your toolkit lives. See README.md's CUDA_HOME section."
  else
    log "  found CUDA toolkit at $cuda_home -- writing conda activate/deactivate hooks"
    mkdir -p "$env_dir/etc/conda/activate.d" "$env_dir/etc/conda/deactivate.d"
    cat > "$env_dir/etc/conda/activate.d/env_vars.sh" <<EOF
#!/bin/sh
export _CRIME_IMAGE_OLD_CUDA_HOME="\${CUDA_HOME:-}"
export _CRIME_IMAGE_OLD_PATH="\${PATH:-}"
export _CRIME_IMAGE_OLD_MAX_JOBS="\${MAX_JOBS:-}"
export CUDA_HOME=$cuda_home
export PATH="\$CUDA_HOME/bin:\$PATH"
export MAX_JOBS=4
EOF
    cat > "$env_dir/etc/conda/deactivate.d/env_vars.sh" <<'EOF'
#!/bin/sh
if [ -n "$_CRIME_IMAGE_OLD_CUDA_HOME" ]; then export CUDA_HOME="$_CRIME_IMAGE_OLD_CUDA_HOME"; else unset CUDA_HOME; fi
export PATH="$_CRIME_IMAGE_OLD_PATH"
if [ -n "$_CRIME_IMAGE_OLD_MAX_JOBS" ]; then export MAX_JOBS="$_CRIME_IMAGE_OLD_MAX_JOBS"; else unset MAX_JOBS; fi
unset _CRIME_IMAGE_OLD_CUDA_HOME _CRIME_IMAGE_OLD_PATH _CRIME_IMAGE_OLD_MAX_JOBS
EOF
    chmod +x "$env_dir/etc/conda/activate.d/env_vars.sh" "$env_dir/etc/conda/deactivate.d/env_vars.sh"
  fi
}

setup_crime_image_tag_env() {
  local base; base="$(conda_base)" || die "conda not found"
  # shellcheck disable=SC1091
  source "$base/etc/profile.d/conda.sh"

  if conda env list | grep -q '^crime-image-tag '; then
    log "crime-image-tag env already exists, skipping (pass --force to recreate)"
    [ "$FORCE" -eq 0 ] && return
    conda env remove -n crime-image-tag -y
  fi
  log "creating crime-image-tag env (CPU-only: SAM + CLIP, kept separate from"
  log "crime-image on purpose -- see pipelines/image/docs/phase2_decision.md)..."
  conda create -n crime-image-tag python=3.10 -y
  conda run -n crime-image-tag --no-capture-output pip install \
    torch==2.13.0+cpu torchvision==0.28.0+cpu --index-url https://download.pytorch.org/whl/cpu
  conda run -n crime-image-tag --no-capture-output pip install \
    open_clip_torch==3.3.0 segment-anything==1.0 opencv-python-headless==5.0.0.93 flask==3.1.3
}

fetch_sam_checkpoint() {
  local dest="$IMG/models/sam_vit_b_01ec64.pth"
  if [ -f "$dest" ] && [ "$FORCE" -eq 0 ]; then
    log "SAM checkpoint already present at $dest, skipping"
    return
  fi
  mkdir -p "$IMG/models"
  log "downloading SAM ViT-B checkpoint (~358MB) from Meta's public bucket..."
  curl -L --fail -o "$dest" https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth \
    || die "SAM checkpoint download failed"
}

print_udev_reminder() {
  cat <<'EOF'
[quickstart] NOT applied automatically (needs sudo, edits /etc) -- if training
dies at startup with an NVRM/NV_ERR_NO_MEMORY error and no Python traceback,
your GPU's runtime power management is probably racing CUDA context creation.
Find your dGPU's PCI address (lspci | grep -i nvidia), then:

    echo 'SUBSYSTEM=="pci", KERNELS=="<PCI address>", ATTR{power/control}="on"' \
        | sudo tee /etc/udev/rules.d/81-nvidia-runtime-pm.rules
    sudo udevadm control --reload-rules

See README.md's "GPU runtime PM" section for the full diagnosis.
EOF
}

cmd_setup() {
  setup_preflight
  setup_crime_image_env
  setup_crime_image_tag_env
  fetch_sam_checkpoint
  print_udev_reminder
  log "setup done. Next: './quickstart.sh pipeline --photos-dir <your photos>'"
}

# ---------------------------------------------------------------------------
# pipeline: EXIF fix -> COLMAP -> Splatfacto -> cleanup -> SAM+CLIP tagging
# ---------------------------------------------------------------------------

cmd_pipeline() {
  [ -d "$PHOTOS_DIR" ] || die "no photos at $PHOTOS_DIR (pass --photos-dir, or put images at pipelines/image/data/$DATASET/photos/)"
  mkdir -p "$COLMAP_DIR"

  if [ -d "$PHOTOS_CORR" ] && [ "$FORCE" -eq 0 ]; then
    log "[1/7] photos_corrected/ exists, skipping EXIF fix"
  else
    log "[1/7] EXIF-aware orientation correction..."
    run_in_env crime-image python "$SCRIPTS/fix_exif_orientation.py" "$PHOTOS_DIR" "$PHOTOS_CORR"
  fi

  if [ -f "$COLMAP_DIR/database.db" ] && [ "$FORCE" -eq 0 ]; then
    log "[2/7] database.db exists, skipping feature extraction/matching"
    log "       (registration is NOT deterministic across reruns -- see"
    log "       pipelines/image/docs/colmap_config.md -- pass --force for a clean rebuild)"
  else
    log "[2/7] COLMAP feature extraction + exhaustive matching (CPU SIFT)..."
    colmap feature_extractor \
      --database_path "$COLMAP_DIR/database.db" \
      --image_path "$PHOTOS_CORR" \
      --ImageReader.single_camera 0 \
      --SiftExtraction.use_gpu 0 \
      --SiftExtraction.num_threads 4
    colmap exhaustive_matcher \
      --database_path "$COLMAP_DIR/database.db" \
      --SiftMatching.use_gpu 0 \
      --SiftMatching.num_threads 4
  fi

  if [ -d "$COLMAP_DIR/sparse/0" ] && [ "$FORCE" -eq 0 ]; then
    log "[3/7] sparse/0 exists, skipping mapper"
  else
    log "[3/7] COLMAP sparse reconstruction (mapper)..."
    mkdir -p "$COLMAP_DIR/sparse"
    colmap mapper \
      --database_path "$COLMAP_DIR/database.db" \
      --image_path "$PHOTOS_CORR" \
      --output_path "$COLMAP_DIR/sparse" \
      --Mapper.num_threads 1
    colmap model_analyzer --path "$COLMAP_DIR/sparse/0" || true
  fi

  if [ -f "$COLMAP_DIR/transforms.json" ] && [ "$FORCE" -eq 0 ]; then
    log "[4/7] transforms.json exists, skipping ns-process-data"
  else
    log "[4/7] converting to nerfstudio transforms.json..."
    run_in_env crime-image ns-process-data images \
      --data "$PHOTOS_CORR" \
      --output-dir "$COLMAP_DIR" \
      --skip-colmap \
      --colmap-model-path sparse/0 \
      --no-same-dimensions
  fi

  local existing_run; existing_run="$(ls -td "$REPO_ROOT/outputs/$EXP_NAME/splatfacto"/*/ 2>/dev/null | head -1 || true)"
  if [ -n "$existing_run" ] && [ "$FORCE" -eq 0 ]; then
    log "[5/7] found existing training run at $existing_run, skipping ns-train"
  else
    log "[5/7] Splatfacto training (30,000 iterations, ~15-20 min on the"
    log "       documented RTX 5060 Laptop GPU -- see README.md 'Hardware')..."
    ( cd "$REPO_ROOT" && run_in_env crime-image ns-train splatfacto \
        --data "$COLMAP_DIR" \
        --experiment-name "$EXP_NAME" \
        --max-num-iterations 30000 \
        --viewer.quit-on-train-completion True \
        --pipeline.model.random-init False \
        nerfstudio-data --load-3D-points True )
  fi

  local run_dir; run_dir="$(cd "$REPO_ROOT" && ls -td outputs/"$EXP_NAME"/splatfacto/*/ 2>/dev/null | head -1)"
  [ -n "$run_dir" ] || die "no training run found under outputs/$EXP_NAME/splatfacto/ -- did ns-train fail?"
  run_dir="${run_dir%/}"
  local ckpt; ckpt="$(cd "$REPO_ROOT" && ls -t "$run_dir"/nerfstudio_models/*.ckpt 2>/dev/null | head -1)"
  [ -n "$ckpt" ] || die "no checkpoint found in $run_dir/nerfstudio_models/"

  local pruned_dir="outputs/$PRUNED_EXP_NAME/splatfacto/$(basename "$run_dir")"
  local pruned_ckpt="$pruned_dir/nerfstudio_models/$(basename "$ckpt")"
  if [ -f "$REPO_ROOT/$pruned_ckpt" ] && [ "$FORCE" -eq 0 ]; then
    log "[6/7] pruned checkpoint exists, skipping cleanup pass"
  else
    log "[6/7] post-training Gaussian cleanup (pruning using this checkpoint's"
    log "       own cull_alpha_thresh/cull_scale_thresh)..."
    local thresh; thresh="$(cd "$REPO_ROOT" && python3 - "$run_dir/config.yml" <<'PY'
import sys, re
text = open(sys.argv[1]).read()
a = re.search(r"cull_alpha_thresh:\s*([0-9.eE+-]+)", text)
s = re.search(r"cull_scale_thresh:\s*([0-9.eE+-]+)", text)
print(a.group(1) if a else "0.1", s.group(1) if s else "0.5")
PY
)"
    local opacity_thresh scale_thresh
    read -r opacity_thresh scale_thresh <<< "$thresh"
    mkdir -p "$REPO_ROOT/$pruned_dir/nerfstudio_models"
    run_in_env crime-image python "$SCRIPTS/prune_checkpoint.py" --report --load-checkpoint "$REPO_ROOT/$ckpt"
    run_in_env crime-image python "$SCRIPTS/prune_checkpoint.py" --prune \
      --load-checkpoint "$REPO_ROOT/$ckpt" \
      --opacity-thresh "$opacity_thresh" --scale-thresh "$scale_thresh" \
      --output "$REPO_ROOT/$pruned_ckpt"
    cp "$REPO_ROOT/$run_dir/config.yml" "$REPO_ROOT/$pruned_dir/config.yml"
    cp "$REPO_ROOT/$run_dir/dataparser_transforms.json" "$REPO_ROOT/$pruned_dir/dataparser_transforms.json"
    sed -i "s/^experiment_name: $EXP_NAME\$/experiment_name: $PRUNED_EXP_NAME/" "$REPO_ROOT/$pruned_dir/config.yml"
  fi

  local lookup="$IMG/query/region_lookup.json"
  if [ -f "$lookup" ] && [ "$FORCE" -eq 0 ]; then
    log "[7/7] region_lookup.json exists, skipping SAM+CLIP tagging"
  elif ! conda env list 2>/dev/null | grep -q '^crime-image-tag '; then
    log "[7/7] SKIPPED: crime-image-tag env not found -- run './quickstart.sh setup' first"
    log "       to enable SAM+CLIP region tagging (needed for the text-query demo)."
  elif [ ! -f "$IMG/models/sam_vit_b_01ec64.pth" ]; then
    log "[7/7] SKIPPED: SAM checkpoint not found -- run './quickstart.sh setup' first."
  else
    log "[7/7] SAM+CLIP region tagging + 3D localization (CPU, ~4 min/20 images)..."
    mkdir -p "$IMG/query"
    run_in_env crime-image-tag python "$SCRIPTS/tag_regions.py" \
      --colmap-dir "$COLMAP_DIR" \
      --dataparser-transforms "$REPO_ROOT/$pruned_dir/dataparser_transforms.json" \
      --out "$lookup"
  fi

  log "pipeline done."
  log "Next: './quickstart.sh web' to export + launch the real WebGL viewer,"
  log "or './quickstart.sh demo' for the lightweight pre-baked Streamlit demo."
}

# ---------------------------------------------------------------------------
# web: export checkpoint + camera poses, then launch the real WebGL viewer
# ---------------------------------------------------------------------------

cmd_web() {
  local run_dir; run_dir="$(ls -td outputs/"$PRUNED_EXP_NAME"/splatfacto/*/ 2>/dev/null | head -1)"
  [ -n "$run_dir" ] || die "no pruned checkpoint found -- run './quickstart.sh pipeline' first"
  run_dir="${run_dir%/}"

  if [ -f "$IMG/ui_web/export/splat.ply" ] && [ "$FORCE" -eq 0 ]; then
    log "export/splat.ply exists, skipping export"
  else
    log "exporting checkpoint to a static 3DGS .ply for the browser viewer..."
    run_in_env crime-image python "$SCRIPTS/export_checkpoint.py" gaussian-splat \
      --load-config "$run_dir/config.yml" \
      --output-dir "$IMG/ui_web/export" --output-filename splat.ply
  fi

  if [ -f "$IMG/ui_web/camera_poses.json" ] && [ "$FORCE" -eq 0 ]; then
    log "camera_poses.json exists, skipping"
  else
    log "extracting the registered COLMAP camera poses for the preset-viewpoint UI..."
    run_in_env crime-image python "$SCRIPTS/extract_camera_poses.py" \
      --colmap-dir "$COLMAP_DIR" \
      --dataparser-transforms "$run_dir/dataparser_transforms.json" \
      --out "$IMG/ui_web/camera_poses.json"
  fi

  log "launching web demo (static viewer + query API)..."
  exec "$IMG/ui_web/run_demo.sh"
}

# ---------------------------------------------------------------------------
# demo: zero-dependency Streamlit mock (pre-baked results, no GPU/COLMAP)
# ---------------------------------------------------------------------------

cmd_demo() {
  log "launching the Streamlit mock demo (two pre-baked, verified query"
  log "results -- no GPU, COLMAP, or conda env needed; see pipelines/image/ui/README.md)"
  exec "$REPO_ROOT/run_demo"
}

case "$MODE" in
  setup) cmd_setup ;;
  pipeline) cmd_pipeline ;;
  web) cmd_web ;;
  demo) cmd_demo ;;
  all) cmd_setup && cmd_pipeline && cmd_web ;;
  *) die "unknown mode '$MODE' (expected: setup | pipeline | web | demo | all)" ;;
esac
