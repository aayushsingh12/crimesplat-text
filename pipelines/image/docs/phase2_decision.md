# Phase 2 decision log — language-queryable layer over the `galanakis2021` checkpoint

Running log, same style as `p1_decision.md`: written as work happened, not
reconstructed after the fact. Goal: type a text query (e.g. "blood
spatter") and get back a rendered view of the Phase 1 checkpoint with the
matching region marked. Deliberately the lightweight SAM-mask + CLIP-crop
+ sparse-point-projection approach, not per-Gaussian language features —
scoped to actually finish in time.

Does not touch COLMAP, does not retrain Splatfacto, does not modify the
pinned Phase 1 pipeline or its docs. Uses only the existing checkpoint
(`outputs/colmap_pruned/splatfacto/2026-08-24_010039/`, Task 5's pruned
454,084-Gaussian model) and the existing pinned COLMAP reconstruction for
`galanakis2021`.

## Environment: two conda envs, on purpose

**Checked first, before installing anything, per this task's own stop
condition.** A dry-run dependency resolution
(`pip install --dry-run segment-anything open_clip_torch`) against the live
`crime-image` env showed:

- **No conflict on torch/torchvision/CUDA itself** — both packages resolve
  cleanly against the pinned `torch==2.11.0+cu128` /
  `torchvision==0.26.0+cu128`; pip reports them "already satisfied."
- **One real conflict**: `open_clip_torch` requires `timm>=1.0.17`, but
  `environment.yml` pins `timm==0.6.7` and `nerfstudio` itself lists `timm`
  as a direct dependency. Installing `open_clip_torch` into `crime-image`
  as resolved would silently bump `timm` 0.6.7 → 1.0.29 — a major-version
  jump on a dependency of the working Phase 1 pipeline. (A
  `grep -rl "timm"` over the installed nerfstudio source found no actual
  `import timm` anywhere in this version, so the live runtime risk looked
  low — but it's still an unreviewed side-effect on a pinned dependency,
  which is exactly the case flagged to stop on rather than decide alone.)

Stopped and asked. Chosen resolution (refined by the user from three
options): **a second, minimal, CPU-only conda env**, `crime-image-tag`,
rather than cloning `crime-image` wholesale (unnecessary — duplicates the
whole CUDA/torch install for no reason) or trying to force everything into
one env. `crime-image-tag` holds only: `torch`/`torchvision` (CPU wheels,
`torch==2.13.0+cpu`), `open_clip_torch`, `segment-anything`,
`opencv-python-headless` (a SAM automatic-mask-generator runtime
dependency, added after the first run hit
`ModuleNotFoundError: No module named 'cv2'` — also conflict-checked via
`pip install --dry-run` first: clean, no pin conflicts). No GPU/CUDA needed
for SAM mask generation or CLIP embedding at this scale.

**The only handoff between the two envs is a JSON file.** `crime-image-tag`
never touches a live nerfstudio object; it reads `transforms.json`,
`dataparser_transforms.json`, and the COLMAP sparse model as plain data,
and writes a region lookup / best-match JSON. `crime-image` (GPU) is used
for exactly one thing: loading the trained checkpoint and rendering. If
this two-env split looks like a mystery later, this is why.

## Step 1–4: SAM masks → CLIP embeddings → 3D localization → lookup file

Script: `pipelines/image/scripts/tag_regions.py` (runs in
`crime-image-tag`).

**SAM**: `segment-anything`'s ViT-B checkpoint
(`sam_vit_b_01ec64.pth`, 358 MB, smallest official SAM checkpoint —
downloaded from Meta's public bucket, not committed, gitignored under
`pipelines/image/models/`), run via `SamAutomaticMaskGenerator` with
`points_per_side=16` (half the default 32, for CPU speed) on each
registered training photo resized to a 1024px long side (also for CPU
speed — full 4032×3024 originals would be much slower per image on CPU).
Masks smaller than 0.5% or larger than 50% of the image area are dropped
(noise / whole-wall-or-floor background, respectively).

**CLIP**: `open_clip`'s `ViT-B-32-quickgelu` / `openai` pretrained weights
— note the `-quickgelu` suffix. The first run used plain `ViT-B-32` and
`open_clip` warned `QuickGELU mismatch between final model config
(quick_gelu=False) and pretrained tag 'openai' (quick_gelu=True)` — i.e.
the model's activation function didn't actually match what the OpenAI
weights were trained with, which would silently degrade every embedding.
Fixed before running for real by switching to the `-quickgelu` variant,
which `open_clip`'s own docs recommend specifically for the original
OpenAI checkpoints. Each kept mask's bounding-box crop (padded 4px) is
embedded and L2-normalized.

**3D localization — the actual design decision, not the literal
letter of "project into 3D using camera poses/intrinsics"**: a single 2D
mask centroid can't be projected to a 3D point without a depth value, and
this pipeline has no depth maps. Rather than re-deriving depth (e.g. a
monocular depth model — more moving parts, another dependency to
conflict-check, out of scope for "lightweight"), each mask is localized
using **COLMAP's own SIFT-track correspondences**: `sparse_txt/images.txt`
already stores, for every registered image, the exact 2D pixel location of
every keypoint that got triangulated into a 3D point (`points3D.txt`) —
these correspondences were themselves computed from that image's camera
pose and intrinsics during COLMAP's bundle adjustment. For each kept SAM
mask, every one of that image's tracked keypoints whose pixel falls inside
the mask is looked up, and the mask's 3D location is the mean of those
keypoints' triangulated `points3D.txt` positions. Masks with zero tracked
keypoints inside them are skipped — no depth evidence, no location, no
entry (flagged as "can't be localized," not guessed at). This *reuses* the
pinned camera parameters (COLMAP already used them to build the
correspondence) rather than re-deriving the same projection with fresh
risk of a sign/axis-convention bug — read literally as "reuse ... don't
recompute."

Practical effect: regions on flat, richly-textured, well-covered surfaces
(the ones SIFT tracks well) get localized; regions on blank, low-texture,
or single-view-only surfaces don't. This is a real, expected limitation of
a SIFT-sparse-point-based localization method, not a bug — noted here so
it isn't a surprise later.

**Coordinate space**: COLMAP's raw 3D points (`points3D.txt`, and the
`sparse_pc.ply` nerfstudio's dataparser reads) live in the pre-training
"raw COLMAP" coordinate frame. The trained checkpoint's Gaussians live in
a different, further-transformed frame — nerfstudio's
`NerfstudioDataParser` composes `transforms.json`'s `applied_transform`
with an auto-orientation/centering transform and a scene-scale factor,
saving the composed result to
`outputs/colmap_pruned/splatfacto/2026-08-24_010039/dataparser_transforms.json`
(`"transform"`: 3×4, `"scale"`: scalar) at train time. Read directly from
nerfstudio's own source
(`nerfstudio_dataparser.py`'s `_load_3D_points`) to get the exact formula
rather than guessing at it:

```
point_final = ([point_raw, 1] @ transform.T) * scale
```

— applied to every region's averaged raw 3D point using this checkpoint's
own saved `dataparser_transforms.json`, so points land in exactly the
coordinate space the checkpoint's Gaussians were trained in, no
approximation.

**Sanity-checked before scaling up**, per this task's stop condition: a
2-image pilot run's region points landed in a tight cluster (mean
≈ `(-0.37, -0.08, -0.38)`) well inside the checkpoint's actual Gaussian
bounding volume (min `(-9.3, -9.8, -12.5)`, max `(13.6, 10.2, 13.3)`, mean
`(-0.57, -0.36, -0.29)` — read directly off `gauss_params.means` in the
checkpoint). Close to the Gaussian cloud's mean, nowhere degenerate (not
all-zero, not identical duplicate points, not thousands of units away) —
passed, proceeded to the full run.

