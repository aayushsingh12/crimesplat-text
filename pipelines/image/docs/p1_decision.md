# Phase 1 — Decision Log

Running record of what happened and why, kept as-we-go so decisions made in
conversation don't evaporate. Newest entries at the bottom. Each entry: what
happened, what was decided, what's still open.

---

## Task 0 — Dev environment
- crime-image conda env, torch 2.11.0+cu128, RTX 5060 confirmed CUDA-functional.
- Blackwell/sm_120: stable cu128 wheel worked fine (no nightly fallback needed —
  simpler than expected going in).
- gsplat needed CUDA_HOME wired + MAX_JOBS=4 capped (OOM otherwise). Persisted via
  conda activate.d/deactivate.d hooks, not shell exports — proved from a genuinely
  fresh shell.
- Checkpoint round-trip (train → ns-eval load) confirmed working — the specific
  Blackwell failure mode we were worried about did NOT reproduce. Real blocker was
  a torch 2.6+ `weights_only` default breaking nerfstudio's own eval script — worked
  around with `pipelines/image/scripts/eval_checkpoint.py`, explicit trusted-source-only
  warning included.
- Committed: environment.yml, README.md, scripts/. Data/output artifacts correctly
  excluded, never staged.

## Task 3 — COLMAP configuration
- Real dataset: 30 photos, `pipelines/image/data/galanakis2021/photos/` (moved from a
  stray root-level `zendoo_images/`).
- EXIF orientation fix scripted (`fix_exif_orientation.py`), 3/30 images actually needed it.
- **COLMAP 3.9.1 registration on this dataset is NOT a fixed number.** Confirmed
  across 8 independent full/partial reruns: range is 20–22/30 (66.67%–73.33%).
  - Mapper alone is deterministic when pinned to `--Mapper.num_threads 1` (confirmed:
    3/3 identical reruns against one fixed database).
  - But feature extraction/matching has its own unexplained nondeterminism upstream
    of the mapper — not fixed by single-threading everything either (two fully
    single-threaded runs gave 21 and 22). Not chased into COLMAP's source; flagged as
    likely an under-seeded RNG in RANSAC-based geometric verification.
  - GPU SIFT tested directly (Wayland/EGL fix: `QT_QPA_PLATFORM=xcb`) — works, but
    gave 20/30, not higher than CPU SIFT. Ruled out as the explanation for the gap
    to Phase 2's 83.33%.
- Phase 2's 83.33% (25/30) was itself one draw from this same noisy process, never
  stress-tested for reproducibility at the time. **Decision: report the orientation-fix
  effect as a range comparison, not delta-between-two-single-numbers, in the eventual
  writeup.**
- `colmap_config.md` rewritten to document the range + both negative results (GPU SIFT,
  thread-pinning) honestly rather than the original single-number claim.

### Open, deliberately not blocking further work
- **No-fix baseline has not been re-stress-tested the same way** — only one old number
  (56.67%) exists for it. Follow-up: rerun the no-fix case 8x the same way, get an
  honest range-vs-range comparison, before this goes in the paper. Not done yet —
  proceeding to Task 4 without it per this entry's decision below.
- **Decision, this entry: Task 4 trains on whatever's currently on disk** at
  `pipelines/image/data/galanakis2021/colmap/transforms.json` (the most recent rerun,
  20/30 registered) rather than picking a "representative" run or re-generating one.
  This is a specific, traceable choice — not "whatever happened to be there" — logged
  here so Task 4's eventual metrics are attributable to a known input set.

---

## Task 4 — Splatfacto training
- Trained on `pipelines/image/data/galanakis2021/colmap/transforms.json` as it stood per
  Task 3's decision (20/30 registered, not regenerated). Command + full rationale in
  `splatfacto_config.md`.
- `--max-num-iterations 30000` (already nerfstudio's default, matches Phase 2's slides),
  point cloud init from the real COLMAP sparse points (`sparse_pc.ply`, 7162 pts) confirmed
  actually used, not a silent random-init fallback.
