# Splatfacto training configuration — `galanakis2021` (Task 4)

Pins the Splatfacto training command for the `galanakis2021` dataset and
records what training actually produced, so this is reproducible and the
numbers are attributable to a known input. Every flag below was checked
against `ns-train splatfacto --help` (and the `nerfstudio-data` dataparser's
own `--help`) on this environment's nerfstudio 1.1.5 install, not assumed
from Phase 2's writeup.

**Input**: `pipelines/image/data/galanakis2021/colmap/transforms.json` — the
20/30-registered COLMAP reconstruction pinned in
[`colmap_config.md`](colmap_config.md) and logged as the deliberate Task 4
input in [`p1_decision.md`](p1_decision.md). Not regenerated for this task.

## Command

```
ns-train splatfacto \
  --data pipelines/image/data/galanakis2021/colmap \
  --max-num-iterations 30000 \
  --viewer.quit-on-train-completion True \
  --pipeline.model.random-init False \
  nerfstudio-data --load-3D-points True
```

- `--max-num-iterations 30000`: already the default (`--help` shows
  `(default: 30000)`) — passed explicitly since it's also what Phase 2's
  slides report ("Trained... for 30,000 iterations"), so the pin doesn't
  silently depend on a default that could change.
- `--viewer.quit-on-train-completion True`: makes the run terminate on its
  own instead of hanging in the viewer — needed for a scripted/background run.
- `--pipeline.model.random-init False` + `nerfstudio-data --load-3D-points
  True`: both already the defaults. Passed explicitly because this is the
  one setting most worth pinning deliberately — it's what makes training
  seed Gaussians from the real COLMAP sparse point cloud (`sparse_pc.ply`,
  7162 points) instead of 50,000 uniformly random points in a cube. Confirmed
  in the run: no `Warning: load_3D_points set to true but no point cloud
  found` line appears (that warning did fire in the Task 0 smoke test, which
  had no point cloud) — the real point cloud was used here.

## Training result

- Exit code 0, ended with `🎉 Training Finished 🎉`.
- Wall time: **~16.5 minutes** (991s) for 30,000 iterations on this GPU.
- Checkpoint: `outputs/colmap/splatfacto/2026-08-24_010039/nerfstudio_models/step-000029999.ckpt`.
- `--save-only-latest-checkpoint` (default `True`) means only this final
  checkpoint was kept — no intermediate checkpoints survive training, so
  there's no way to retroactively inspect an earlier step's model.

### Confirming this is a real, converged reconstruction — not just a clean exit

Per the same rigor as the Task 0 smoke test (training success *and*
checkpoint load, not just exit 0):

1. **Checkpoint reload**: `pipelines/image/scripts/eval_checkpoint.py
   --load-config outputs/colmap/splatfacto/2026-08-24_010039/config.yml
   --output-path <path>` → `✅ Done loading checkpoint`, exit 0. Same
   `weights_only` workaround as the smoke test, same wrapper — no new gotcha
   here.
2. **No divergence**: zero `NaN`/`Inf`/divergence lines anywhere in the full
   training log.
3. **Healthy Gaussian-count trajectory** (a real proxy for training health,
   since `--vis viewer` — the default — disables periodic eval/PSNR logging
   during training; see below): seeded at 7,162 points (the COLMAP point
   cloud), grew through densification to ~520,000 by step ~9,200, then
   **stabilized in the 480,000–520,000 range for the remaining ~21,000
   steps** — densification and culling reaching equilibrium, not exploding
   or collapsing. Final count: 480,560 Gaussians.
4. **Eval metrics are non-degenerate** (see below) — plausible values for a
   working reconstruction on a small, hard dataset, not the near-random
   numbers a silently-broken run would produce.

One real gap: `--vis viewer` (default, unchanged here) prints `[NOTE] Not
running eval iterations since only viewer is enabled. Use --vis {wandb,
tensorboard, viewer+wandb, viewer+tensorboard} to run with eval.` — so there
is no PSNR-over-time curve from this run to point to directly. The Gaussian
trajectory + no-divergence + post-hoc eval metrics together are the evidence
used here instead; a future run wanting a convergence curve should pass
`--vis tensorboard` (or similar) from the start.

## Evaluation

Nerfstudio's own eval computes PSNR/SSIM/LPIPS out of the box — this is what
Phase 2's slides describe ("quantitative evaluation using PSNR/SSIM/LPIPS"),
with no separate custom eval script anywhere in this repo's Phase 2
materials to find or reinvent. Ran via the same
`pipelines/image/scripts/eval_checkpoint.py` wrapper used for the checkpoint
reload above (it *is* `ns-eval`, just with the `weights_only` workaround):

