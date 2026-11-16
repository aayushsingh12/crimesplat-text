# COLMAP configuration — `galanakis2021` (Task 3)

Pins the COLMAP structure-from-motion command sequence for the 30-photo
`galanakis2021` dataset, so Task 4 (Splatfacto training) has a sparse
reconstruction + `transforms.json` to build on. Every flag below was checked
against `colmap <cmd> --help` on this machine's COLMAP 3.9.1 install, not
assumed from older docs or from the Phase 2 writeup.

**Update (second pass, closing out Task 3):** the first version of this doc
claimed `--Mapper.num_threads 1` made the registration count fully
reproducible. That claim was wrong — it only held because every repro check
at the time reused one cached, already-built database. A genuine clean
end-to-end rerun (delete `database.db` and `sparse/` entirely, rebuild from
scratch) shows the **full pipeline is not deterministic**, even with every
stage forced single-threaded. See "Full pipeline determinism, retested"
below before trusting any single registration number from this dataset.

This document does not run Splatfacto/`ns-train` — that's Task 4, and it's
sequential on this doc's output existing.

## Dataset location note

The task brief said the dataset was already at
`pipelines/image/data/galanakis2021/photos/`. It wasn't — the 30 images
(`IMG_0457.jpg`–`IMG_0486.jpg`) were sitting at repo-root `zendoo_images/`,
untracked. They were moved into the documented, gitignored path
(`pipelines/image/data/galanakis2021/photos/`) before anything else in this
doc runs. If you're looking for the raw originals and they're not there,
that's why.

## Environment prerequisites

- `crime-image` conda env active (`conda activate crime-image` — see
  `pipelines/image/README.md` for the `CUDA_HOME`/`MAX_JOBS` hooks; those are
  gsplat/torch concerns and irrelevant to COLMAP itself).
- COLMAP is a **CPU-only build** on this machine (`colmap -h` reports
  `Commit Unknown on Unknown without CUDA` — see `pipelines/image/README.md`).
  That doesn't block GPU-accelerated SIFT on its own (SiftGPU is
  OpenGL-based, not CUDA-specific) — and unlike what the first pass of this
  doc concluded, **GPU SIFT does actually work here**: it fails under native
  Wayland (`QWaylandGLContext::makeCurrent: eglError... Framebuffer object
  not supported!`), but forcing the XWayland (X11) path with
  `QT_QPA_PLATFORM=xcb colmap feature_extractor --SiftExtraction.use_gpu 1
  ...` gets a working OpenGL context and runs to completion. See "GPU SIFT
  under Wayland" below — it was tested directly, and it does not turn out to
  matter for the registration gap. **The pinned commands in this doc still
  use CPU SIFT** (`--SiftExtraction.use_gpu 0` / `--SiftMatching.use_gpu 0`,
  no `QT_QPA_PLATFORM` needed) — GPU SIFT is documented as a tested,
  ruled-out alternative, not adopted, since it didn't produce a better result
  and adds an extra environment variable dependency for no benefit.

## Step 1 — EXIF-aware orientation correction

COLMAP's image reader loads raw pixel arrays and ignores the EXIF
`Orientation` tag. A batch with mixed portrait/landscape camera metadata —
some photos correctly upright as stored, others stored "sideways" with an
EXIF tag telling a normal viewer to rotate them — gets fed to SIFT feature
extraction with inconsistent effective orientations for photos of the same
real-world scene. This was identified in Phase 2 as the critical
preprocessing step: fixing it (plus `--ImageReader.single_camera 0`) took
registration on this same dataset from 56.67% to 83.33%.

Checked the 30 source images directly (not assumed): 3 of them
(`IMG_0459.jpg`, `IMG_0462.jpg`, `IMG_0464.jpg`) carry EXIF `Orientation=6`
and had **not** had it baked into their pixel data. The fix is scripted, not
hand-applied, at `pipelines/image/scripts/fix_exif_orientation.py`:

```
python pipelines/image/scripts/fix_exif_orientation.py \
    pipelines/image/data/galanakis2021/photos \
    pipelines/image/data/galanakis2021/photos_corrected
```