- Training: exit 0, "Training Finished", ~16.5 min wall time. Checkpoint reload confirmed
  via `eval_checkpoint.py` (`✅ Done loading checkpoint`) — same rigor as the Task 0 smoke
  test, not just trusting exit 0.
- **Convergence evidence, since `--vis viewer` (default) disables periodic eval/PSNR
  logging**: Gaussian count grew 7,162 → ~520K by step ~9,200, then held stable
  (480K–520K) through the remaining ~21,000 steps — densification/culling equilibrium, not
  runaway or collapsed. Zero NaN/Inf/divergence anywhere in the log.
- Eval: nerfstudio's own PSNR/SSIM/LPIPS (`ns-eval`, via the same wrapper) — no separate
  Phase 2 eval script exists anywhere in this repo to find or reinvent. **Eval split is
  18 train / 2 eval** (default 90/10 fraction split on 20 registered images) — a real
  caveat, not a footnote: n=2 is too small for a tight benchmark number.
- **Results vs. Phase 2's 0.60/12.36/0.54 (SSIM/PSNR/LPIPS, fixed-orientation run):**
  SSIM 0.6394 (**better**, +6.6%), PSNR 11.76 (−4.9%), LPIPS 0.5863 (+8.6% worse). All
  small, mixed-direction deviations — not wildly off, one metric actually beats Phase 2.
  Consistent with Task 3's finding that registration itself isn't a fixed number (this run
  trained on 20/30, Phase 2's was 25/30 — different registered images, different scene
  coverage, different tiny eval set). **Decision: read this as expected noise from a
  different input set, not a pipeline bug** — nothing here (crash, unloadable checkpoint,
  NaN, runaway/collapsed Gaussian count, wildly-off metrics) looks like a real problem.
- Full pinned command, rationale for every flag, and the "what would have been a red flag"
  checklist are in `splatfacto_config.md`, matching `colmap_config.md`'s format.

### Open, deliberately not blocking further work
- **No convergence curve exists for this run** — would need `--vis tensorboard` (or
  similar) from the start; not rerun for this task.
