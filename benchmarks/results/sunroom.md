# Video pipeline benchmark: sunroom

Generated 2026-11-23 10:54 on NVIDIA GeForce RTX 3050 Laptop GPU (3782 MiB). Reference: Aria MPS closed-loop SLAM (closed_loop_trajectory.csv). Footage: `aria_sunroom.mp4`. Every number below is read from the pipeline's own reports or computed by `benchmarks/aria_video.py`; the raw values are in the `.json` file next to this one.

## Run

| Measure | Value |
|---|---|
| Keyframes registered | 106 / 106 (100.0 %) |
| Mean reprojection error | 1.119 px |
| Sparse points | 36696 |
| Camera model | OPENCV_FISHEYE |
| Units assigned by the pipeline | metres |
| Training | 7000 iterations, 93 views at [960, 960], 789.1 s, peak VRAM 1.13 GiB |
| Gaussians | 300000 |
| Held-out PSNR (13 views) | 19.58 dB (worst view 14.08 dB, colour-corrected 21.64 dB) |
| Total pipeline time | 1279.4 s (ingest 0.4, frames 55.5, masks 9.5, sfm 407.6, normalize 0.2, train 797.1, package 9.1) |

## Camera poses against the Aria reference

104 registered keyframes matched to the reference by frame timestamp. Reference path 24.20 m, extent 5.81 m.

| Measure | Mean | Median | RMSE | p95 | Max |
|---|---|---|---|---|---|
| ATE, device origin (m) | 0.032 | 0.026 | 0.041 | 0.084 | 0.156 |
| ATE, lever arm fitted (m) | 0.023 | 0.016 | 0.033 | 0.063 | 0.150 |
| ATE, % of extent | 0.56 | 0.45 | 0.70 | 1.45 | 2.69 |
| Absolute rotation error, mounting fitted (deg) | 0.493 | 0.374 | 0.594 | 1.243 | 2.009 |
| Rotation-angle error, next keyframe, no fit (deg) | 0.361 | 0.204 | 0.536 | 1.309 | 1.856 |
| Rotation-angle error, 10 keyframes apart, no fit (deg) | 0.402 | 0.327 | 0.526 | 1.078 | 1.511 |
| Relative rotation error, next keyframe (deg) | 0.548 | 0.375 | 0.704 | 1.507 | 1.905 |
| Relative rotation error, 10 keyframes apart (deg) | 0.689 | 0.566 | 0.806 | 1.469 | 2.520 |

- Fitted device-to-camera offset: 0.048 m; fitted mounting rotation 92.7°.
- Up-axis error against reference gravity: 3.00°.
- Metric scale error: 17.82 % (lengths in the pipeline's metres divided by the reference's, minus 1). The pipeline sets scale by assuming the camera is 1.45 m above the floor it detects; the reference implies 1.23 m.
- Raw structure-from-motion poses (before normalisation) give the same ATE up to scale: mean 0.56 % of extent.

## How to read this

- The reference is Aria's own SLAM estimate, not surveyed ground truth.
- ATE is measured after a best-fit similarity transform, so it shows the shape of the recovered path, not its placement.
- Rows marked 'fitted' estimate the camera's fixed mounting on the glasses from this same data (3 parameters each), so they are slightly optimistic. Rows marked 'no fit' make no such assumption.
- The lever-arm row fits 3 extra parameters to this same data, so it is slightly optimistic; the true error lies between the two ATE rows.
- One recording. It characterises this run, not the pipeline in general.
