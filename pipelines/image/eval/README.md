# eval/ — evaluating COLMAP + 3DGS against ground truth

Standalone tooling (own env `crime-eval`, see `ENV.txt`; nothing outside `eval/` is read-modified).
Run everything CPU-only, e.g. `OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 nice -n 19 <env>/bin/python script.py ...`.
**No tolerance or threshold has a default**: every one is a required argument.

> **The synthetic tests validate the code, not the science.** They show that the
> implementations recover known transforms/errors from generated data. They say nothing
> about how accurate COLMAP/3DGS is on real scenes; that needs real ground truth.

## Modules

| file | purpose |
|---|---|
| `colmap_io.py` | COLMAP model reader (text **or** binary, auto-detected), camera models, projection/undistortion. (`scripts/colmap_model.py` is text-only and breaks on images with zero keypoints; it is left untouched and not used.) |
| `align.py` | Umeyama Sim(3)/SE(3) + RANSAC; `Sim3` class and JSON format |
| `pose_error.py` | ATE + rotation error vs GT camera poses |
| `cloud_error.py` | accuracy / completeness vs reference cloud or mesh |
| `detect_markers.py` | ArUco detection over an image folder |
| `triangulate_markers.py` | robust marker triangulation from a COLMAP model |
| `marker_error.py` | marker-pair distance error, Sim(3) residuals, scale-free ratio check |
| `score_queries.py` | Phase-2 query localisation scoring |
| `tests/` | `pytest tests` (synthetic data only) |

## Conventions (read this once)

* COLMAP pose `(qvec=(w,x,y,z), tvec)` is **world→camera**: `x_cam = R x_world + t`.
  Camera centre `C = -Rᵀt`; camera→world `c2w = [Rᵀ | C]`.
* Camera axes: OpenCV (`+x` right, `+y` down, `+z` forward). All internal poses are `c2w` in this convention.
* GT JSON poses (`{image: 4x4 c2w}`) need `--gt-camera-convention`:
  `opencv` as is; `opengl` (Blender, nerfstudio/NeRF `transforms.json`: `+y` up, `-z` forward):
  `c2w_cv = c2w_gl · diag(1,−1,−1,1)`. Tested (viewing direction, up-axis, projection of the optical axis).
  Using the wrong convention shows up as a large rotation error (tested), not a silent pass.
* `Sim3`: `x_dst = s·R·x_src + t`, `R` proper rotation. JSON: `{"scale": s, "R": [[..]x3], "t": [..]}`;
  readers also accept a file with that under key `"sim3"` (what `pose_error.py`, `marker_error.py`, `cloud_error.py` write).
  Direction is always **estimated (COLMAP/splat) frame → reference/GT frame**.
* Images are matched by **basename**; duplicates are an error.
* COLMAP is metric-scale-free; all metric numbers need either a GT-derived Sim(3) or marker distances. "Metres" holds only if the GT is in metres.
* nerfstudio/splatfacto outputs live in a *transformed* frame (`dataparser_transforms.json`: re-orientation + scale). The sparse
  COLMAP frame ≠ the exported splat/`sparse_pc.ply` frame (verified: raw model vs `sparse_pc.ply` differ by a similarity).
  A `--sim3` obtained from COLMAP poses is only valid for clouds in the **COLMAP** frame; for splat-frame clouds supply the
  right Sim(3) (e.g. compose with the dataparser transform) or use `--icp`.

## Tools: inputs / outputs

### align.py
`--src A.json --dst B.json --with-scale {true,false} [--ransac-thresh T --ransac-iters N --seed S] --out o.json`
→ `{sim3, residuals, rmse, inliers}`. Python: `umeyama(src,dst,with_scale)`, `umeyama_ransac(src,dst,inlier_thresh,n_iters,seed,with_scale)`.
Needs ≥3 non-collinear points. Reflections are never returned (det R = +1).

### pose_error.py
`--model <COLMAP dir|images.txt> --gt <COLMAP dir|images.txt|poses.json> [--gt-camera-convention] --with-scale {true,false} (--extent X | --extent-from-gt-cameras) [--ransac-thresh T --ransac-iters N --seed S] --out o.json`

Output keys: `sim3`, `n_gt_images`, `n_matched`, `registered_fraction`, `gt_not_in_model`, `model_not_in_gt`, `n_alignment_inliers`,
`ate{mean,median,rmse,p95,max}` (GT units), `ate_percent_of_extent`, `scene_extent(+source)`, `abs_rotation_error_deg`,
`relative_rotation_error_deg` (+`n_pairs`), `per_image`.

Definitions (matched images i=1..n, estimated centres `c_i`, GT centres `g_i`, Sim(3) `(s,R,t)` from Umeyama on `{c_i}→{g_i}`):
* ATE_i = ‖g_i − (s R c_i + t)‖; RMSE = √(mean ATE_i²); also mean/median/p95/max.
* % of extent = 100·stat / extent. Extent = bbox diagonal of matched GT camera centres, or a user value.
* registered fraction = n_matched / n_GT_images (GT images the model lacks count as unregistered).
* absolute rotation error_i = angle(R_gt,iᵀ · R_align · R_est,i) with `R_*` the c2w rotations; angle(M)=arccos((tr M − 1)/2).
* relative rotation error over all pairs i<j = angle((R_gt,iᵀR_gt,j)ᵀ (R_est,iᵀR_est,j)); independent of the alignment.
* Optional RANSAC alignment: ATE is still reported over all matched images (outliers visible), `n_alignment_inliers` says how many fit the model.