**Full run**: all 20 registered images, ~12s SAM mask generation per image
on CPU (~4 minutes total). **314 localized+embedded region records**
written to `pipelines/image/query/region_lookup.json` (gitignored — a
derived artifact, regenerable from the pinned checkpoint + COLMAP model,
not project source). Per-image kept-region counts ranged from 2
(`IMG_0484.jpg`) to 25 (`IMG_0462.jpg`) — images with less texture/more
uniform surfaces in frame produced fewer localizable regions, consistent
with the SIFT-track-coverage limitation above.

## Step 5: query time

Text side — `pipelines/image/scripts/query_regions.py` (runs in
`crime-image-tag`): encodes the query string with the same
`ViT-B-32-quickgelu`/`openai` CLIP text tower, cosine-similarity against
all 314 stored (already-normalized) embeddings, prints the top-k, saves
the single best match to `pipelines/image/query/last_match.json` — this
JSON file is the entire handoff to the GPU env.

Render side — `pipelines/image/scripts/render_query.py` (runs in
`crime-image`, the sole GPU step): same `weights_only=False` checkpoint
patch as `eval_checkpoint.py`/`render_checkpoint.py`. Loads the pipeline
via nerfstudio's `eval_setup(..., test_mode="test")` (loads train+eval
datasets, giving access to every registered camera's exact final pose —
reused directly rather than re-deriving the pose transform a second time,
same "reuse, don't recompute" reasoning as the localization step). Finds
the camera belonging to the best match's source image (matched by bare
filename — the loaded dataset points at a `images_4/` auto-downscaled
sibling folder, not the `images/` path `transforms.json` uses; caught this
via a "camera not found" error on the first attempt and fixed the lookup
to match on filename tail only), renders it with
`pipeline.model.get_outputs_for_camera`, then projects the match's 3D
point into that same camera (using its known `fx,fy,cx,cy` + pose,
ignoring radial distortion — fine for a visual marker, not a metric
measurement) and draws a red crosshair/circle at the resulting pixel.