```
python pipelines/image/scripts/eval_checkpoint.py \
  --load-config outputs/colmap/splatfacto/2026-08-24_010039/config.yml \
  --output-path <path>.json
```

**Eval split**: nerfstudio's `nerfstudio-data` dataparser default
(`--eval-mode fraction`, `--train-split-fraction 0.9`), applied to the 20
registered images → **18 train / 2 eval**. Confirmed directly from the
training log's dumped config, not assumed. **This is a real caveat, not a
footnote: 2 held-out images is a very small eval set** — enough to sanity
check the reconstruction, not enough for a statistically robust metric
estimate. A different 2-image split (or a differently-registered COLMAP run,
per `colmap_config.md`'s documented 20–22/30 range) could plausibly move
these numbers by more than run-to-run training noise alone would.

### Results

| Metric | This run | Phase 2 (fixed-orientation) | Δ | Δ% |
|---|---|---|---|---|
| PSNR | 11.76 (±0.16) | 12.36 | −0.60 | −4.9% |
| SSIM | 0.6394 (±0.0085) | 0.60 | **+0.039** | **+6.6%** |
| LPIPS | 0.5863 (±0.0319) | 0.54 | +0.046 | +8.6% |

(SSIM higher is better; PSNR higher is better; LPIPS lower is better. ± is
the per-image std dev across the 2 eval images, not a confidence interval —
with n=2 it barely means anything statistically, included for completeness.)

## Reading these numbers — expected noise, not a red flag

**None of these are wildly off, and one metric (SSIM) is actually better
than Phase 2's.** Per Task 3's finding, COLMAP registration on this dataset
is not a fixed number (20–22/30 observed, 66.67%–73.33%) — this run trained
on the 20/30 draw, not necessarily the same registered-image subset Phase
2's 25/30 run used. Different registered images means different scene
coverage, different viewpoints contributing to the point cloud, and (given
the eval split above) a different, tiny 2-image eval set — small deviations
in any direction are exactly what that predicts, not evidence of a pipeline
problem:

- **SSIM is higher (0.6394 vs 0.60)**: structural fidelity is at least as
  good here as Phase 2's reported run, despite fewer registered images.
- **PSNR is slightly lower (11.76 vs 12.36, −4.9%)** and **LPIPS is slightly
  worse (0.5863 vs 0.54, +8.6%)**: both small, single-digit-to-low-double-digit
  percentage deviations, consistent with a smaller/different training and
  eval image set rather than a broken reconstruction.

**What would have been a real red flag, and wasn't seen**: training not
completing, a crashed or unloadable checkpoint, NaN/Inf in the loss or
Gaussian parameters, a collapsing or runaway Gaussian count, or metrics
wildly off Phase 2's numbers (e.g. PSNR in single digits, SSIM near 0, LPIPS
near 1). None of that happened *at this 18-train/2-eval split*. **This
pipeline produces a working reconstruction from this environment, at the
image counts this specific run used.**

**Important update, see "Eval split methodology" below**: that caveat is
load-bearing. Every one of those exact red flags — runaway Gaussian count,
training not completing — *does* happen on this same dataset the moment
training images drop from 18 to 17. This section's numbers and their
"expected noise, not a bug" reading still stand for the 18/2 split actually
used here; they should not be read as evidence that this dataset tolerates
a meaningfully smaller training set.

## Eval split methodology — revisited

The n=2 eval set above is too small to trust a comparison against Phase 2's
numbers. This section documents an attempt to fix that with a genuinely
larger, randomized held-out set — and a real, hardware-confirmed constraint
that made it impossible on this dataset without violating "don't starve
training."

### The actual split flag, checked live — and why it can't be seeded

`ns-train splatfacto --data <path> nerfstudio-data --help` (checked live,
not assumed):

```
--eval-mode {fraction,filename,interval,all}   (default: fraction)
--train-split-fraction FLOAT                   (default: 0.9)
--eval-interval INT                             (default: 8)
```

No seed flag exists for the split — because there's nothing to seed.
`get_train_eval_split_fraction()` in
`nerfstudio/data/utils/dataparsers_utils.py` (checked directly, not
assumed) picks training images via `np.linspace` over the frame list: a
fully deterministic, evenly-strided selection, zero randomness anywhere in
the code path. The "80/20 with the seed varied across 3 runs" request as
literally stated has no way to be satisfied via `--eval-mode fraction` —
the same fraction always picks the same images.

