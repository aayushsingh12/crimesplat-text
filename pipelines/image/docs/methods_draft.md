# Methods — image-based 3D reconstruction pipeline for crime-scene photo sets

This document consolidates Tasks 0 and 3–7 into a single narrative account
of the image pipeline as built and tested: COLMAP structure-from-motion
feeding nerfstudio's Splatfacto (3D Gaussian Splatting), with a
post-training cleanup pass, validated on one real scene and stress-tested
against a second. It is written for a reader who was not present for the
individual task sessions; every claim below traces back to a specific
finding recorded in `p1_decision.md` and the per-task documents it links
(`colmap_config.md`, `splatfacto_config.md`, `cleanup.md`,
`second_scene_validation.md`, `failure_modes.md`) — nothing here is new.
Where a claim would require evidence that was never actually gathered,
that gap is stated explicitly rather than inferred.

The pipeline runs on one development environment (an RTX 5060 Laptop GPU,
8 GB VRAM, CPU-only COLMAP 3.9.1, nerfstudio 1.1.5) documented in the
project README; every quantitative result below is specific to that
environment and is not claimed to generalize to other hardware.

## 1. Capture protocol and preprocessing

The pipeline's input is a set of overlapping photographs of a scene, and
its first processing step exists to correct a specific, avoidable defect
in how phone cameras report those photographs rather than any property of
the scene itself: COLMAP's image reader loads raw pixel arrays and ignores
the EXIF `Orientation` tag that phones attach to indicate how a photo
should be rotated for display. In a photo set with mixed portrait and
landscape shots — the normal case for a handheld walkthrough of a room —
some images are stored "sideways" with an EXIF flag telling a viewer to
rotate them, while others are stored already upright. Left uncorrected,
SIFT feature extraction sees inconsistent effective orientations for
photographs of the same physical surfaces, which degrades the feature
matches that structure-from-motion depends on. This was identified as the
critical preprocessing step in the project's earlier phase, where applying
the fix (together with disabling COLMAP's single-shared-camera assumption)
moved registration on the same scene from 56.67% to 83.33% of the image
set.

The fix is applied by a small script
(`pipelines/image/scripts/fix_exif_orientation.py`) that bakes each
image's EXIF rotation into its actual pixel data via Pillow's
`exif_transpose` and writes the result to a separate directory, leaving
the raw originals untouched. On the pipeline's primary validation scene
(`galanakis2021`, 30 photographs of a single staged room), 3 of the 30
images carried an unbaked `Orientation` tag and were corrected; the
remaining 27 were unaffected no-ops, and every one of the 30 images fed to
COLMAP downstream carries zero residual orientation tags afterward, split
18 landscape to 12 portrait. On the pipeline's second validation scene
(`th_0085`, from the Fictional Forensic Scene dataset, discussed in
Section 5), the same script found nothing to correct at all — 0 of 24
images needed rotation. That is read as a real, scene-specific property of
how each set of photographs happened to be captured, not as evidence the
preprocessing step is unnecessary; the script still ran, still verified
zero residual tags, and would have corrected any image that needed it.

## 2. COLMAP configuration and the registration-range finding

Feature extraction and matching run on CPU (this environment's COLMAP
build has no CUDA support), with per-image camera parameters rather than
one shared calibration across the set (`--ImageReader.single_camera 0`,
already COLMAP's default, pinned explicitly so the command does not
silently depend on a default that could change) and exhaustive pairwise
matching rather than sequential or vocabulary-tree matching — a correct
choice, not just a convenient one, at the 30-image scale used here (435
candidate pairs), though one that would need revisiting if the dataset
grew into the hundreds of images. GPU-accelerated SIFT was tested directly
as an alternative (working once COLMAP's Wayland/EGL crash was worked
around by forcing the XWayland Qt platform) and produced measurably
different per-image feature counts than CPU SIFT, but registered no more
images — it was not adopted, since it added an environment dependency for
no benefit.

The mapper stage (`colmap mapper`) is pinned to `--Mapper.num_threads 1`.
This does make the mapper deterministic *given a fixed, already-built
feature/match database* — confirmed by rerunning the mapper alone against
three separate fixed databases and getting identical registration counts
every time. It does not, however, make the full pipeline deterministic:
a genuinely clean end-to-end rerun (feature extraction and matching redone
from scratch, not reusing a cached database) produces a different
registration count even with every stage forced single-threaded. Across 8
independent full or partial pipeline runs on `galanakis2021`, registration
ranged from 20 to 22 of 30 images (66.67% to 73.33%), including two
fully-independent single-threaded runs that landed on 21 and 22
respectively. This was not chased into COLMAP's C++ source to find the
exact unseeded RNG call site — the leading hypothesis is the RANSAC-based
geometric verification step inside feature matching, a known category of
issue in SfM tools where a global random-seed flag does not always reach
every RNG consumer — but the practical conclusion is unambiguous: **there
is no single "true" registration number for this dataset in this
environment**, and any comparison against it should use the observed range,
not one run treated as ground truth.

That range should itself be read against another range, not a single
number, and this is where the evidence is asymmetric: `galanakis2021`'s
*with-fix* registration was stress-tested honestly, 8 times, and reported
as the 66.67–73.33% range above. Its *without-fix* baseline was not
re-tested in this environment at all — the only number available for it is
a single historical draw from the project's earlier phase (56.67%, 17 of
30 images), never repeated here to see whether it is similarly noisy. Every
run in the with-fix range sits far closer to that phase's own post-fix
number (83.33%) than to its pre-fix number, which is consistent with the
fix still working, but **the honest comparison is one range against one
unreplicated point, not range against range** — a gap worth closing before
this result is presented as a controlled before/after comparison rather
than a directional one. The concrete reconstruction this pipeline trains
on downstream is whatever a single clean rebuild happened to produce (20 of
30 images registered, 66.67%) — a specific, traceable, real input, logged
as a deliberate choice rather than a "representative" run picked after the
fact.