## First working end-to-end query — STOPPED here per this task's checkpoint

**Query: `"blood spatter"`** (top match, similarity 0.3226, out of 314
candidates — `IMG_0463.jpg` / `images/frame_00007.jpg`, 22 supporting
SIFT-tracked 3D points). Rendered output:
`pipelines/image/query/last_result.jpg`.

The marker lands on a white card with a reddish handprint stain, one of
several evidence cards with blood-like markings scattered across the
floor in this scene — a plausible, on-topic match for "blood spatter,"
not a degenerate or nonsensical one. Render quality at this camera is
consistent with the rest of the checkpoint (same general softness
documented in `cleanup.md`/`failure_modes.md`, nothing new).

Per this task's explicit instruction, stopping here — not running further
queries, not building a UI, not polishing the marker rendering or
similarity threshold — until reviewed.

## What's still open / not yet decided

- **Only one query has been tried.** Whether "blood spatter" landing on a
  plausible card generalizes to other queries (e.g. more specific object
  names, or queries with no good match in this scene) is untested.
- **No similarity threshold / "no match" handling yet** — the script
  always returns a top-1 best match regardless of how weak the cosine
  similarity is (0.32 here is a moderate score, not a strong one by
  typical CLIP zero-shot standards). A real query UI would need some
  notion of "this scene doesn't contain that."
- **Sparse-point localization coverage is uneven across the scene**
  (2–25 kept regions per image) — regions on low-texture surfaces are
  systematically underrepresented in the lookup, not because they're
  unimportant but because SIFT doesn't track them. Not fixed here (would
  need a depth model or denser matching), just documented as a known gap.
- **The `-quickgelu` fix and the SIFT-track localization choice were both
  caught/decided during this session**, not pre-planned — worth
  double-checking against a second query or two before trusting the
  lookup for anything beyond this one proof-of-concept result.
- **No-match test result, directly testing the threshold gap above**: ran
  one deliberately absent-object query, `"a car"` (nothing car-like exists
  in this scene), and compared its top-1 similarity against "blood
  spatter"'s:

  | Query | Top-1 similarity | Supporting SIFT points |
  |---|---|---|
  | "blood spatter" (real object in scene) | 0.3226 | 22 |
  | "a car" (absent from scene) | 0.2592 | 1 |

  Plainly: **similarity score alone does not reliably separate real
  matches from absent-object queries in this scene** — 0.2592 and 0.3226
  both sit in the same moderate CLIP-similarity band, not the wide
  separation a safe fixed threshold would need. This is consistent with
  known CLIP zero-shot score compression (raw cosine similarities cluster
  into a narrow range regardless of match quality).

  The supporting-SIFT-point count (22 vs. 1) separates these two cases far
  more cleanly than similarity does — a **promising but untested**
  secondary signal for a future threshold. Not implemented; only observed
  on this single comparison.

  **Plainly: the current system should not be demonstrated as an open,
  type-anything interface without this caveat** — as it stands, it will
  confidently mark a wrong answer for a query about something that isn't
  in the scene, with nothing in the output to distinguish that from a real
  match.