To get real, seed-varied random splits, this used nerfstudio's other
supported (not hacked-around) mechanism instead: `--eval-mode filename`,
which splits on whether `"train"`/`"eval"` appears in each image's
filename. `pipelines/image/scripts/make_eval_split.py` does the seeded
random assignment: given the pinned `colmap/transforms.json`, a seed, and
an eval count, it writes a self-contained directory with a renamed-copy
`transforms.json` and symlinks back to the real images (and `sparse_pc.ply`)
— no pixel data duplicated, the pinned `colmap/` directory itself untouched.

```
python pipelines/image/scripts/make_eval_split.py \
    --source pipelines/image/data/galanakis2021/colmap \
    --output pipelines/image/data/galanakis2021/eval_splits/seed<N> \
    --seed <N> --eval-count 4
```

### Chosen split: 16 train / 4 eval (80/20), 3 seeds

Per the task's own suggestion ("closer to 80/20"), and to leave training as
close as possible to the working 18-image baseline while still meaningfully
growing the eval set: **eval-count 4** (double the original 2), leaving 16
for training (only 2 fewer than the original 18). Seeds 1, 2, 3.

```
ns-train splatfacto \
  --data pipelines/image/data/galanakis2021/eval_splits/seed<N> \
  --max-num-iterations 30000 \
  --viewer.quit-on-train-completion True \
  --pipeline.model.random-init False \
  nerfstudio-data --eval-mode filename --load-3D-points True
```

**All three seeds crashed. Identically.**

| Seed | Eval images (of 20) | Crash step | Gaussian count at crash | Failure |
|---|---|---|---|---|
| 1 | `frame_00004,06,09,29` | ~10,000 | 1,376,528 and climbing | `torch.OutOfMemoryError` in SSIM loss |
| 2 | `frame_00003,04,21,29` | ~10,100 | 1,230,264 and climbing | `torch.OutOfMemoryError` in SSIM loss |
| 3 | `frame_00006,08,28,29` | ~18,800 | 1,213,662 and climbing | `torch.OutOfMemoryError` in SSIM loss |