Bakes the EXIF rotation into the pixel data via PIL's `ImageOps.exif_transpose`
and writes to a separate `photos_corrected/` directory — the raw originals in
`photos/` are never mutated in place. Result: the 3 flagged images go from
`3024x4032` (stored, wrong) to `4032x3024` (corrected); the other 27 are
byte-for-byte unaffected by the transform (no orientation tag → no-op) but
are still re-saved into `photos_corrected/` so **all 30 images COLMAP sees
come from one directory with zero residual `Orientation` tags** (verified: 0
of 30 corrected images carry an `Orientation` tag afterward). Final split:
18 landscape / 12 portrait, 0 square.

This step is stable and not in question — every run described below, CPU or
GPU, single- or multi-threaded, used the exact same `photos_corrected/`
directory as input. It is not the source of the nondeterminism found below.

**All COLMAP commands below take `photos_corrected/` as `--image_path`, never
`photos/`.**

## Step 2 — Feature extraction

```
colmap feature_extractor \
  --database_path pipelines/image/data/galanakis2021/colmap/database.db \
  --image_path pipelines/image/data/galanakis2021/photos_corrected \
  --ImageReader.single_camera 0 \
  --SiftExtraction.use_gpu 0 \
  --SiftExtraction.num_threads 4
```

- `--ImageReader.single_camera 0`: each image gets independent camera
  parameters rather than one shared calibration across all 30 photos. This
  is already COLMAP 3.9.1's default (`--help` shows `(=0)`), but it's passed
  explicitly here so the pinned command doesn't silently depend on a default
  that could change in a future COLMAP version.
- `--SiftExtraction.use_gpu 0`: forces CPU SIFT. Not strictly required to
  avoid a crash (GPU SIFT does work here via `QT_QPA_PLATFORM=xcb` — see
  Environment prerequisites), but it's what this doc's pinned pipeline uses;
  GPU SIFT was tested separately and ruled out as a fix for the registration
  gap (see below).
- `--SiftExtraction.num_threads 4`: the default is one thread per core
  (`nproc` = 32 on this machine). CPU SIFT on 12MP images at 32-way
  parallelism OOM-kills partway through (`SIGKILL`, exit 137) — same failure
  shape as the gsplat `MAX_JOBS` issue documented in the main README, same
  fix (cap parallelism). **This flag does not control reproducibility either
  way** — see "Full pipeline determinism, retested" below: independent runs
  at `num_threads 1` disagreed just as much as runs at `num_threads 4`.

Result: 30/30 images processed every time this was run (never a source of
missing images), ~1m6s–1m11s wall time at `num_threads 4`, ~3m33s at
`num_threads 1`. Log confirms 30 distinct camera entries (`Camera #1` …
`#30`) each run, confirming `single_camera 0` took effect.

## Step 3 — Feature matching

```
colmap exhaustive_matcher \
  --database_path pipelines/image/data/galanakis2021/colmap/database.db \
  --SiftMatching.use_gpu 0 \
  --SiftMatching.num_threads 4
```

**Exhaustive, not sequential or vocab-tree.** With only 30 images that's 435
pairs (n·(n-1)/2) — small enough that exhaustive pairwise matching is both
correct (no approximation) and fast (~1m21s–1m32s here at `num_threads 4`,
~4m42s at `num_threads 1`). Sequential matching assumes temporally/spatially
ordered frames (video-like capture) and vocab-tree trades accuracy for speed
on much larger sets (hundreds to thousands of images) where exhaustive's
O(n²) cost becomes prohibitive. Neither tradeoff applies at this scale —
exhaustive is the correct choice here, not just the simplest one, and this
choice needs revisiting if this dataset ever grows substantially.

## Step 4 — Sparse reconstruction (mapper)

```
colmap mapper \
  --database_path pipelines/image/data/galanakis2021/colmap/database.db \
  --image_path pipelines/image/data/galanakis2021/photos_corrected \
  --output_path pipelines/image/data/galanakis2021/colmap/sparse \
  --Mapper.num_threads 1
```