## Encoding coverage: 20/30 images are 3D-queryable, 10/30 are 2D-only

Confirmed by cross-referencing `galanakis2021`'s full 30-image list
against COLMAP's registered set (`colmap/sparse_txt/images.txt`): the 10
images missing from `region_lookup.json` — `IMG_0466`, `IMG_0467`,
`IMG_0468`, `IMG_0471`, `IMG_0472`, `IMG_0473`, `IMG_0474`, `IMG_0475`,
`IMG_0482`, `IMG_0483` — are exactly the 10 images COLMAP never
registered, the same registration ceiling already documented in
`colmap_config.md`/Task 3. Not a missed tagging step: with no recovered
camera pose, `tag_regions.py`'s 3D localization method (COLMAP's own
SIFT-track 2D↔3D correspondences) has no pose or depth data to work from
for these 10, so it correctly has nothing to place in 3D for them.

These 10 have since been given **2D-only encoding coverage** — SAM masks
+ CLIP embeddings, no 3D point — via a separate script
(`tag_regions_2d_only.py`, reusing `tag_regions.py`'s masker/CLIP builders
unmodified) writing a **separate** file, `region_lookup_2d_only.json` (154
regions). This is deliberately never merged into `region_lookup.json` and
never read by `query_regions.py`: a region with no 3D point must not be
matchable by a query. So, plainly: **20/30 `galanakis2021` images are
3D-queryable (COLMAP-registered); 10/30 have 2D-only coverage encoding and
cannot be localized or queried in 3D** — visible, not query-eligible.
`encoding_coverage.png` shows all 30, with the 10 2D-only ones visually
distinguished (desaturated, orange border, explicit caption) so the two
coverage levels are never confused at a glance.

## Revision: query_regions.py now searches the 2D-only regions too, honestly

**This ties directly to Task 3's registration finding** (`colmap_config.md`
documents the 66.67–73.33% registration range on this dataset; the 10
2D-only images above are exactly that ceiling's leftover 10 images) — not
a new, separate issue, the same one showing up again at the query layer.

The paragraph above said `region_lookup_2d_only.json` is "never read by
`query_regions.py`." That was correct for keeping 2D-only regions out of
the 3D scene (still true — they have no 3D point and never will), but on
reflection it had a real cost: it meant a query whose true best
conceptual match was one of these 10 images' actual content (e.g. "drug
paraphernalia" — genuinely depicted in `IMG_0468.jpg`, one of the 10) got
silently answered from the remaining 314 3D-localized regions instead,
with no indication anything was missing. Silently dropping real evidence
content is worse than acknowledging the constraint.

`query_regions.py` now optionally takes `--lookup-2d-only` and ranks
**both pools together** — a single combined similarity ranking, not two
separate searches. If a 2D-only region's embedding is genuinely the
closest match to the query, it wins the #1 slot rather than being
excluded from ranking at all. But its match is reported honestly, not
rendered as a real location: `localized: false`, `point3d_final: null`,
and an explicit message — *"Found in photo evidence, but this image was
not part of the 3D reconstruction and cannot be located in the scene."*
`render_query.py` checks this flag first and exits cleanly with that same
message rather than crashing on a missing 3D point or frame path.

Verified: `"blood spatter"` still returns the identical top-1 result
(sim 0.3226, `IMG_0463.jpg`) with the 2D-only pool included — the combined
ranking doesn't change existing behavior when a 3D-localized region is
genuinely the best match. `"drug paraphernalia"` returns a 2D-only top-1
(sim 0.2732, `IMG_0468.jpg`), and both `query_regions.py`'s printed output
and its `--out-match` JSON, and `render_query.py`'s handling of that JSON,
were checked directly (not assumed) to confirm the honest-failure path
actually runs rather than crashing.

Out of scope, left as-is: `app.py`'s `run_query()` is a static
pre-computed lookup (`QUERY_RESULTS`), not a live call into
`query_regions.py` — confirmed by inspection before making any of the
above changes — so this revision has no effect on the demo UI one way or
the other.
