# Web splat viewer (`ui_web/`) — status: Stage 2 confirmed working (real browser, ~61fps, orbit/zoom/pan), preset viewpoints added

New, additive, standalone from `pipelines/image/ui/` (the Streamlit demo +
pre-rendered arc viewer, both untouched and still the working fallback).
Goal: real interactive orbit/zoom/pan of the actual trained
`galanakis2021` splat in a browser, via a static `.ply` export + a
client-side WebGL viewer — no live nerfstudio process (`ns-viewer` is
confirmed dead in this environment, not revisited).

## Stage 1 — export: done, verified

```
conda activate crime-image
python pipelines/image/scripts/export_checkpoint.py gaussian-splat \
  --load-config outputs/colmap_pruned/splatfacto/2026-08-24_010039/config.yml \
  --output-dir pipelines/image/ui_web/export \
  --output-filename splat.ply
```

(`export_checkpoint.py` — same `weights_only=False` patch as every other
checkpoint-loading script tonight; `ns-export` hits the identical known
error unpatched.)

**Result**: `export/splat.ply`, **108 MB**, standard 3DGS ply
(`sh_coeffs` color mode — the default, and the format most WebGL splat
viewers expect), 454,084 vertices — matches the checkpoint's known
Gaussian count exactly. Not committed (gitignored) — regenerable from the
pinned checkpoint with the command above.

**Size flag, as asked**: 108 MB is under the ~300 MB concern threshold,
so not a hard blocker — but it's still a real several-second load over a
typical connection, worth accounting for in a live demo (a "loading…"
state is shown in the viewer for exactly this reason, not decoration).

## Stage 2 — viewer: real rendering confirmed, but a stability blocker stopped further verification here

`index.html` + `vendor/gsplat-1.2.9.es.js` (gsplat, MIT license, pinned
exact version, vendored locally so the page is offline-capable — no CDN
dependency at runtime). Checked what was actually reachable/working
before picking it (`gsplat` npm package resolved and imported cleanly;
confirmed its actual exported API, `PLYLoader`/`Scene`/`Camera`/
`WebGLRenderer`/`OrbitControls`, by reading the built module directly
rather than assuming from memory).

**No browser GUI available to me directly**, so verification used
headless Chrome (`google-chrome --headless=new`), driven via
`puppeteer-core` against the system Chrome install (installed
temporarily for this test only, not part of the repo) so I could read
real page state and pixel data rather than guess:

- **Confirmed real rendering, not blank/broken**: `window.__debug` (a
  small dev-only hook `index.html` exposes) showed the parsed PLY loaded
  exactly **454,084 vertices** into the scene, matching the checkpoint's
  known Gaussian count exactly, at plausible positions near the scene's
  known center. A captured in-loop frame (see "why in-loop" below) showed
  real, structured Gaussian content — not a blank canvas, not a solid
  color, not an error state.