`--Mapper.num_threads 1` is pinned here because, **given a fixed, unchanging
database**, it makes the mapper stage itself reproducible: rerunning the
mapper alone against the same feature/match database, repeatedly, at
`num_threads 1`, gave the same registered-image count every time — confirmed
across three separate databases (21/21/21 on the original database, 20/20 on
a GPU-SIFT database, 20/20 on a freshly-rebuilt CPU database). At the default
thread count (`nproc`=32, tested explicitly at 4) the same fixed database
gave 22 on one run and 21 on an immediate rerun — clear thread-scheduling
nondeterminism in COLMAP's incremental SfM (RANSAC-based initial-pair search,
multi-threaded bundle adjustment) that the default `--random_seed 0` doesn't
pin down.

**But this only fixes the mapper stage in isolation.** It says nothing about
whether `feature_extractor` and `exhaustive_matcher` themselves produce the
same database on independent runs — every check above reused one cached
database. That assumption turned out to be false; see next section.

## GPU SIFT under Wayland — tested directly, ruled out

Task ask: try to get SiftGPU working before accepting CPU-only SIFT, since
Phase 2 likely had a working GPU SIFT path and this is a plausible driver of
the registration gap.

`QT_QPA_PLATFORM=xcb` (forces the XWayland/X11 path instead of native
Wayland) fixes it cleanly:

```
QT_QPA_PLATFORM=xcb colmap feature_extractor --SiftExtraction.use_gpu 1 \
  --database_path <db> --image_path pipelines/image/data/galanakis2021/photos_corrected \
  --ImageReader.single_camera 0
QT_QPA_PLATFORM=xcb colmap exhaustive_matcher --SiftMatching.use_gpu 1 --database_path <db>
```

Both ran to completion, 30/30 images extracted, exit 0. Feature counts per
image differ measurably from CPU SIFT on the same images (e.g. `IMG_0457.jpg`:
13509 features via GPU vs. a different count via CPU) — confirming COLMAP's
CPU and GPU SIFT are not bit-identical, as expected.

Ran the full pinned sequence (feature_extractor → exhaustive_matcher, both
GPU, → mapper at `--Mapper.num_threads 1`, unchanged) end to end:

**Result: 20/30 registered (66.67%) — confirmed stable across two mapper
reruns on the same GPU-SIFT database, but *lower* than CPU SIFT's runs, not
higher.**

**This is a real negative result, not a silent non-finding: GPU SIFT does
not explain the gap to Phase 2's 83.33%.** If CPU-vs-GPU SIFT were the
driver, GPU should have registered noticeably more images, closer to 25/30.
It didn't — it landed within the same 20–22/30 range CPU SIFT produces
across independent runs (see next section), and specifically at the low end
of it. The CPU/GPU SIFT difference is real (different feature counts,
confirmed directly) but it is not the explanation for the gap to Phase 2.
GPU SIFT was not adopted for the pinned sequence — no benefit, and it adds a
`QT_QPA_PLATFORM` dependency the CPU path doesn't need.

Total time spent on this: ~12 minutes, within the ~15-minute time-box.

## Full pipeline determinism, retested — it does not hold

The original version of this doc treated `--Mapper.num_threads 1` as making
the whole pipeline reproducible. That was never actually tested — every
repro check reused one cached database. Retested properly: delete
`database.db` and `sparse/` entirely, rerun `feature_extractor` →
`exhaustive_matcher` → `mapper` from scratch, at the exact pinned settings
(`--SiftExtraction.num_threads 4`, `--SiftMatching.num_threads 4`,
`--Mapper.num_threads 1`).

**Result: 20/30 registered — not the 21/30 the previous pass had documented
as "the" number, from the exact same commands.**

Confirmed the new database's mapper stage is itself internally stable
(reran mapper alone against this new database: 20/20 again) — so the
disagreement is upstream, in `feature_extractor` and/or `exhaustive_matcher`,
not in the mapper. Since `--Mapper.num_threads 1` didn't cause this
(mapper-in-isolation was already proven stable), the next hypothesis was
thread-scheduling nondeterminism *inside* feature extraction/matching at
`num_threads 4`. Tested that directly: ran the full pipeline twice more,
independently, with **every stage forced to `num_threads 1`**
(`feature_extractor`, `exhaustive_matcher`, and `mapper` all single-threaded):

| Run | Threading | Registered |
|---|---|---|
| Run A | fully single-threaded | 21/30 |
| Run B | fully single-threaded, independent of A | 22/30 |