Every crash is the same `pytorch_msssim` allocation inside
`splatfacto.py`'s `get_loss_dict`, on this 8GB laptop GPU (`GPU 0 has a
total capacity of 7.53 GiB`). Crash *step* varied (~10,000 to ~18,800,
different held-out images per seed), but the mechanism didn't: in every
run, Gaussian count grew past **1.2 million and was still climbing** at
the moment of the crash — roughly **2.5x** the original 18-train run's
count at a comparable step, which plateaued at ~495K and stayed bounded
(480K–520K) for its last 21,000 steps. Not a fluke of one seed's specific
held-out images — 3 different held-out sets, same runaway trajectory, same
outcome.

**This is not "GPU memory happened to run out" — it's Gaussian densification
itself behaving qualitatively differently.** The stable run reaches an
equilibrium between splitting/duplicating and culling. Every 16-train run
never reached one; it was still growing unbounded when it ran out of room to
grow into.

### Boundary probe: is 16 the cliff, or is any reduction unstable?

One more run, 17 train / 3 eval (85/15, seed 1's assignment minus one eval
image), to find out whether the boundary sits at 16 or is more forgiving:

**Also crashed.** Same failure, same mechanism: Gaussian count reached
1,244,065 and climbing by step ~9,700 before `torch.OutOfMemoryError`.

**The boundary is precise: 18 training images works, 17 does not.** Losing
even one training image below Task 4's original 18 is enough to break this
dataset's densification stability on this GPU.

### Conclusion: 20 total images cannot support an expanded eval set here

**This is the "20 images might be too few, regardless of ratio" finding the
task asked to flag if real. It's real.** Four independent full-pipeline
attempts (3 seeds at 16/4, 1 at 17/3) all failed the same way. There is no
split point between the original 18/2 and a "meaningfully larger" eval set
that both (a) grows the eval set and (b) leaves training un-starved, on this
specific 20-image dataset with this specific 8GB GPU. The two constraints
the task asked to balance turned out to be mutually exclusive here, not
just difficult to balance well.

**No SSIM/PSNR/LPIPS range can be reported for an expanded eval split** —
zero runs at any expanded split completed training, so there are no eval
numbers to report a range over. **The only trustworthy metrics for this
dataset remain Task 4's original 18-train/2-eval numbers** (SSIM 0.6394 /
PSNR 11.76 / LPIPS 0.5863, above) — worse-evidenced than hoped, but not
replaceable by anything gathered here, because nothing here finished.

One unexplored, un-tested mitigation worth naming rather than silently
skipping: PyTorch's own OOM message suggests
`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` for allocator
fragmentation (each crash did show a nontrivial reserved-but-unallocated
gap — e.g. seed 1's crash: 6.58 GiB allocated, 636 MiB reserved-but-idle).
This might buy some extra headroom. It was **not** tried here — even if it
delayed a crash, every run's Gaussian count was still climbing, not
plateaued, at the moment it died, so the underlying instability would very
plausibly still hit a wall shortly after, just a later one. Also, tuning
CUDA allocator behavior is an environment change, not an eval-methodology
one — out of scope for this task as given.

### What would change this finding

A bigger GPU (more VRAM headroom might let densification run away for
longer without crashing — though "eventually stabilizes" vs. "just takes
longer to hit a bigger wall" wasn't distinguished here, since nothing
reached that point). Or, more fundamentally: more source photos. This
constraint is about *this* dataset's size (20 registered images), not a
Splatfacto or COLMAP bug — the real fix is more images, not a training
config tweak.

**Plausible mechanism, not chased further**: this is consistent with the
known sparse-view failure mode of vanilla 3D Gaussian Splatting's adaptive
density control — insufficient multi-view constraint on some regions of the
scene lets gradient-driven splitting proceed without matching pruning
pressure, so densification never reaches the split/cull equilibrium a
better-constrained (more-views) reconstruction settles into. 17 training
images is already a sparse-view regime for this scene; this framing is
offered as the plausible *why*, not a confirmed root cause — actually
diagnosing it (e.g. per-region gradient/visibility analysis) is out of
scope here.

### Verification run — isolated rerun confirms the finding, 2026-08-24

This session separately saw unexplained background training processes get
killed mid-startup with no traceback, before a clean retry succeeded (noted
above as "cause undetermined"). Before treating the 18-vs-17 boundary as a
real per-image-count finding, the 17-train/3-eval case was rerun once more
under deliberately tightened isolation, to rule out that the original
boundary-probe crash was itself contamination from whatever killed those
other processes, rather than a genuine training-time OOM. **This is
corroboration layered on top of the finding above, not a replacement for
it** — the original crash table and conclusion stand unchanged.

**Isolation, checked live immediately before launch**:
```
memory.used [MiB], memory.total [MiB], utilization.gpu [%]
13 MiB, 8151 MiB, 27 %
```
Only `gnome-shell` (2MiB, desktop compositor) held any GPU memory. `ps aux`
confirmed no other `ns-train`/`splatfacto` process running anywhere.

**Execution note**: launched via the harness's supervised background
execution, not a literal single unbroken blocking foreground call — the
crash historically takes 23–103 minutes to arrive (read off prior runs' own
checkpoint-file timestamps), longer than a single blocking tool call
permits. The run was monitored continuously throughout (live `nvidia-smi`
polling + process-liveness checks every ~20s), not left unsupervised —
functionally different from whatever silently killed the earlier
mid-startup processes.

**Config diff, working 18/2 run vs. this 17/3 run** (full resolved
`config.yml`, both sides): the only differences are `data`/`experiment_name`
(expected — different directory) and `eval_mode: fraction` →
`eval_mode: filename` (the deliberate, documented change from "Eval split
methodology" above). Everything else is byte-identical, including
`downscale_factor: null`, `camera_res_scale_factor: 1.0`,
`cache_images: gpu` / `cache_images_type: uint8`, `resolution_schedule:
3000`, `num_downscales: 2`, and every optimizer hyperparameter.
`--eval-mode filename` did **not** silently change resolution, downscale
factor, or any batch-size-equivalent default via the dataparser code path.

**VRAM trajectory**, polled directly via `nvidia-smi` through the run (not
inferred from the log):

| Step | VRAM |
|---|---|
| 340 | ~0 |
| 2,810 | 2.24 GB |
| 4,770 | 3.65 GB |
| 6,110 | 7.12 GB |
| 6,640 | 7.52 GB |
| 7,160–8,220 | 7.4–7.6 GB, fluctuating at the ceiling |
| 8,720 | crash |

A steady climb to the GPU's real ceiling on a GPU confirmed idle
immediately beforehand, with no other process ever appearing in
`nvidia-smi` during the run — the genuine-exhaustion signature, not a
step-function consistent with an external kill.

**Crash**: `torch.OutOfMemoryError` at **step 8,720/30,000 (29.07%)**, same
mechanism as the original finding — `pytorch_msssim`'s SSIM computation
inside `splatfacto.py`'s `get_loss_dict`:
```
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 140.00 MiB. GPU 0 has a total
capacity of 7.53 GiB of which 139.75 MiB is free. Including non-PyTorch memory, this process
has 7.37 GiB memory in use. Of the allocated memory 5.91 GiB is allocated by PyTorch, and
1.11 GiB is reserved by PyTorch but unallocated.
```
Full Python traceback captured, wrapper's own exit-code trap fired cleanly
(`ISOLATED_RERUN_EXIT_CODE=1`), and GPU VRAM dropped straight back to 13MiB
immediately after — a clean process exit on a catchable exception, not a
vanished process or an external SIGKILL.

**Gaussian count**: rather than trust a log line, the last surviving
checkpoint (step 8,000, saved 720 steps before the crash) was loaded
directly and its tensor shapes read:
```
_model.gauss_params.means torch.Size([1195982, 3])
```
**1,195,982 Gaussians, still climbing** at step 8,000 — matches the original
run's 1,244,065-at-crash finding almost exactly. Same runaway-not-plateauing
dynamic, independently reproduced under tightened isolation.

**Conclusion: the finding holds.** Under full isolation — confirmed-clean
GPU, continuously supervised execution, live VRAM monitoring, a config diff
ruling out silent parameter drift — the 17-train/3-eval case still OOMs via
genuine Gaussian-count runaway. The original boundary-probe crash was not
contamination from the session's separate unexplained-kill issue; it is a
real, reproducible property of this dataset at this image count on this
GPU.

**The separate mid-startup-kill mystery, now explained (different mechanism
from the OOM above)**: `dmesg`/`journalctl` show `NVRM: ... Check failed:
Out of memory [NV_ERR_NO_MEMORY]` plus a GPU power-cycle signature
(`nvidia ...: Enabling HDA controller` firing twice a few seconds apart) at
the exact timestamp of each prior silent death — no Linux OOM-killer entry
either time. This machine has GPU runtime power management active
(`Runtime D3 status: Enabled (fine-grained)`, PCIe `power/control: auto`),
a known failure mode where a laptop dGPU's autosuspend/resume races a
freshly-launching CUDA context. This is unrelated to the Gaussian-runaway
OOM documented throughout this file — one is a driver-level hiccup at
process startup, the other is genuine mid-training memory exhaustion — and
is recorded here only to close out the "cause undetermined" note, not as a
revision to the finding above.

## Full pinned command sequence (copy-paste)

```
conda activate crime-image
cd ~/crime-graph

