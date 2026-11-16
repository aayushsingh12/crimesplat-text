# Second-scene validation — FFS `th_0085` (Task 6)

Validates the pinned pipeline (`colmap_config.md` → `splatfacto_config.md` →
`cleanup.md`) against a second, independent scene, to find out whether Task
3–5's results generalize or were specific to `galanakis2021`. **Headline
result: they don't generalize to this scene, for a real, diagnosable reason
— this scene's capture protocol doesn't provide the multi-view overlap
structure-from-motion needs, not something the pinned pipeline did wrong or
could be tuned around.** No Splatfacto training or cleanup pass was run —
COLMAP registration never reached a level worth building a checkpoint on
(see "Decision: stop before Splatfacto" below).

**Time-boxed under real presentation-deadline pressure.** The COLMAP
reproducibility check below is a **lighter-touch check than Task 3's**: 5
independent full-pipeline reruns plus 2 more on a filtered image set, not
Task 3's 8-run characterization. Stated here explicitly so this isn't later
read as Task-3-level proof — it's a directional read, and for this scene the
direction was unambiguous well before 8 runs would have been reached.

## Dataset

**Source**: Fictional Forensic Scene (FFS) dataset, Zenodo, CC BY-NC-SA 4.0
— identified in earlier scoping, pulled here for the first time. Checked
the actual record listing before downloading anything (not guessed from the
DOI in the task brief, which pointed at Part 2 / 17164106 — that record
alone is a single 42.3 GB zip). The dataset is split across 5 parts by
Zenodo record, sizes checked live via the API:

| Part | Record | Scenes | Zip size |
|---|---|---|---|
| 1 | 18623173 | th_0001–0020 | 44.55 GB |
| 2 | 17164106 (task brief's DOI) | th_0021–0040 | 42.26 GB |
| 3 | 18623134 | th_0041–0060 | 40.13 GB |
| 4 | 18622559 | th_0061–0080 | 47.45 GB |
| 5 | 18623225 | th_0081–0100 | **18.75 GB** |

**Part 5 (18623225) is the smallest package** — picked per the task's
"pull the smallest available package if multiple exist" instruction. Disk
check first: 62 GB free at the time (`df -h`), so even the smallest full
package left little headroom once extracted, and this is a single-scene
validation, not bulk ingestion anyway.

**Downloaded only one scene's images, not the package.** Zenodo's file host
supports HTTP range requests (confirmed directly: a `Range: bytes=0-100`
request returns `206 Partial Content`) and the `remotezip` Python package
reads a remote zip's central directory and streams out individual entries
without fetching the rest — used to list every scene's `img/` folder inside
the 18.75 GB zip (sizes ranged 18–133 MB per scene across the 19 available
scenes) and pull only one, **`th_0085`** (24 JPEGs, ~64 MB total,
`4160x3120`/`3120x4160`), directly to
`pipelines/image/data/th_0085/photos/`. Total transferred: listing metadata
plus ~64 MB of image bytes — nowhere near the 18.75 GB package.

**Content warning acknowledged, not dwelt on**: the dataset's own
description flags realistic mannequins that can resemble real crime-scene
bodies. `th_0085` contains one (a mannequin posed on the floor by a chair,
visible in the wide shots below) — noted here as the task asked, handled the
same as any other forensic-photography content in this pipeline, nothing
further to add.

## Step 1 — EXIF orientation fix

Ran unchanged, per `colmap_config.md`:

```
python pipelines/image/scripts/fix_exif_orientation.py \
    pipelines/image/data/th_0085/photos \
    pipelines/image/data/th_0085/photos_corrected
```

**Real finding, scene-specific**: 0 of 24 images needed rotation (none
carried an unbaked EXIF `Orientation` tag) — unlike `galanakis2021`'s 3/30.
Not a pipeline issue; just a different camera/shooting-app behavior on
whatever device captured this scene. The script still ran and still
produced a `photos_corrected/` directory with 0 residual `Orientation` tags,
confirming it's a correct no-op here, not a silent skip.

## Step 2 — COLMAP, unfiltered, 5 independent full-pipeline reruns

Exact same pinned command sequence as `colmap_config.md` — CPU SIFT,
`--ImageReader.single_camera 0`, `--SiftExtraction.num_threads 4`,
`--SiftMatching.num_threads 4`, `--Mapper.num_threads 1`, exhaustive
matching (24 images → 276 pairs, still small enough) — each rerun a full
clean rebuild (`database.db` and `sparse/` deleted first), not a cached-DB
reuse.

| Run | Registered / 24 | % |
|---|---|---|
| 1 | 7 | 29.17% |
| 2 | 2 | 8.33% |
| 3 | 2 | 8.33% |
| 4 | 4 | 16.67% |
| 5 | 6 | 25.00% |

**Range: 2–7/24 (8.33%–29.17%).** This is not the same shape of finding as
Task 3's 20–22/30 range on `galanakis2021`: there, every run registered
roughly two-thirds of the set and the variance was run-to-run RANSAC noise
inside an otherwise well-connected match graph. Here, **most of the set
never had a chance to register, in any run** — confirmed by looking at
*why*, not just accepting the numbers.

## Step 3 — Why: the match graph itself is disconnected, not just noisy

Queried `run1`'s `database.db` directly (`two_view_geometries` table) rather
than inferring from registration counts alone. Of 276 candidate pairs, only
**71 passed geometric verification with any inliers at all** — the rest are
hard zeros, not weak-but-nonzero matches. Connected-components over those 71
verified pairs (union-find, computed directly, not eyeballed):

| Component | Size | Images |
|---|---|---|
| Main | **18** | `121028, 121103, 121109, 121115, 121141, 121144, 121151, 121200, 121207, 121214, 121220, 121226, 121233, 121240, 121247, 121250, 121254, 121302` |
| Isolated cluster A | 3 | `121033, 121038, 121045` |
| Isolated cluster B | 3 | `121050, 121056, 121121` |

(Filenames abbreviated to their `HHMMSS` timestamp suffix;
`IMG_20250526_<time>.jpg`.)

**Visually confirmed what these clusters are**: `IMG_..._121028.jpg` (in
the isolated cluster A) is a tight macro shot of a single evidence
item (a pistol next to marker `#13`) with no room background at all;
`IMG_..._121200.jpg` and `..._121302.jpg` (both in the 18-image main
component) are wide establishing shots of the whole room, showing a posed
mannequin and a spread of numbered evidence markers, bags, and shoes across
the floor. The two isolated 3-image clusters are each a short macro
sequence photographing one evidence item from a few closely-spaced close-up
angles — genuinely well-matched *to each other* (up to 72 inlier matches
within a cluster) but sharing **zero** verified matches with the room-wide
shots or with the other macro cluster, because a close-up of one small
object simply doesn't depict any of the same 3D scene structure as a
wide room shot or a close-up of a different object.

Even inside the 18-image main component, most pairwise matches are weak —
only about a dozen pairs exceed 100 inliers (the strongest, 1,459, between
two of the wide shots), and roughly half the component's edges are under 20
inliers, near the passing threshold rather than comfortably above it. This
is consistent with a documentation-photography convention (walk to each
piece of evidence, take a few close/medium shots of it, occasionally step
back for a wide shot) rather than `galanakis2021`'s apparent
walk-around-the-room-at-roughly-constant-radius convention that gives every
consecutive frame strong overlap with its neighbors.

## Step 4 — Filtered rerun: does removing the isolated clusters fix it?

Built a filtered image set — the 18-image main component only, the two
isolated 3-image macro clusters (6 images total) excluded —
`pipelines/image/data/th_0085_filtered/photos_corrected/`. Ran the same
pinned COLMAP sequence twice (2 reruns, not more — time-boxed per this
task's explicit instruction to stop here regardless of outcome):

| Run | Registered / 18 | % |
|---|---|---|
| 1 | 4 | 22.22% |
| 2 | 6 | 33.33% |

**Filtering helped a little (22–33% vs. the unfiltered range's low end) but
did not come close to restoring anything like `galanakis2021`'s 66.67–73.33%
range.** Inspecting which 4–6 images actually registered in the filtered
runs: both runs' registered sets are subsets of the dozen or so
strongest-matched wide-shot pairs identified in Step 3 (e.g. run 2:
`121200, 121207, 121233, 121247, 121250, 121254`) — exactly the images with
>80-inlier mutual matches. The rest of the 18-image "component" is
technically connected (nonzero matches exist) but too weakly for COLMAP's
incremental mapper to reliably extend registration into it, run to run.

**This rules out "a few contaminating macro shots" as the whole story.**
The disconnection Step 3 found is real and does explain the two 3-image
clusters being unregistered — but the deeper issue is that even the
"room documentation" images among the 18 don't have `galanakis2021`-grade
mutual overlap. Both effects point the same direction: this scene's photo
set, taken as a forensic-documentation sequence rather than a
reconstruction-oriented walkthrough, doesn't provide enough consistent
multi-view coverage for COLMAP to chain together.

## Decision: stop before Splatfacto

Per this task's explicit floor (~40% registered as the minimum worth
building a reconstruction on): **no run, filtered or unfiltered, crossed
it** — best case was 7/24 (29.17%) unfiltered, 6/18 (33.33%) filtered.
**No Splatfacto training and no cleanup pass were run on `th_0085`.** A
sparse point cloud from 4–7 images and the near-empty `transforms.json`
that would come with it isn't a reconstruction worth training 30,000
Splatfacto iterations against, and doing so anyway would produce a number
to put on a slide without a real result behind it — exactly what this
project's standing rule (report real output, not a manufactured-looking
one) says not to do.

**This is the honest validation outcome, not a gap in this task.** The
pinned pipeline's job at the COLMAP stage is to attempt registration and
report what it finds; it did that correctly on `th_0085`, five times
unfiltered and twice filtered, and what it found — consistently, via two
independent lines of evidence (raw registration counts and the match-graph
connectivity behind them) — is that this scene doesn't have the input
structure the method needs. That is itself the validation result.

## Reading this against Task 3/4/5: what generalizes and what doesn't

- **What generalizes**: the EXIF-fix step ran correctly (and correctly did
  nothing, since it wasn't needed here); the COLMAP command sequence,
  unmodified, produced a real, inspectable reconstruction attempt with
  real per-pair match data to diagnose, not a crash or a silent failure;
  registration count is *not* a fixed number here either, matching Task 3's
  general finding that this COLMAP build has run-to-run registration
  variance — just at a much lower and more scene-dependent magnitude.
- **What doesn't generalize, and why that's expected, not alarming**:
  `galanakis2021`'s 66.67–73.33% range assumed a capture protocol with
  strong neighbor-to-neighbor overlap; `th_0085`'s forensic-documentation
  capture protocol (item-by-item macro shots plus occasional wide shots)
  doesn't provide that, and no amount of COLMAP flag-tuning changes what's
  in the photographs. **This is a real capture-protocol constraint on the
  pipeline, not a bug in it** — consistent with (and a sharper, more
  extreme version of) Task 4b's finding that this pipeline's downstream
  stages are sensitive to how much genuine multi-view coverage the input
  actually contains.
- **What this means going forward, not chased further here (out of
  scope — this task stops at reporting)**: a scene meant to validate this
  pipeline needs a walkthrough-style capture (many photos from a roughly
  continuous path around the space, consistent neighbor overlap), not a
  forensic-documentation capture (item-by-item macro shots). That's a
  capture-protocol requirement worth stating plainly for anyone recording a
  future scene for this pipeline, not a defect to fix in code.

## What's still open

- **Only one scene tried from this dataset.** `th_0085` was picked for a
  manageable image count (24, close to `galanakis2021`'s 30) and because it
  was one of the smallest per-scene downloads in Part 5 — not for its
  capture style, which wasn't knowable before downloading and inspecting
  it. Other FFS scenes may follow a more walkthrough-like protocol and
  register normally; not tested, per this task's explicit stop instruction.
- **No Splatfacto/cleanup run exists for a second scene.** Tasks 4 and 5's
  findings remain validated on `galanakis2021` alone. This task's negative
  result is about COLMAP registration, not about whether Splatfacto/cleanup
  would behave consistently given a properly-registered second scene.
- **5 (unfiltered) + 2 (filtered) reruns is a lighter-touch check than
  Task 3's 8-run characterization**, stated explicitly per this task's
  instruction — the direction (far below `galanakis2021`'s range, in both
  the filtered and unfiltered cases) was unambiguous well within that
  budget, but a tighter range estimate would need more runs.
- Raw data (`pipelines/image/data/th_0085*/`) stays local, same policy as
  every other dataset/output artifact this session — not committed.