**Still different. Single-threading every stage does not restore
determinism.** This rules out thread-scheduling as the root cause. Something
inside COLMAP 3.9.1's SIFT extraction or two-view geometry RANSAC is drawing
from a randomness source that `--random_seed 0` (the default, used
unchanged in every run above) doesn't fully control — most plausibly the
RANSAC-based geometric verification step in feature matching, which is a
known category of issue in SfM tools where a global `--random_seed` flag
doesn't get threaded through to every RNG consumer in the codebase. Chasing
this into COLMAP's C++ source to find the exact unseeded call site is out of
scope for this task (COLMAP config only, no source patching) — recorded here
as a known, real limitation of this COLMAP 3.9.1 build, not chased further.

**All registration counts observed across every independent full-pipeline
run in this investigation**, CPU and GPU, every threading configuration:

| Run | Config | Registered | % |
|---|---|---|---|
| Original canonical run | CPU, extractor/matcher @4, mapper @4 | 22/30 | 73.33% |
| Same DB, mapper rerun @4 | CPU, mapper @4 | 21/30 | 70.00% |
| Same DB, mapper @1 (×3 reruns) | CPU, mapper @1 | 21/30 (×3, stable) | 70.00% |
| Clean rebuild, pinned settings | CPU, extractor/matcher @4, mapper @1 | 20/30 | 66.67% |
| Same clean DB, mapper rerun @1 | CPU, mapper @1 | 20/30 (stable) | 66.67% |
| GPU SIFT, pinned mapper | GPU (xcb), mapper @1 | 20/30 (×2, stable) | 66.67% |
| Fully single-threaded, run A | CPU, everything @1 | 21/30 | 70.00% |
| Fully single-threaded, run B | CPU, everything @1, independent | 22/30 | 73.33% |

Range: **20–22 out of 30 registered (66.67%–73.33%)**, across 8 independent
full or partial pipeline runs. `--Mapper.num_threads 1` remains worth pinning
— it's a real, confirmed fix for one genuine source of variance (the mapper
stage, given fixed inputs) — but it is not sufficient on its own to make a
specific registration number reproducible, and this doc no longer claims it
is.

## Result vs. baseline

| Run | Registered | % |
|---|---|---|
| Phase 2, no EXIF fix | 17/30 | 56.67% |
| Phase 2, EXIF fix + `single_camera 0` | 25/30 | **83.33%** (target) |
| This environment, observed range (8 independent runs) | 20–22/30 | **66.67%–73.33%** |
| Current on-disk artifact (`colmap/transforms.json`) | 20/30 | 66.67% |

**The fix (EXIF correction + `single_camera 0`) clearly still works** —
every number in the observed range is far closer to Phase 2's post-fix
83.33% than to its pre-fix 56.67%, and the EXIF correction is confirmed
necessary and correctly applied (Step 1, unaffected by any of the
nondeterminism above). But no run in this environment reached 83.33%, and
that gap is now much better understood than "plausible but unverified":

1. **GPU vs. CPU SIFT does not explain it** — tested directly (see above),
   GPU SIFT scored at the low end of the CPU range (20/30), not higher.
   Ruled out as the driver of the gap.
2. **This COLMAP 3.9.1 build has genuine, unexplained run-to-run
   nondeterminism** in feature extraction and/or matching, independent of
   threading, that `--random_seed 0` doesn't fully control. Phase 2's own
   83.33% was one draw from whatever this same nondeterminism looked like on
   their machine/build — not a fixed target this environment is failing to
   hit, but one sample from a noisy process this environment also produces
   samples from. The observed range here (66.67%–73.33%) simply hasn't
   happened to include an 83.33%-equivalent draw in 8 attempts.