### cloud_error.py
`--est <COLMAP dir|PLY> --ref <PLY cloud|mesh> --mesh-samples N --seed S --thresholds t1 t2 .. (--sim3 f | --icp --with-scale {..} --icp-trim f --icp-iters N --icp-tol e [--init-sim3 f]) --out o.json`
* Mesh reference → `N` area-weighted surface samples. **Distances are nearest-sample distances**, so they cannot go below roughly the
  sample spacing (reported as `reference_sample_spacing_approx = √(area/N)`); choose N so this is ≪ your thresholds.
* Metrics (d = nearest-neighbour distance after alignment): accuracy = d(est→ref); completeness = d(ref→est); each
  mean/median/RMSE/p95, plus per threshold τ: fraction ≤ τ for both and `fscore = 2PR/(P+R)`.
* ICP: trimmed (closest `trim` fraction kept) point-to-point Sim(3) ICP. Initialisation: centroid match; RMS-radius scale ratio
  (if scaled); PCA-axis alignment with the 4 proper sign combinations, best ICP result kept. Fails on near-isotropic shapes, strong
  partial overlap, or symmetric scenes; then provide `--sim3`/`--init-sim3`.
* A sparse COLMAP cloud measured against a dense reference will have low *completeness* by construction.

### detect_markers.py
`--images DIR --dictionary DICT_4X4_50 --corner-refinement {none,subpix} --out det.json` →
`{meta, image_sizes, detections{image:{id:[[x,y]×4]}}, counts{image:n}, duplicate_ids}`. Corner order = ArUco order (marker TL,TR,BR,BL).
Must run on the **exact images COLMAP used** (EXIF orientation ignored on read, matching COLMAP); size mismatches are errors downstream.
Duplicate ids within one image are dropped and listed.

### triangulate_markers.py
`--model DIR --detections det.json --reproj-thresh-px P --min-views K --out tri.json` (K ≥ 2).
Output: `markers{id:{position, corners, n_views, views, outlier_views, reproj_rms_px, reproj_max_px, per_view_reproj_px, side_lengths}}`,
`rejected{id:reason}`. Position = mean of the 4 triangulated corners. Method: exhaustive view-pair DLT hypotheses scored by
inlier views (mean corner reprojection error < P px, positive depth), refit, Levenberg–Marquardt refinement on pixel error.
Supported camera models: SIMPLE_PINHOLE, PINHOLE, SIMPLE_RADIAL, RADIAL, OPENCV (others raise).

### marker_error.py
`--triangulated tri.json --gt ground_truth.json --with-scale {true,false} --out o.json`

`ground_truth.json`:
```json
{"units": "m",
 "markers":   {"3": [x, y, z], "7": [x, y, z]},
 "distances": [{"a": 3, "b": 7, "distance": 0.512, "sigma": 0.002}]}
```
`markers` (centres, reference frame) is optional; `distances` (centre-to-centre, 1σ uncertainty) optional. Output: `sim3`,
`alignment{per_marker_residual, rmse, max, loo_residual, loo_rmse}`, `distance_pairs`, `distance_summary`, `scale_free_ratio_check`.
* aligned error: `d_est·s − d_true` (s from marker Sim(3)); LOO: `s₋ₖ = Σ_{l≠k} d̂_l d_l / Σ_{l≠k} d̂_l²` (scale from the other distances,
  out-of-sample); error % = 100·err/d_true; z = err/σ.
* ratio check, all pairs (k,l): `100·((d̂_k/d̂_l)/(d_k/d_l) − 1)`; needs no scale and no marker positions.
* Residuals of a Sim(3) fit on few markers are optimistic (use LOO). Errors below σ are not distinguishable from measurement error.

### score_queries.py
`--predictions p.json --gt queries_gt.json --sim3 s.json --gt-unit-cm U --tolerance-cm T --out o.json`
* `predictions.json`: `{query: [x,y,z] | null}` in the estimated frame. `queries_gt.json`: present → `[x,y,z]` (reference frame), absent → `null`.
* Every GT query must appear in the predictions (missing key = error).
* error_i = U·‖sim3(pred_i) − gt_i‖ (cm). top-1 hit rate = #(answered ∧ error ≤ T)/n_present (null for a present query is a **miss**).
  Median/p95 are over answered present queries (n reported) and also with unanswered as +∞.
  False-positive rate = #(non-null prediction for an absent query)/n_absent (null if no absent queries).

## Ground-truth sources
* Public datasets (ETH3D, Tanks and Temples, ScanNet++/Replica) or Blender scenes: GT poses → `pose_error.py`, reference cloud/mesh → `cloud_error.py`
  (pass the pose-alignment Sim(3) via `--sim3`), known object positions → `queries_gt.json`.
* Staged scenes: ArUco markers + tape-measured distances → `detect_markers` → `triangulate_markers` → `marker_error` (its `sim3` feeds `score_queries`).

## Known limitations
* No dataset-specific loaders (ETH3D/T&T/ScanNet++ formats must be converted to the JSON/PLY formats above).
* Mesh distances are sample-based (above); no exact point-to-triangle distance.
* Pairwise rotation error is O(n²) in images (fine for hundreds, heavy for tens of thousands).
* ICP is local; PCA init is a heuristic. Trimmed ICP is not robust to arbitrary partial overlap.
* Fisheye / FULL_OPENCV / FOV COLMAP camera models are not supported for marker triangulation.
* Marker position = centre from 4 corners; assumes planar square markers and that GT positions are centres.
* Detection quality (blur, marker size in pixels, lighting) is not assessed; only counts per image are reported.
* Nothing here has been run on a real scene with real ground truth. Smoke checks only: reader consistency and reprojection on the
  Galanakis model, binary-vs-text self-comparison (ATE ~1e-15), and ICP recovering the frame of `sparse_pc.ply` from the same points.