- ~~Eval set (n=2) is too small to treat these numbers as a tight benchmark~~ — attempted
  to fix, see below: turns out it can't be fixed on this dataset without violating the
  other stated constraint (don't starve training). n=2 stands as the only number available.
- **No-fix baseline Splatfacto run** — explicitly out of scope for this task, logged as
  separate follow-up (ties to Task 3's same open item on the no-fix COLMAP baseline).
- **Whatever COLMAP registration count a future rerun lands on (20–22/30, per Task 3),
  expect these Splatfacto metrics to move somewhat too** — that's the dataset's own noise
  floor, not something to chase as a bug if a future retrain's numbers differ from this
  entry's.

## Task 4b — Eval split methodology revisit (attempted fix, real negative result)
- Goal: replace the n=2 eval set with something meaningfully larger (target ~80/20, per
  explicit instruction) across 3 seeded runs, reporting SSIM/PSNR/LPIPS as a range like
  Task 3 reported the registration range.
- **Checked live, not assumed**: `--eval-mode fraction` (nerfstudio's default) has no seed
  because it has no randomness — `get_train_eval_split_fraction()` uses `np.linspace`, a
  fully deterministic strided pick. To get genuinely seed-varied splits at all, had to use
  the other supported mechanism, `--eval-mode filename`, with a new script
  (`pipelines/image/scripts/make_eval_split.py`) doing the seeded random train/eval
  filename tagging via symlinks over the pinned `colmap/` reconstruction (untouched).
- Chose 16 train / 4 eval (80/20, doubling the eval set, only 2 fewer training images than
  the working 18/2 baseline). Ran all 3 seeds.
- **All 3 seeds crashed. Identically.** `torch.OutOfMemoryError` inside splatfacto's SSIM
  loss, on this 8GB GPU. Gaussian count in every run grew past **1.2 million and was still
  climbing** at the crash (~2.5x the stable 18-train run's ~495K plateau) — different
  crash step per seed (~10,000 to ~18,800) but the same runaway-not-plateauing dynamic
  every time, across 3 different held-out image sets. Not seed noise.
- **Boundary probe** (17 train / 3 eval, one run): also crashed, same mechanism, Gaussian
  count 1.24M and climbing. **The boundary is precise: 18 training images is stable, 17 is
  already not.**
- **Decision: report this as the real finding, not paper over it.** Per the task's own
  framing ("flag clearly if 20 total images turns out to be too few... regardless of
  ratio — that would itself be a real, worth-reporting constraint"): it is. On this
  20-image dataset with this GPU, there is no split point that both grows the eval set and
  avoids starving training — the two requested constraints are mutually exclusive here.
  **No SSIM/PSNR/LPIPS range exists for an expanded split, because nothing at any expanded
  split finished training.** Task 4's original 18/2 numbers (SSIM 0.6394 / PSNR 11.76 /
  LPIPS 0.5863) remain the only trustworthy metrics for this dataset.
- Full crash table, mechanism analysis, and the untested `expandable_segments:True`
  allocator-tuning lead are in `splatfacto_config.md`'s "Eval split methodology —
  revisited" section.

### Open, deliberately not blocking further work
- **`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`** not tried — might buy headroom on
  the 16/17-train crashes, but every crash showed Gaussian count still climbing (not
  plateaued), so it would very plausibly just delay the same crash rather than fix it.
  Untested, not assumed either way.
- **Real fix for a larger eval set is more source photos or more GPU VRAM, not a
  different ratio on the current 20 images.** This is a dataset-size constraint, not a
  bug in the pipeline.
- Background/environment note from this task, unrelated to the finding above: several
  background training launches were killed externally mid-startup with no traceback (not
  a training crash) before a clean retry succeeded — cause undetermined, not chased
  further since retries reliably worked and it didn't affect any of the actual results.

## Task 4b (cont.) — Isolation verification, closing entry

- Goal: rule out that the 17-train/3-eval OOM (and by extension the 16/4 crashes) was
  contamination from this session's separate, unrelated mid-startup process kills, before
  treating the 18-vs-17 boundary as a real finding. Reran the 17/3 boundary probe once more
  under deliberately tightened isolation: GPU confirmed idle immediately before launch
  (`nvidia-smi`: 13MiB, only gnome-shell; no other training process via `ps aux`), launched
  under continuous supervision (not a bare detached background job), VRAM polled live
  throughout, and the working 18/2 vs. this 17/3 run's full resolved `config.yml`s diffed
  side by side.
- **Result: identical crash.** `torch.OutOfMemoryError` at step 8,720/30,000 (29.07%), same
  mechanism (SSIM loss inside `splatfacto.py`'s `get_loss_dict`), full Python traceback,
  clean exit code 1, GPU VRAM released to 13MiB immediately after — a genuine allocation
  failure, not an external kill. Gaussian count read directly from the last surviving
  checkpoint's tensor shapes (not inferred from a log line): 1,195,982 and still climbing at
  step 8,000, matching the original run's 1,244,065-at-crash finding. VRAM traced climbing
  steadily to the GPU's real ~7.5GB ceiling, not a step-function. Config diff confirmed
  clean — only `eval_mode` and the data path differ, no silent resolution/downscale/
  batch-size drift from `--eval-mode filename`. Full evidence in `splatfacto_config.md`'s
  "Verification run" addendum.
- **Decision: the 18-vs-17 boundary is a real, confirmed per-image-count finding, not an
  artifact of the session's separate unexplained-kill issue.** Eval-split expansion is
  confirmed impossible on this 20-image dataset with this 8GB GPU — not merely observed to
  fail four times, but independently reproduced under strict isolation. **18-train/2-eval
  (SSIM 0.6394 / PSNR 11.76 / LPIPS 0.5863) remains the only trustworthy result for this
  dataset.** No further reruns of this boundary are planned.
- **Plausible mechanism identified** (not chased into a full diagnosis — out of scope):
  consistent with vanilla 3D Gaussian Splatting's known sparse-view failure mode — adaptive
  density control's gradient-driven splitting outruns pruning pressure when multi-view
  constraint is too thin in some scene regions, and 17 training images is already a
  sparse-view regime for this scene. Offered as the plausible *why* the boundary sits where
  it does, not a confirmed root cause requiring further investigation.
- **The "cause undetermined" mid-startup-kill note above is now closed, with a different
  cause than the OOM finding this task is about**: `dmesg`/`journalctl` show `NVRM: ...
  NV_ERR_NO_MEMORY` plus a GPU power-cycle signature (`Enabling HDA controller` firing twice
  a few seconds apart) at the exact second of each prior silent death, no Linux OOM-killer
  entry either time. Consistent with this laptop's GPU runtime power management (PCIe
  `power/control: auto`, `Runtime D3 status: Enabled (fine-grained)`) racing a
  freshly-launching CUDA context — unrelated to the Gaussian-runaway OOM mechanism
  throughout this task. Fix (`power/control: on`) requires interactive `sudo` this session
  can't supply non-interactively; flagged to the user, not applied by this entry.

## Task 5 — Post-training Gaussian cleanup

- Goal: prune floating/noise Gaussians from Task 4's pinned checkpoint
  (18-train/2-eval, 480,560 Gaussians) and measure the effect with the same
  rigor as everything else this session — real tensor reads, not assumed
  3DGS-textbook behavior; real before/after eval on the same split; a real
  visual comparison, not "looks cleaner."
- **Inspected the actual checkpoint first**: opacities/scales are stored
  unactivated (logit/log-scale — confirmed against this environment's
  nerfstudio 1.1.5 source, not assumed), so all analysis was done in
  sigmoid/exp-activated space. Real distribution: 5.115% of Gaussians
  (24,580) sit below this checkpoint's own training config's
  `cull_alpha_thresh` (0.1); scale has a severe heavy tail (p99.9=0.837,
  max=55.29 — a ~66x jump), with 0.408% (1,962) above the same config's
  `cull_scale_thresh` (0.5). Full percentile tables in `cleanup.md`.
- **Thresholds used are this checkpoint's own training-time culling values**
  (0.1 opacity, 0.5 max-axis scale), not invented constants — justified
  directly by the distribution above: these are Gaussians that drifted past
  Splatfacto's own stated culling criteria after the last refinement pass
  before training ended, not a new standard applied post-hoc.
- **Pruned**: 480,560 → 454,084 Gaussians (26,476 removed, 5.509%), read
  from tensor shapes before and after via
  `pipelines/image/scripts/prune_checkpoint.py`. Re-evaluated on the exact
  same 18/2 split (`--eval-mode fraction`, same `data:` dir) via a sibling
  output directory differing only in `experiment_name`.
- **Result: real, measurable Gaussian removal; no measurable quality
  change.** PSNR 11.76→12.05 (+2.4%, but smaller than the run's own
  ±0.27 std dev at n=2 eval images), SSIM 0.6394→0.6380 (−0.2%), LPIPS
  0.5863→0.5891 (+0.5%) — every delta inside noise. Rendered before/after
  eval images are visually near-identical; a raw pixel diff on the render
  half (ground-truth half confirmed byte-identical) shows a real but
  localized change (7.1/255 mean diff, up to 15% of pixels shifted >5/255
  in one view) — floaters were genuinely removed and genuinely rendering
  *something*, just not enough to move whole-image metrics past this small
  eval set's noise floor.
- **Decision: report this as the honest finding, not manufacture a win.**
  This is a small, controlled indoor scene whose quality ceiling is set by
  the 18-image training-set size (per `splatfacto_config.md`'s eval-split
  findings), not by leftover floater/noise Gaussians — cleanup cannot fix
  an undertrained reconstruction, and didn't need to fix a large floater
  problem here because Splatfacto's own training-time culling had already
  been doing most of that work throughout training. 5.51% Gaussian
  reduction with no quality cost is still a legitimate, real result (a
  slightly leaner checkpoint at equal quality), just not a dramatic one.
- Full distribution tables, pruning script, before/after eval JSON, pixel
  diff numbers, and a committed before/after render pair are in
  [`cleanup.md`](cleanup.md).

### Open, deliberately not blocking further work

- Only one threshold pair tried (this checkpoint's own cull values) — a
  more aggressive scale cut wasn't tried, not expected to change the
  null-result quality finding since it would only remove even fewer
  Gaussians.
- This finding is specific to the 2 pinned eval views — a floater outside
  both eval cameras' frustums wouldn't show up in either the metrics or the
  pixel diff even if visible from another angle (e.g. the interactive
  viewer). Not chased further, out of scope for this task.
- Pruned checkpoint stays local under `outputs/colmap_pruned/` (not
  committed, same policy as every other checkpoint this session) — only the
  two representative render PNGs are committed, under `docs/assets/`.

## Task 6 — Second-scene validation (FFS `th_0085`) — negative result, stopped at COLMAP

- Goal: run the full pinned pipeline (EXIF fix → COLMAP → Splatfacto →
  cleanup) on a second, independent scene to test whether Tasks 3–5's
  findings generalize beyond `galanakis2021`. Time-boxed under real
  presentation-deadline pressure — explicitly a lighter-touch check than
  Task 3's 8-run characterization, stated as such in the doc, not
  represented as equivalent rigor.
- **Dataset**: FFS (Zenodo, CC BY-NC-SA 4.0). Checked the actual record
  listing live before downloading — the task brief's DOI (17164106) is one
  part of a 5-part series (each part its own Zenodo record, 18.75–47.45 GB);
  picked Part 5 (18623225, 18.75 GB, smallest). Downloaded **one scene only**
  (`th_0085`, 24 images, ~64 MB) via HTTP range requests + `remotezip`
  reading the remote zip's central directory — never pulled the 18.75 GB
  package itself. Content warning (realistic mannequins) acknowledged per
  the task ask, not dwelt on further.
- **EXIF fix**: ran clean, 0/24 needed rotation (vs. `galanakis2021`'s
  3/30) — a real scene-specific difference, not a bug.
- **COLMAP, unfiltered, 5 independent full-pipeline reruns**: registration
  collapsed to **2–7/24 (8.33%–29.17%)** — far below `galanakis2021`'s
  66.67–73.33% range, and not the same *kind* of variance (there: RANSAC
  noise in a well-connected graph; here: mostly non-registration).
- **Diagnosed why, not just observed it**: queried the verified two-view
  match graph directly (`two_view_geometries` table, union-find over
  nonzero-inlier pairs). Found the 24 images split into one 18-image
  connected component plus two isolated 3-image clusters — confirmed
  visually as tight macro/close-up shots of single evidence items (zero
  shared background with the room-wide shots) vs. the room-wide
  establishing shots. Even within the 18-image component, most pairwise
  matches are weak (~half under 20 inliers); only a dozen-ish pairs among
  the wide shots are strongly matched.
- **Filtered rerun** (18-image main component only, 2 reruns, hard-capped
  per this task's explicit stop instruction): **4/18 (22.22%) and 6/18
  (33.33%)** — better than the unfiltered low end, nowhere near
  `galanakis2021`'s range. Registered images in both filtered runs were
  subsets of the same dozen strongly-matched wide shots — confirms the
  issue isn't just "a few contaminating macro shots" but that this scene's
  forensic-documentation capture style (item-by-item macro shots + a
  handful of wide shots) doesn't provide `galanakis2021`-grade
  neighbor-to-neighbor overlap even among the "good" images.
- **Decision: stopped before Splatfacto/cleanup.** No run (filtered or
  unfiltered) crossed the task's ~40% floor for a registration worth
  training on (best case 29.17% unfiltered, 33.33% filtered). Training
  Splatfacto on a 4–7-image point cloud would produce a number for a slide
  without a real result behind it — against this project's standing rule.
  **This is the honest validation outcome, not a shortfall in this task**:
  the pipeline correctly attempted registration, correctly reported what it
  found, and what it found — via two independent lines of evidence — is a
  real capture-protocol mismatch, not a pipeline defect.
- **Reading against Tasks 3–5**: what generalizes — the EXIF-fix step
  (correctly a no-op here), the COLMAP command sequence (produced a real,
  diagnosable reconstruction attempt, not a crash), and registration
  non-determinism as a general property of this COLMAP build. What doesn't
  generalize — the specific 66–73% range, because that assumed
  `galanakis2021`'s strong-neighbor-overlap capture protocol, which
  `th_0085`'s forensic-documentation-style capture doesn't share. **Framed
  as a real capture-protocol constraint on this pipeline** (a scene meant to
  validate it needs walkthrough-style capture, not item-by-item macro
  documentation), **not a bug chased or parameter-tuned away** — no pinned
  config was modified to try to improve this scene's numbers, per this
  task's explicit scope.
- Full evidence (per-run tables, the connectivity breakdown, the visual
  confirmation, the filtered-set registered-image lists) in
  [`second_scene_validation.md`](second_scene_validation.md).

### Open, deliberately not blocking further work

- Only one FFS scene tried (`th_0085`); other scenes in the dataset may
  follow a more walkthrough-like protocol and register normally — not
  tested, per this task's explicit stop instruction.
- No second-scene Splatfacto/cleanup validation exists — Tasks 4/5's
  findings remain validated on `galanakis2021` alone.
- Raw `th_0085`/`th_0085_filtered` data stays local under
  `pipelines/image/data/`, same policy as every other dataset this session
  — not committed.
- **Task 7 and Prompt 2's consolidation work are explicitly not started** —
  stopping here per this task's own instruction.

## Task 7 — Localized failure-mode inspection, `galanakis2021` post-cleanup checkpoint

- Goal: on the one *working* reconstruction (Task 5's pruned checkpoint,
  454,084 Gaussians), find where quality visibly degrades *within* an
  otherwise-successful scene, distinct from the already-known whole-scene
  haze (`cleanup.md`'s PSNR ~12). No new training, no new COLMAP — visual
  inspection of the existing checkpoint only.
- **Method**: new `render_checkpoint.py` wrapper (same `weights_only=False`
  pattern as `eval_checkpoint.py`) to run `ns-render dataset --split
  train+test`, rendering all 20 registered cameras (18 train + 2 eval) as
  both `rgb` and `gt-rgb` — not just the 2 fixed eval views `cleanup.md`
  used. Checkpoint reload reconfirmed (`✅ Done loading checkpoint`).
  Inspected 7 of 18 train views (spread across the sequence, including both
  sides of every COLMAP registration gap) plus both eval views.
- **Finding 1 — recurring frustum-edge chromatic-noise artifact**: a
  rainbow/prism-colored streaking band at the outer edges of the rendered
  frame, absent from the matching real photo, in 5 of the 7 train views
  checked. Best-guess mechanism (flagged as unverified): poorly-constrained
  peripheral Gaussians where fewer overlapping training rays converge near
  each camera's frustum edge — a property of multi-view ray coverage, not
  of one specific object.
- **Finding 2 — floating warped-geometry blob next to a real coverage
  gap**: `frame_00021` (the first registered frame right after the
  documented 5-image 15–19 registration gap) shows an inverted,
  shoe-like brown smear floating where the real photo shows plain
  tablecloth — the rest of that same frame reconstructs cleanly. Best-guess
  mechanism (flagged as unverified): sparse local multi-view support
  immediately after a real gap in registered images.
- **Checked and genuinely found nothing distinct, reported honestly**:
  reflective/glossy surfaces (black cabinets, a window) and thin forensic
  detail (evidence markers, blood-spatter sheets) — both inspected closely,
  neither showed localized degradation beyond the reconstruction's general
  softness. Not a gap in the inspection; a real negative result for those
  two categories specifically.
- **Re-confirmed, not re-litigated**: the eval-view (`frame_00029`) haze
  matches `cleanup.md`'s already-documented PSNR ~12 whole-reconstruction
  ceiling — called out explicitly as the same finding, not double-counted
  as new.
- Both concrete findings are backed by committed render-vs-ground-truth
  image pairs, not description alone. Full method, evidence, and the two
  honestly-negative checks are in
  [`failure_modes.md`](failure_modes.md).

### Open, deliberately not blocking further work

- Both findings' root causes are best-guess, not independently verified
  (e.g. no per-pixel ray-coverage count was computed) — flagged as such in
  the doc, not chased further per this task's visual-inspection-only scope.
- Only 7 of 18 train views were inspected closely, not all 18 — prevalence
  counts (5/7 for Finding 1) are over what was checked, not the full set.
- No retraining, no parameter changes, no new COLMAP runs — per this
  task's explicit scope. Whether either failure mode would respond to a
  training change is untested.

## Task 8 — Methods draft (consolidation, no new experiments)

- Goal: a single coherent narrative document — `methods_draft.md` — that an
  outside reader or reviewer could read to understand the pipeline as a
  whole, consolidating Tasks 0 and 3–7. Pure writing/consolidation; no new
  experiments, no new numbers.
- Every claim traces back to an existing doc (this file,
  `colmap_config.md`, `splatfacto_config.md`, `cleanup.md`,
  `second_scene_validation.md`, `failure_modes.md`) — nowhere does it state
  something not already documented. Where a claim would need evidence that
  was never gathered, the draft says so explicitly rather than filling the
  gap:
  - **The registration-range finding is presented as range vs. an
    unreplicated point, not range vs. range** — `galanakis2021`'s with-fix
    registration was honestly stress-tested 8 times (66.67–73.33%), but its
    without-fix baseline was never re-tested in this environment; the only
    number for it is one historical draw from the project's earlier phase
    (56.67%). The draft states this asymmetry plainly rather than
    presenting it as a controlled before/after comparison.
  - The sparse-view adaptive-density-control explanation for the
    18-vs-17-train boundary is carried into the draft with the same
    epistemic flag it has in `splatfacto_config.md`: the most plausible
    reading of the mechanism, not a verified root cause.
  - Both Task 7 localized-failure explanations (frustum-edge artifact,
    gap-adjacent floating blob) are likewise carried forward flagged as
    best-guess, not confirmed.
- Closes with an explicit "what this pipeline does not yet do" section —
  no calibrated dimensional accuracy, no language-based querying, and a
  direct statement that only one scene (`galanakis2021`) has actually been
  reconstructed successfully end-to-end; `th_0085` is a diagnosed negative
  result at COLMAP, not a second successful validation.

### Open, deliberately not blocking further work

- This is a draft — written for internal consolidation and as the basis
  for the Phase 3 Review 1 deck's underlying narrative, not reviewed by
  anyone outside this session yet.
- The registration range-vs-point asymmetry flagged above (Section 2) is
  named as a gap worth closing (re-stress-testing the no-fix baseline the
  way the with-fix case was tested) but was not closed here — out of scope
  for a consolidation-only task.
- **This is the last task in this sequence** — stopping here per this
  task's own instruction. No further work proceeds without the user.