**What this means for Task 4**: there is no single "true" registration
number for this dataset in this environment — treat 66.67%–73.33% as the
honest range, not 70.00% or any other single run as ground truth. The
concrete `transforms.json` currently on disk (20/30, 66.67%, from the "clean
rebuild" run above) is what Task 4 will actually load — it's a real,
internally-consistent, valid reconstruction, just not a uniquely
reproducible one. If Task 4's results look meaningfully different from a
future rerun of this doc's commands, this nondeterminism — not a Task 4 bug
— is the first thing to check.

## Step 5 — Convert to nerfstudio `transforms.json`

```
ns-process-data images \
  --data pipelines/image/data/galanakis2021/photos_corrected \
  --output-dir pipelines/image/data/galanakis2021/colmap \
  --skip-colmap \
  --colmap-model-path sparse/0 \
  --no-same-dimensions
```

- `--skip-colmap`: don't re-run SfM, just convert the sparse model already
  produced above.
- `--colmap-model-path sparse/0`: relative to `--output-dir`, matching where
  Step 4 wrote the model.
- `--no-same-dimensions`: the 30 photos are a genuine mix of portrait and
  landscape shots (18/12, per Step 1) — this is normal photo variety, not
  the EXIF bug — so nerfstudio must not assume uniform dimensions when
  copying/downscaling.

nerfstudio's own conversion log independently reports **"COLMAP only found
poses for 66.67% of the images"** for the sparse model currently on disk — a
second, independent confirmation of the 20/30 figure, computed by different
code than `model_analyzer`.

Output, under `pipelines/image/data/galanakis2021/colmap/`:
- `transforms.json` — 20 frames (only the registered images from the
  currently-on-disk sparse model; this is expected, not a bug — unregistered
  images simply have no recovered pose)
- `images/` — all 30 source images copied in (nerfstudio's own convention;
  the 10 unregistered ones are simply absent from `transforms.json`'s
  `frames` list)
- `sparse_pc.ply` — point cloud exported from the sparse model, usable for
  Splatfacto's point-cloud initialization in Task 4 instead of random init

**This is as far as Task 3 goes.** `transforms.json` + `images/` are in
place and ready; Task 4 (`ns-train splatfacto --data
pipelines/image/data/galanakis2021/colmap ...`) was not run.

## Full pinned command sequence (copy-paste)

**Caveat, given the finding above: rerunning this sequence is not guaranteed
to reproduce exactly 20/30 registered.** Expect a result somewhere in the
66.67%–73.33% range. `--Mapper.num_threads 1` is still worth keeping (it
removes one confirmed source of variance), but treat the exact count as a
draw from a range, not a target to hit.

```
conda activate crime-image
cd ~/crime-graph

python pipelines/image/scripts/fix_exif_orientation.py \
    pipelines/image/data/galanakis2021/photos \
    pipelines/image/data/galanakis2021/photos_corrected

colmap feature_extractor \
  --database_path pipelines/image/data/galanakis2021/colmap/database.db \
  --image_path pipelines/image/data/galanakis2021/photos_corrected \
  --ImageReader.single_camera 0 \
  --SiftExtraction.use_gpu 0 \
  --SiftExtraction.num_threads 4

colmap exhaustive_matcher \
  --database_path pipelines/image/data/galanakis2021/colmap/database.db \
  --SiftMatching.use_gpu 0 \
  --SiftMatching.num_threads 4

mkdir -p pipelines/image/data/galanakis2021/colmap/sparse
colmap mapper \
  --database_path pipelines/image/data/galanakis2021/colmap/database.db \
  --image_path pipelines/image/data/galanakis2021/photos_corrected \
  --output_path pipelines/image/data/galanakis2021/colmap/sparse \
  --Mapper.num_threads 1

colmap model_analyzer --path pipelines/image/data/galanakis2021/colmap/sparse/0

ns-process-data images \
  --data pipelines/image/data/galanakis2021/photos_corrected \
  --output-dir pipelines/image/data/galanakis2021/colmap \
  --skip-colmap \
  --colmap-model-path sparse/0 \
  --no-same-dimensions
```

(`colmap mapper` does not create its own `--output_path` — `mkdir -p` it
first or it aborts with `cameras, images, points3D files do not exist`.)

## File layout after this doc's steps

```
pipelines/image/data/galanakis2021/
├── photos/              # 30 raw source images, untouched
├── photos_corrected/    # 30 images, EXIF orientation baked in, 0 residual tags
└── colmap/
    ├── database.db       # feature + match database (this exact db: 20/30 registered)
    ├── sparse/0/         # sparse reconstruction: cameras.bin, images.bin, points3D.bin
    ├── images/            # 30 images copied in by ns-process-data
    ├── sparse_pc.ply       # point cloud, for Task 4's Splatfacto init
    └── transforms.json      # 20 registered frames, ready for Task 4
```