## 3. Splatfacto configuration, verified metrics, and the eval-set ceiling

Splatfacto trains for its default 30,000 iterations, initialized from the
real COLMAP sparse point cloud (7,162 points) rather than random
initialization — confirmed in the training log by the *absence* of
nerfstudio's fallback warning, which does fire when no point cloud is
found. Training on the pinned 20-image reconstruction completes in about
16.5 minutes, ends with zero NaN/Inf/divergence anywhere in the log, and
shows Gaussian count growing from the seed 7,162 points to roughly 520,000
by step 9,200 before settling into a stable 480,000–520,000 equilibrium for
the remaining 21,000 steps (final count 480,560) — the signature of
densification and culling reaching balance, not a runaway or a collapse.
Because the run used the default `--vis viewer`, which disables periodic
eval logging, this Gaussian-count trajectory stands in for a PSNR-over-time
curve that was never actually recorded; a future run wanting one would need
`--vis tensorboard` from the start.

Evaluation uses nerfstudio's built-in PSNR/SSIM/LPIPS computation against
whatever the dataparser's default 90/10 fraction split produces on the
20 registered images — 18 training images, 2 held out for evaluation. On
that split: PSNR 11.76 (±0.16 across the 2 eval images), SSIM 0.6394
(±0.0085), LPIPS 0.5863 (±0.0319), against the project's earlier-phase
reference numbers of 12.36 / 0.60 / 0.54 respectively. Every deviation is
small and none point the same direction — SSIM is actually better here,
PSNR and LPIPS slightly worse — which is the expected shape of noise from
training on a different registered-image subset (this run's 20 of 30 vs.
the reference run's 25 of 30) rather than evidence of a broken
reconstruction; none of the concrete red flags that would indicate an
actual problem (a crashed or unloadable checkpoint, divergent loss, a
collapsing or runaway Gaussian count, metrics an order of magnitude off)
were observed.

The 2-image eval set, however, is too small to trust as a precise
benchmark number, and an explicit attempt was made to fix that with a
genuinely larger, seed-randomized held-out set — not by inventing a
mechanism, but by using nerfstudio's other supported split mode
(`--eval-mode filename`, since the default fraction-based split turned out
to have no randomness to seed at all: it is a deterministic strided pick).
Three seeded 16-train/4-eval runs and one 17-train/3-eval boundary probe
were attempted; **all four crashed**, identically, with a CUDA
out-of-memory error inside Splatfacto's SSIM loss computation, on every
run with Gaussian count still climbing past 1.2 million — roughly 2.5
times the stable 18-train run's plateau — at the moment of the crash. A
follow-up isolated rerun of the 17-train boundary case, under continuous
supervision with the GPU confirmed idle beforehand and VRAM polled live
throughout, reproduced the same failure at step 8,720 of 30,000, with a
checkpoint saved shortly before the crash independently confirming
1,195,982 Gaussians and still growing. **The boundary is precise: 18
training images trains stably on this GPU; 17 does not.** No amount of
allocator tuning was tested as a mitigation (an untested, not
ruled-out lead), but every crash showed Gaussian count still rising, not
plateaued, at the point of failure, which argues against allocator
headroom being a full fix rather than a delay of the same crash.

The most plausible mechanism offered for this boundary — explicitly
flagged in the source document as a plausible explanation, not a verified
root cause, since it was not chased into a per-region gradient or
visibility diagnosis — is vanilla 3D Gaussian Splatting's known sparse-view
failure mode in adaptive density control: gradient-driven splitting and
pruning are meant to reach an equilibrium, but when multi-view constraint
on some region of the scene is too thin, splitting can proceed without
matching pruning pressure, so densification never settles and instead
grows without bound. Seventeen training images is, on this read, already a
sparse-view regime for this particular scene. Practically, this means the
2-image eval set is not a shortfall this pipeline can currently fix by
simply asking for a larger one on this dataset: **20 total registered
images cannot support both an 18-image (or more) training set and a
meaningfully larger held-out set on this 8 GB GPU** — the real fix is more
source photographs or more VRAM, not a different split ratio on the
current 20.

## 4. Post-training cleanup

Splatfacto's training-time culling (`cull_alpha_thresh`, `cull_scale_thresh`,
active throughout training via gsplat's default density-control strategy)
already removes low-opacity and oversized Gaussians as training proceeds,
but the final checkpoint can still contain a residue that drifted past
those same thresholds after the last refinement pass before training
stopped at step 30,000. Rather than assume this residue's size or pick a
threshold from generic 3DGS convention, the actual checkpoint's activated
opacity and scale distributions were inspected directly (opacities and
scales are stored unactivated — as logits and log-scales respectively —
confirmed against this environment's nerfstudio source, so all analysis
was done in sigmoid/exp-activated space). That inspection found 5.115% of
Gaussians (24,580 of 480,560) below the checkpoint's own training-config
opacity-cull threshold of 0.1, and 0.408% (1,962) above its own
scale-cull threshold of 0.5, with the scale distribution in particular
showing a severe heavy tail (p99.9 at 0.837, true maximum at 55.29 — a
roughly 66-fold jump in the top 0.1%). A pruning pass using exactly those
two threshold values — the checkpoint's own training-time criteria applied
once more, not new constants — removed 26,476 Gaussians (5.509%), leaving
454,084.

Re-evaluating on the identical 18/2 split, every metric moved by less than
its own per-image noise: PSNR 11.76 → 12.05 (a nominal +2.4%, smaller than
the post-pruning run's own ±0.27 standard deviation at n=2), SSIM 0.6394 →
0.6380 (−0.2%), LPIPS 0.5863 → 0.5891 (+0.5%). Rendered before/after images
at the same eval viewpoint are visually near-identical. A raw pixel
difference on the rendered half of those images (the ground-truth half
confirmed byte-identical between the two evaluation runs) shows a real,
non-zero, localized change — up to 15% of pixels shifting by more than
5/255 in one of the two eval views — indicating the pruned Gaussians were
genuinely rendering something, somewhere, just not enough in these
particular two held-out camera views to move whole-image metrics past the
eval set's own noise floor. **This is reported as a legitimate small
result, not inflated into a larger one**: a real, verified 5.5% reduction
in Gaussian count at no measurable cost to reconstruction quality on this
scene, consistent with the reconstruction's actual quality ceiling being
set by the 18-image training-set size (Section 3) rather than by leftover
floater or noise geometry — cleanup cannot fix an undertrained
reconstruction, and did not need to fix a large floater problem here
because Splatfacto's own training-time culling had already done most of
that work.

## 5. Second-scene validation and the macro-capture failure mode

Every result above is specific to one scene. To test whether it
generalizes, the same pinned EXIF-fix-through-COLMAP sequence was run,
unmodified, on a second, independent scene (`th_0085`, 24 images, from the
publicly available Fictional Forensic Scene dataset). It does not
generalize, for a reason that was diagnosed rather than merely observed.
Across 5 independent full-pipeline reruns, registration collapsed to
2–7 of 24 images (8.33%–29.17%) — not simply a lower number in the same
kind of noisy-but-workable range documented in Section 2, but a
qualitatively different failure. Querying the verified two-view feature
match graph directly (rather than reasoning from registration counts
alone) showed why: of 276 candidate image pairs, only 71 had any verified
matches at all, and those 71 split the 24 images into one 18-image
connected component plus two fully isolated 3-image clusters that share
zero matches with the rest of the set or with each other. Visual
inspection of the isolated clusters confirmed they are tight macro
close-ups of individual evidence items (a photographed pistol next to its
evidence marker, with no room background in frame at all) — photographs
that, by construction, do not depict any of the same 3D scene structure as
the wide establishing shots or as each other's neighbors. A filtered rerun
using only the 18-image connected component (two reruns, deliberately not
pursued further once the direction was clear) reached 4/18 and 6/18
(22.22% and 33.33%) — better than the unfiltered low end, but still far
below the first scene's range, and the images that did register in both
filtered runs were consistently the same dozen or so strongly-matched wide
shots, showing that even the "connected" remainder of this scene's photo
set lacks the consistent neighbor-to-neighbor overlap the first scene's
capture protocol provided.

No configuration value was changed to try to improve this outcome, and no
Splatfacto training was attempted on it: registration never crossed a
reasonable floor for a reconstruction worth training 30,000 iterations
against, and doing so anyway would have produced a metrics table without a
real result behind it. **This is framed deliberately as a capture-protocol
constraint of the method, not a defect in the pipeline's implementation.**
Structure-from-motion needs consistent multi-view overlap between nearby
photographs; a forensic-documentation convention of walking to each item
of evidence and photographing it in isolated close-up, with only occasional
wide shots, does not reliably provide that, regardless of how the COLMAP
or Splatfacto stages are configured. The practical implication for any
future capture session intended to feed this pipeline is a capture-protocol
requirement — a roughly continuous walkthrough with strong frame-to-frame
overlap — not a pipeline change.

## 6. Failure modes within a successful reconstruction

The findings above describe whether a scene reconstructs at all, or how
good the reconstruction is in aggregate. A separate pass looked at *where*,
within the one reconstruction that did succeed (the post-cleanup
`galanakis2021` checkpoint), quality actually breaks down — rendering all
20 of the checkpoint's registered camera views, not only the two fixed
evaluation views used to measure aggregate metrics. Two distinct,
image-verified localized failures were found, each checked against the
real photograph at the same camera pose rather than judged by eye alone.
The first is a recurring band of rainbow-colored chromatic noise at the
outer edges of the rendered frame, present in 5 of the 7 training views
inspected and absent from every corresponding photograph; the most
plausible explanation offered, explicitly flagged as unverified, is that
Gaussians near the periphery of any given camera's field of view are
constrained by fewer overlapping rays from neighboring cameras than
Gaussians nearer the frame center, since neighboring frustums tend to
overlap most strongly toward their shared middle. The second is a single
floating, geometrically incoherent blob in one specific frame — the first
registered image immediately following a real, documented 5-image
registration gap — where the rest of that same frame reconstructs
cleanly; the most plausible explanation, again flagged as unverified, is
locally sparse multi-view support immediately after a genuine break in
capture coverage. Both explanations are offered as the most plausible
reading of where each artifact sits, not as confirmed diagnoses — neither
was checked against an actual per-pixel or per-Gaussian coverage
computation.

Two other categories commonly flagged in the Gaussian Splatting literature
— reflective or glossy surfaces, and thin small-scale detail such as the
evidence markers and blood-spatter sheets that matter most for this
project's actual forensic use case — were inspected with equal care and,
honestly, showed no distinct localized problem beyond the reconstruction's
general softness. The scene has no strongly specular surfaces to trigger
the sharper view-dependent failures that category usually produces, and
the flat evidence markers and spatter sheets sit on the floor well inside
the region the camera path walked closely around, giving them strong
multi-view constraint — the geometric opposite of the sparse-coverage
situation behind the floating-blob finding. This negative result is
reported as such, not treated as an inspection gap. Separately, the two
held-out evaluation views were re-rendered and re-inspected as part of
this same pass and confirmed to show the same haze already quantified in
Section 3 and Section 4 — noted explicitly here so it is not
double-counted as a new, distinct finding.

## 7. What this pipeline does not yet do

To keep scope unambiguous for a reader: this pipeline, as built and tested
through Task 7, reconstructs scene *appearance and rough geometry* as a 3D
Gaussian Splat, and nothing more. It carries **no calibrated dimensional
accuracy** — no scale bar, ground-control point, or other metric reference
was introduced anywhere in the capture, COLMAP, or Splatfacto stages
documented above, so no claim about real-world measurements (distances
between evidence items, object sizes) can currently be made from a
reconstruction this pipeline produces; COLMAP's recovered scale is
arbitrary unless separately calibrated, and no such calibration step
exists in any pinned command in this document. It has **no language-based
querying or retrieval** — nothing in Tasks 0–7 adds semantic features,
CLIP embeddings, or any mechanism for asking a reconstruction a question
in natural language; the output of this pipeline is a checkpoint renderable
from arbitrary viewpoints, not a queryable scene representation. And it
has been **verified end-to-end on exactly one successfully-reconstructed
scene** (`galanakis2021`); the second scene attempted (`th_0085`) is
documented as a real, diagnosed negative result at the COLMAP stage
(Section 5), not a second successful validation, so every quantitative
claim about reconstruction quality, cleanup effect, or localized failure
behavior in this document should be read as characterizing this method on
one scene, with a second scene's worth of evidence only about where the
method's registration stage stops working — not about how a second
*successful* reconstruction would behave downstream.

---
## Update appended 2026-11-08 ~00:40 SGT (append-only; full picture in pipelines/image/eval/results/CONTEXT_LOSSLESS.md)
Later evaluation (eval/results/) bears on sections 2 and 7:
* COLMAP 4.2.1 registers more of galanakis2021 through its structure-less fallback. Its run-to-run split comes from that fallback's
  unseeded RANSAC (eval/results/eth3d/e3/seedtest/RESULT.md).
* On ETH3D sparse subsets, fallback-only images are much more often grossly mis-posed (eval/results/eth3d/RESULTS_v9.md /
  RESULTS_v10.md).
* Landmark distances on galanakis2021 core cameras: magazine width -0.15 %, lip -7.3 %, shoe +1.2 % post hoc
  (eval/results/landmarks/analysis/accuracy_section.tex).
* This text is not revised; see CONTEXT_LOSSLESS.md.