- **A first capture attempt looked blank/white** — traced to a real bug
  in my *test harness*, not the viewer: the canvas has
  `preserveDrawingBuffer: false` (gsplat's default), so calling
  `canvas.toDataURL()` from *outside* the render loop races the browser's
  automatic buffer clear. Fixed by adding a small in-loop capture hook to
  `index.html` (`window.__requestCapture`/`window.__lastCapture`, grabs
  the frame synchronously right after `renderer.render()`) — after that
  fix, captures were real and non-blank.
- **The rendered frame itself is heavily hazy/floater-laden** from the
  viewer's default camera angle — visually consistent with this
  checkpoint's already-documented novel-view haze
  (`failure_modes.md`'s `frame_00029` finding: sparse 18-training-view
  coverage degrades badly from angles that don't match a trained camera
  pose). The default orbit camera doesn't start at any trained pose, so
  this is expected, not a new bug — but it does mean the *default* view
  isn't a flattering first impression; Stage 3 (not started) would need
  to consider starting the camera near a known-good trained viewpoint.
- **Stability blocker, not resolved**: in every headless test run, the
  browser reliably stayed alive and rendering through steady per-frame
  work for a while, but the whole browser process (not just the tab)
  disconnected/crashed reproducibly after roughly **30 seconds of
  continuous rendering** under `--enable-unsafe-swiftshader` (CPU
  software WebGL — the only WebGL2 path that actually initialized in
  this headless sandbox). Real GPU-accelerated headless rendering
  (`--use-gl=angle --use-angle=gl-egl`) was tried first and is `unclear
  if usable here at all: it returned a **null** WebGL2 context
  (`Cannot read properties of null (reading 'createProgram')`) rather
  than working faster — this sandbox's headless Chrome doesn't appear to
  have a working GPU passthrough path for EGL, despite an idle NVIDIA GPU
  being present (`nvidia-smi` showed it idle, 13/8151 MiB used, during
  these tests). So every real render I captured came from the software
  fallback, which is inherently much weaker than what a real user's
  normal (non-headless, GPU-accelerated) Chrome would use.

**What this means, plainly**: the export and the loading/rendering
pipeline are real and working — this is not vaporware, actual scene
content renders. But I could not, in this environment, get a clean,
sustained, multi-minute verification of "orbit/zoom/pan controls work,
performance is acceptable" the way the task asked, because my only
available headless test path crashes after ~30s and I have no way here
to open a normal, real, GPU-accelerated browser window myself to check
directly. One orbit-drag interaction did execute successfully (mouse
events dispatched, a second capture was requested) before that run's
crash arrived shortly after — so control wiring isn't obviously broken —
but I did not get a clean "orbit, see the view actually change, hold
steady" confirmation the way I'd want before calling this done.

**Per this task's own instruction to stop at a real blocker rather than
debug further blind: stopping here.** `pipelines/image/ui/` (Streamlit +
pre-rendered arc viewer) is untouched and remains the confirmed-working
fallback for tonight's demo.

## To actually verify this yourself

```
cd pipelines/image/ui_web
python3 -m http.server 8000
# open http://localhost:8000/ in a normal (non-headless) browser
```

If it holds up under real interactive use in an actual browser, that's
the real answer — the headless-sandbox crash may simply not reproduce
there. If it also struggles in a real browser, that's the genuine signal
the software-rendering instability isn't just a test-harness artifact.

**Update**: the user confirmed Stage 2 working directly in a real browser —
orbit/zoom/pan all work, ~61fps. The headless-sandbox crash documented
above was specific to this environment's forced software (swiftshader)
rendering path and did not reproduce for a real user.

## Preset viewpoints — the 20 real COLMAP camera poses, clickable

Additive on top of the confirmed-working viewer above; the core
renderer/scene/camera/render-loop setup in `index.html` was not touched,
only added to (a new UI panel + click handlers that set
`camera.position`/`camera.rotation` from outside the render loop, the
same way user drag interaction already does via `OrbitControls`).

`pipelines/image/scripts/extract_camera_poses.py` (new) reads the 20
registered COLMAP camera poses via `colmap_model.py`'s reader (imported,
not rewritten) and transforms each into the exact coordinate space
`splat.ply` lives in, reusing `tag_regions.py`'s already-verified
`raw_to_final()` point transform for camera position unmodified. Writes
`camera_poses.json` (20 entries: image filename, position, a row-major
3x3 rotation matrix), gitignored like the other derived query artifacts
— regenerable from the pinned checkpoint + COLMAP model.

### A real bug, found and fixed before trusting any of this

The first version of the orientation transform was wrong — not caught by
eyeballing, caught by verification. Sanity-checking one camera by
rendering from it in the browser showed every preset viewpoint producing
the same "spiky, everything-too-close" artifact the task described as
the exact failure mode this feature exists to fix — on views that should
have been clean (real training-camera poses, not novel angles). That's
the signal to stop and diagnose, not to ship it.

Root cause, found by process of elimination rather than guessing:

1. Projected one of an image's own COLMAP-tracked 3D points through my
   computed extrinsics and compared to COLMAP's own recorded 2D pixel for
   it — matched (positive depth, right pixel neighborhood). This proved
   `qvec_to_rotmat`'s world-to-camera rotation itself was correct.
2. Diffed my computed camera-to-world rotation directly against
   `transforms.json`'s own saved per-frame pose for the same image —
   mismatched in a precise pattern: column 0 exactly right, columns 1 and
   2 exactly negated.
3. That is exactly the standard COLMAP→NeRF camera-convention fix
   (COLMAP's camera-to-world uses the computer-vision convention, Y down
   Z forward; nerfstudio's uses OpenGL/NeRF convention, Y up Z backward —
   every COLMAP→NeRF converter negates the Y and Z columns). A step I'd
   entirely missed — distinct from `applied_transform` (a separate axis
   permutation nerfstudio applies on top) and from the gsplat
   local-forward-convention fix (a third, separate conversion). Three
   different conversions, easy to conflate; I'd only accounted for two.
4. Added the missing `COLMAP_TO_NERF = diag(1, -1, -1)` step and
   re-verified against **nerfstudio's own loaded, trained
   `camera_to_worlds`** for the same image (fetched directly from
   `pipeline.datamanager.train_dataset.cameras`, the actual ground
   truth) — matched to within 4e-6 (float precision), full 3x3 matrix,
   not just position.

Re-rendered all previously-tested preset viewpoints after the fix (8
of the 20, spread across the set): forward-vector-toward-scene-centroid
dot products went from strongly negative (camera facing away from the
scene) to strongly positive (0.55–1.0) for every one. Visually: 2–3 of
the 8 rendered clearly recognizable real scene content (e.g. `IMG_0476`
showed sharp, legible magazine covers on the checkered blanket matching
`encoding_coverage.png`'s known content for that image; `IMG_0463`
clearly showed the blood-marked evidence cards). The remaining views are
non-degenerate (dense real content across the whole frame, camera clearly
inside/near the scene looking at it, nowhere close to the earlier
looking-away pattern) but visually noisier/spikier than the two clean
ones — read as gsplat.js's simpler WebGL rasterizer (no CUDA-grade
depth-sorted alpha compositing the way nerfstudio's own renderer has)
combined with this checkpoint's own already-documented sparse-training
softness (`failure_modes.md`), not a remaining coordinate bug — the
underlying math is independently verified correct by three separate
methods above, not just eyeballed.

### Verified

- Positions match `raw_to_final()`'s output exactly (already trusted from
  `phase2_decision.md`'s region-point work).
- Rotations match nerfstudio's own trusted `camera_to_worlds` to float
  precision (~4e-6) for the cross-checked camera.
- Clicked 8 of the 20 viewpoint buttons via a headless-browser harness
  (real button clicks, not simulated data) and confirmed each one: the
  camera actually moves to the exact target position (verified via
  `OrbitControls`' damped interpolation forced to full convergence, then
  compared against the target), and renders real, non-degenerate,
  in-scene content — not a crash, not a blank frame, not a
  looking-away-from-everything frame.

### What's still open

- Not all 20 buttons were individually re-verified after the fix (8 of
  20 spot-checked, spanning different parts of the image set) — the
  underlying transform is proven correct for any camera by the same
  formula, but a per-button UI wiring typo on one of the remaining 12
  isn't strictly ruled out.
- The visual noisiness on some (not all) viewpoints in gsplat.js, vs.
  nerfstudio's own cleaner renders of the same poses (seen earlier this
  session via `render_query.py`), is read as a rasterizer/quality
  difference, not re-derived or proven beyond the reasoning above.

## Text query -> camera snap

Wires a text query straight to a camera jump, reusing `query_regions.py`'s
existing matching logic (imported and called, not copied/rewritten —
verified byte-identical to its pre-refactor CLI output before this was
built on top of it).

`query_server.py` (new): a small Flask app (Flask chosen over
FastAPI+uvicorn — 4 new packages vs. 13, checked via `pip install
--dry-run` before deciding) exposing `GET /query?text=...`. Loads CLIP
**once at startup** (1.7s, not per-request), then imports and calls
`query_regions.py`'s `build_clip_model` / `load_combined_records` /
`encode_query` / `rank_records` / `best_match_dict` — the exact same
functions the CLI path uses, via a new `top1_match()` convenience
wrapper that composes them (no new matching logic, just orchestration).
Response:
```
{matched, localized, viewpoint_id, similarity, sift_support, message, caveat}
```
`message` is `null` for a localized match or `query_regions.py`'s exact
`NOT_LOCALIZED_MESSAGE` (unmodified) for a 2D-only one. No confidence
threshold is computed server-side — consistent with every other task
this session's standing rule ("no threshold logic"), since
`phase2_decision.md` already established similarity alone doesn't
reliably separate real matches from wrong ones. Instead `caveat` carries
that finding's exact wording (reused verbatim from `ui/app.py`'s
permanent bottom banner) on every response, so the raw similarity number
is always shown next to the same honest disclosure, rather than the
server pretending it can classify confidence.

Client side (`index.html`, additive): a text input + submit, `fetch()`s
the API, and either calls `jumpToViewpoint()` (the same function the
preset-viewpoint buttons already use) on a localized match, or shows the
honest message in a warning-styled banner with no camera movement for a
2D-only match — never guesses a nearby viewpoint.

### Verified against the known, documented results (not trusted blind)

Ran all three through the actual running server + a real page load
(headless-browser harness, real form submit, real fetch, camera position
read back afterward):

| Query | Documented | Server response | Camera moved to |
|---|---|---|---|
| "blood spatter" | 0.3226, IMG_0463.jpg | 0.3226, IMG_0463.jpg, localized=true | IMG_0463.jpg's exact position |
| "a car" | 0.2592, low-confidence | 0.2592, IMG_0485.jpg, localized=true, caveat present | IMG_0485.jpg's exact position |
| "drug paraphernalia" | 2D-only, IMG_0468.jpg | localized=false, honest message, no viewpoint_id | unchanged (no jump attempted) |

All three matched exactly. Response latency: ~75-80ms per query (CLIP
already warm from startup) — well under the 10s "feels broken" threshold,
not treated as an issue because it wasn't one.

## Root-caused: why most viewpoints look spiky in gsplat.js (nerfstudio's own render is clean)

15 of 20 preset viewpoints render with heavy needle/spike floater
artifacts in gsplat.js; 5 look clean. The working theory going in
("gsplat.js's simpler rasterizer + this checkpoint's sparse training")
was explicitly treated as unverified and tested, not assumed:

**Test 1 — direct comparison, decisive.** Rendered the exact same poses
(`IMG_0457`=`frame_00001`, `IMG_0461`=`frame_00005`) through nerfstudio's
own renderer (`render_checkpoint.py`, unmodified, same camera data the
viewpoint presets use). **Nerfstudio's render is clean and fully
recognizable** — the mannequin, blood cards, footprint card all sharp,
only the already-documented frustum-edge fringing. This is a real
rendering bug in the gsplat.js integration, not a model/checkpoint
limitation — proceeded to Test 2.

**Test 2 — stale sort-order, disproven.** gsplat.js's depth sort runs in
a Web Worker, triggered every `render()` call
(`vendor/gsplat-1.2.9.es.js`, `RenderProgram.render`) — async by
construction, so a capture taken synchronously right after a camera jump
(no yield to the event loop) could plausibly use a stale sort. Tested
directly: forced the camera to the *exact* target position/rotation
synchronously, then captured at 0ms, 500ms, 1500ms, and 3000ms of real
wall-clock wait with the camera provably static throughout (position
read back and confirmed unchanged at each capture). **The artifact was
unchanged across all four captures** — 3 full seconds of real time gave
the worker ample opportunity to catch up if that were the cause. Ruled
out.

**Test 3 — scale convention, refined into the actual mechanism.** Read
`vendor/gsplat-1.2.9.es.js`'s `PLYLoader._ParsePLYBuffer` directly: it
applies `Math.exp()` to `scale_0/1/2` and sigmoid to `opacity`, exactly
the standard INRIA 3DGS ply convention `splat.ply`'s header uses — no
units mismatch, no missing exponentiation. (It also silently drops all
45 `f_rest_*` higher-order spherical-harmonics coefficients, using only
the DC/base color — a real simplification vs. nerfstudio's renderer, but
affects color, not the geometric spike shape, so not the cause here.)

Checked the actual scale *values* directly (`plyfile`, not assumed):
absolute magnitudes are sane (max 0.5 in a scene spanning ~20+ units —
not oversized). But **anisotropy is extreme and widespread**: median
ratio between a Gaussian's longest and shortest axis is **52.6x**;
**40.6% of all 454,084 Gaussians exceed 100x anisotropy**, with outliers
past 8.8 million x. These are real, legitimately-trained "needle"
Gaussians (thin structures — card edges, text, fine lines are exactly
what produces them), not an export bug.

**Confirmed the mechanism directly**, not just correlated: filtered the
ply to keep only Gaussians with anisotropy ≤5 (the most compact 9%,
41,885 of 454,084) and re-rendered `IMG_0457`'s exact pose. **The needle
artifacts were gone, replaced by discrete round blobs** — proving
gsplat.js's simpler rasterizer specifically mishandles high-anisotropy
("needle") Gaussians in a way nerfstudio's own renderer does not, most
likely a missing numerical-stability safeguard for near-degenerate 2D
covariance projection (not confirmed at the shader-code level — inferred
from this closed-loop behavioral test, not from reading the actual vertex
shader). A milder filter (≤100x, still keeping 59% of Gaussians) showed
no visible improvement — the problem threshold sits somewhere in the
broad middle of this checkpoint's actual anisotropy distribution, not at
a clean cutoff removing only genuine outliers, which is exactly why no
simple filter is offered as a fix here: at any threshold aggressive
enough to visibly help, it also strips the real fine-structure content
(cards, text, edges) that legitimately needs those Gaussians.

**Conclusion**: real, fixable-in-principle rendering bug, not a
checkpoint/model limitation — but the fix (proper degenerate-ellipse
handling in gsplat.js's rasterizer, or an alternative viewer library)
is out of scope here and not attempted. Test/diagnostic files
(`test_filtered.html`, filtered `.ply` variants) were deleted after use,
not committed — this section is the record.

## Follow-up: pinned down to the actual shader/data level (still unfixed, safety-tagged)

Time-boxed (30 min) attempt to go from "behavioral" to "shader-level"
diagnosis and try a minimal fix, with `git tag pre-shader-fix` (→
`8c1ba2f`) created first as a mandatory safety net. Total time used:
**~9 minutes** — stopped well inside the box once the required fix
turned out to be larger than "minimal, targeted."

**Read the actual vertex shader** (`vendor/gsplat-1.2.9.es.js`, GLSL
inline, ~line 1647). The low-pass dilation (`cov2d[0][0]/[1][1] += 0.3`,
matching the INRIA reference exactly) and the max-radius clamp
(`min(sqrt(2·λ), 1024.0)`) are both present and correct — not the cause.

**Two real, well-justified shader bugs were found and fixed, tested, and
had zero visible effect on the artifact** (before/after captures
identical at both `IMG_0457` — bad — and `IMG_0476` — good):
1. `vec2 diagonalVector = normalize(vec2(cov2d[0][1], lambda1 - cov2d[0][0]))`
   degenerates to `normalize((0,0))` whenever the off-diagonal term is
   ~0 *and* the larger eigenvalue equals the diagonal entry — a real,
   provable 0/0 case for near-axis-aligned covariances, not a rare edge
   case. Fixed with an explicit axis-aligned branch.
2. `lambda2 = mid - radius` subtracts two nearly-equal, potentially huge
   values for extreme anisotropy — classic float32 catastrophic
   cancellation. Fixed with the standard numerically-stable
   `lambda2 = det(cov2d)/lambda1` reformulation.

Both fixes are numerically correct improvements in general, but **neither
was the actual mechanism here** — reverted (see below), since they
changed nothing and don't belong in the tree unexplained.

**Kept investigating within the box and found the real cause**: the splat
texture is `RGBA32UI`, and the shader unpacks each covariance component
with `unpackHalf2x16` — the 3D world-space covariance is stored at
**16-bit half-float precision**, packed CPU-side (a Web Worker) before
ever reaching the shader. Checked directly (not assumed): for the 20,000
most anisotropic Gaussians in this checkpoint, **2.25% of covariance
matrix entries are nonzero in float32 but underflow to exactly 0.0 in
float16** (a value like a needle Gaussian's short-axis variance can be
~10⁻¹⁴–10⁻¹⁹, far below half-float's ~6×10⁻⁸ subnormal floor) — **8.9% of
Gaussians in that subset have at least one such zeroed covariance entry**.
This is real, quantified data loss at the texture-packing stage, not
shader math — no vertex-shader-only patch can recover a value that was
already zeroed before upload. A correct fix means restructuring the
covariance texture format itself (e.g. full `RGBA32F` instead of
half-float-packed `RGBA32UI`, or a scale-invariant encoding like storing
per-axis log-scale directly) across three interconnected pieces — the
worker's CPU-side packing, the texture upload/format declarations, and
the shader's unpacking — with real risk of regressing the ~60% of
Gaussians that already render correctly. That's a real code change, not
a one-line patch, and re-verifying all 20 viewpoints afterward (this
task's own requirement before declaring success) wouldn't have fit
cleanly in what remained of the box with margin for care.

**Stopped and reverted per instruction, cleanly, not left half-fixed**:
```
git diff pre-shader-fix..HEAD --stat   # empty
```
`vendor/gsplat-1.2.9.es.js` is back to the exact byte-identical
pre-investigation state (`git checkout -- vendor/gsplat-1.2.9.es.js`,
confirmed against the tag). Nothing shader-related was left applied.

**Status: confirmed-diagnosed-but-unfixed tonight**, precisely at the
data level this time (half-float covariance texture packing losing
precision for extreme-anisotropy Gaussians), not just behaviorally. The
`pre-shader-fix` tag remains in the repo as a permanent, real reference
point for whenever this is picked back up.

## What's NOT been done (Stage 3, explicitly not started without go-ahead)

- No styling to match the dark/gold aesthetic.
- No visual marker at the matched location (camera jump only, no
  highlight/crosshair the way the static-render pipeline has).
- No fix for the gsplat.js anisotropic-Gaussian rendering bug above.