ns-train splatfacto \
  --data pipelines/image/data/galanakis2021/colmap \
  --max-num-iterations 30000 \
  --viewer.quit-on-train-completion True \
  --pipeline.model.random-init False \
  nerfstudio-data --load-3D-points True

find outputs/colmap -name "*.ckpt"

python pipelines/image/scripts/eval_checkpoint.py \
  --load-config outputs/colmap/splatfacto/<timestamp>/config.yml \
  --output-path <path>.json
```

## What's still open

- **No convergence curve** — `--vis viewer` disabled periodic eval logging;
  a rerun with `--vis tensorboard` would give one, not done here.
- **Eval set is 2 images, and — per "Eval split methodology" above — cannot
  be safely grown on this dataset/GPU.** This is now a confirmed structural
  constraint, not just a caveat to note and move past. Growing the eval set
  needs either more source photos or more GPU VRAM (untested here), not a
  different split ratio on the current 20 images.
- **`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`** — named but not
  tested as a possible way to buy extra headroom on the 16/17-train crashes;
  would need a fresh attempt to know if it actually helps or just delays the
  same runaway-Gaussian crash.
- **No-fix baseline Splatfacto run** — not attempted (out of scope per the
  task brief: "Don't start the no-fix baseline rerun — logged as separate
  follow-up work, not this task").
- Ties back to `colmap_config.md`'s open item: whatever COLMAP registration
  count a future rerun lands on (20–22/30), retraining Splatfacto on it
  should be expected to move these metrics somewhat — that's the dataset's
  own noise floor, not this task's bug to chase.
