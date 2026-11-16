"""Step 5 summary for landmark distances (rules: eval/results/landmarks/analysis/DECLARED.md).

Reads landmark_distances.py outputs + the model spec list, and the two click passes. Writes:
  per_model.csv        one row per model: family, condition, flip set, n_registered, points dropped, images used,
                       scaled distance (mm, primary ref mag_height) and signed error % per distance
  noise_floor.json     click repeatability (px) and its Monte Carlo propagation to mm per distance
  groups.csv           per (family, grouping, group, distance): n, mean err %, 95 % bootstrap CI, SD mm
  tests.csv            Kruskal-Wallis per (family, grouping, distance)
  spread_vs_floor.csv  between-model SD vs click-noise floor per (family, distance)
  summary.png          signed error % per model, by family/condition, with the floor band

Run with the crime-image python (needs PIL for landmark_distances' imports):
  python eval/summarize_landmarks.py --config eval/landmarks_config.json --specs <specs.json> \
      --pass1 eval/results/landmarks/clicks.csv --pass2 eval/results/landmarks/clicks_pass2.csv \
      --ld-out <landmark_distances out dir> --raw-images-dir data/galanakis2021/photos \
      --min-ray-angle-deg 3 --max-reproj-px 5 --mc-draws 500 --out-dir <dir>
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import kruskal

import colmap_io
import landmark_distances as ld

PRIMARY = ["mag_width", "shoe_length", "lip_length"]
LOWCONF = ["box_length", "box_width"]
FLIP_LABEL = {"none": "{none}", "0476": "{0476}", "0474+0475": "{0474,0475}", "0474+0475+0476": "{0474,0475,0476}"}


def rcsv(p):
    return list(csv.DictReader(open(p)))


def wcsv(p, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)


def boot_ci(x, rng, n=10000):
    x = np.asarray(x, float)
    if len(x) < 2:
        return (float("nan"), float("nan"))
    m = x[rng.integers(0, len(x), (n, len(x)))].mean(1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def click_repeatability(p1, p2):
    a = {(r["point_name"], r["image"]): (float(r["x"]), float(r["y"])) for r in rcsv(p1)}
    pairs = []
    for r in rcsv(p2):
        k = (r["point_name"], r["image"])
        if k in a:
            dx, dy = float(r["x"]) - a[k][0], float(r["y"]) - a[k][1]
            pairs.append(dict(point=k[0], image=k[1], dx=dx, dy=dy, d=float(np.hypot(dx, dy))))
    d = np.array([[p["dx"], p["dy"]] for p in pairs])
    sigma = float(np.sqrt((d ** 2).mean()) / np.sqrt(2)) if len(d) else float("nan")
    return pairs, sigma


def scaled(cfg, pts):
    dist = ld.distance_table(cfg, pts)
    if cfg["primary_reference"] not in dist:
        return {}
    s = {d["name"]: d["mm"] for d in cfg["distances"]}[cfg["primary_reference"]] / dist[cfg["primary_reference"]]
    return {k: v * s for k, v in dist.items()}


def mc_model(cfg, obs, spec, a, sigma, rng):
    """SD (mm) of each scaled distance under isotropic click noise sigma (px), and mm-per-px at each re-clicked view."""
    draws = defaultdict(list)
    for _ in range(a.mc_draws):
        o = {p: [(n, x + rng.normal(0, sigma), y + rng.normal(0, sigma), w, h) for n, x, y, w, h in lst] for p, lst in obs.items()}
        pts, _, _ = ld.model_points(spec["model_dir"], spec["frame"], o, a.raw_images_dir, a.min_ray_angle_deg, a.max_reproj_px)
        for k, v in scaled(cfg, pts).items():
            draws[k].append(v)
    return {k: float(np.std(v, ddof=1)) for k, v in draws.items() if len(v) >= 0.9 * a.mc_draws}


def mm_per_px(cfg, obs, spec, a, keys):
    """For each re-clicked (point, image): depth (scaled to mm) / focal (px) in this model."""
    pts, _, _ = ld.model_points(spec["model_dir"], spec["frame"], obs, a.raw_images_dir, a.min_ray_angle_deg, a.max_reproj_px)
    dist = ld.distance_table(cfg, pts)
    ref = cfg["primary_reference"]
    if ref not in dist:
        return []
    s = {d["name"]: d["mm"] for d in cfg["distances"]}[ref] / dist[ref]
    cams = colmap_io.read_cameras(spec["model_dir"])
    ims = {im.name: im for im in colmap_io.read_images(spec["model_dir"], False).values()}
    out = []
    for p, img in keys:
        if p in pts and img in ims:
            im = ims[img]; cam = cams[im.camera_id]
            z = float((im.R @ pts[p] + im.tvec)[2]) * s
            f = float(cam.params[0])  # SIMPLE_RADIAL / SIMPLE_PINHOLE / RADIAL: f first; PINHOLE etc: fx
            out.append(dict(point=p, image=img, depth_mm=z, focal_px=f, mm_per_px=z / f))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ("--config", "--specs", "--pass1", "--pass2", "--ld-out", "--raw-images-dir", "--out-dir"):
        ap.add_argument(k, required=True)
    ap.add_argument("--min-ray-angle-deg", type=float, required=True)
    ap.add_argument("--max-reproj-px", type=float, required=True)
    ap.add_argument("--mc-draws", type=int, default=500)
    ap.add_argument("--exclude-distances", nargs="*", default=[], help="distances left out of every summary output")
    ap.add_argument("--repeat-pass1", help="pass-1 clicks for the repeatability pairs (default: --pass1)")
    ap.add_argument("--label", default="", help="free text written to label.txt in the out dir")
    a = ap.parse_args()
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    if a.label:
        (out / "label.txt").write_text(a.label + "\n")
    cfg = json.load(open(a.config))
    cfg["distances"] = [d for d in cfg["distances"] if not d.get("optional") and d["name"] not in a.exclude_distances]
    names = [d["name"] for d in cfg["distances"] if d["name"] != cfg["primary_reference"]]
    specs = {s["run_id"]: s for s in json.load(open(a.specs))}
    obs = ld.load_clicks(a.pass1)

    # ---- per model
    pp = defaultdict(list)
    for r in rcsv(Path(a.ld_out) / "per_point.csv"):
        pp[r["run_id"]].append(r)
    err = defaultdict(dict)
    for r in rcsv(Path(a.ld_out) / "errors_long.csv"):
        if r["is_primary"] == "True":
            err[r["run_id"]][r["distance"]] = (float(r["est_mm"]), float(r["err_pct"]))
    pts_of = {d["name"]: (d["a"], d["b"]) for d in cfg["distances"]}
    rows = []
    for rid, s in specs.items():
        P = {r["point"]: r for r in pp[rid]}
        row = dict(run_id=rid, family=s["family"], condition=s["condition"], seed=s["seed"],
                   flipset=FLIP_LABEL[P[next(iter(P))]["flipset"]], n_registered=int(P[next(iter(P))]["n_registered"]),
                   points_dropped=sum(r["status"] != "ok" for r in P.values()),
                   dropped_list=";".join(f'{k}({v["status"][9:]})' for k, v in P.items() if v["status"] != "ok"))
        for n in names:
            a_, b_ = pts_of[n]
            row[f"{n}_views"] = f'{P[a_]["n_views"]}+{P[b_]["n_views"]}'
            if n in err[rid]:
                row[f"{n}_mm"], row[f"{n}_err_pct"] = round(err[rid][n][0], 3), round(err[rid][n][1], 3)
            else:
                row[f"{n}_mm"] = row[f"{n}_err_pct"] = ""
        rows.append(row)
    wcsv(out / "per_model.csv", rows)

    # ---- click noise floor
    pairs, sigma = click_repeatability(a.repeat_pass1 or a.pass1, a.pass2)
    rng = np.random.default_rng(0)
    mc = {rid: mc_model(cfg, obs, s, a, sigma, rng) for rid, s in specs.items()}
    floor = {n: float(np.median([m[n] for m in mc.values() if n in m])) for n in names if any(n in m for m in mc.values())}
    first_fix = next(rid for rid, s in specs.items() if s["condition"] == "with_fix")
    conv = mm_per_px(cfg, obs, specs[first_fix], a, [(p["point"], p["image"]) for p in pairs])
    nf = dict(n_pairs=len(pairs), points=sorted({p["point"] for p in pairs}), pairs=pairs,
              sigma_px_per_axis=sigma, mean_disp_px=float(np.mean([p["d"] for p in pairs])) if pairs else None,
              max_disp_px=float(np.max([p["d"] for p in pairs])) if pairs else None,
              mm_per_px_model=first_fix, mm_per_px=conv,
              sigma_mm_single_click=[dict(point=c["point"], image=c["image"], mm=sigma * c["mm_per_px"]) for c in conv],
              mc_draws=a.mc_draws, floor_sd_mm=floor,
              floor_sd_pct={n: 100 * floor[n] / {d["name"]: d["mm"] for d in cfg["distances"]}[n] for n in floor})
    json.dump(nf, open(out / "noise_floor.json", "w"), indent=1)

    # ---- groups, tests, spread
    groupings = [("3.9.1", "condition"), ("3.9.1:with_fix", "flipset"), ("3.9.1:without_fix", "flipset"),
                 ("4.2.1_seeds", "flipset"), ("4.2.1_ablation", "condition")]
    G, T, S = [], [], []
    rng = np.random.default_rng(0)
    for fam, key in groupings:
        fam_name, _, cond = fam.partition(":")
        sel = [r for r in rows if r["family"] == fam_name and (not cond or r["condition"] == cond)]
        for n in names:
            groups = defaultdict(list); groups_mm = defaultdict(list)
            for r in sel:
                if r[f"{n}_err_pct"] != "":
                    groups[r[key]].append(r[f"{n}_err_pct"]); groups_mm[r[key]].append(r[f"{n}_mm"])
            for g, v in sorted(groups.items()):
                lo, hi = boot_ci(v, rng)
                G.append(dict(family=fam, grouping=key, group=g, distance=n, tier="primary" if n in PRIMARY else "low_confidence",
                              n=len(v), mean_err_pct=round(float(np.mean(v)), 3), ci95_lo=round(lo, 3), ci95_hi=round(hi, 3),
                              sd_mm=round(float(np.std(groups_mm[g], ddof=1)), 3) if len(v) > 1 else ""))
            testable = [v for v in groups.values() if len(v) >= 2]
            if len(testable) >= 2 and len({x for v in testable for x in v}) > 1:
                h, p = kruskal(*testable)
                T.append(dict(family=fam, grouping=key, distance=n, k_groups=len(testable),
                              sizes="/".join(str(len(v)) for v in testable), H=round(float(h), 4), p=float(p)))
            else:
                T.append(dict(family=fam, grouping=key, distance=n, k_groups=len(testable),
                              sizes="/".join(str(len(v)) for v in groups.values()), H="", p="",
                              note="not testable (<2 groups with >=2 models, or all values identical)"))
    for fam in ("3.9.1", "4.2.1_seeds", "4.2.1_ablation"):
        for n in names:
            v = [r[f"{n}_mm"] for r in rows if r["family"] == fam and r[f"{n}_mm"] != ""]
            sd = float(np.std(v, ddof=1)) if len(v) > 1 else float("nan")
            S.append(dict(family=fam, distance=n, tier="primary" if n in PRIMARY else "low_confidence", n_models=len(v),
                          between_model_sd_mm=round(sd, 4), noise_floor_sd_mm=round(floor.get(n, float("nan")), 4),
                          ratio=round(sd / floor[n], 3) if n in floor else "", exceeds_floor=bool(n in floor and sd > floor[n]),
                          range_mm=round(max(v) - min(v), 3) if v else ""))
    wcsv(out / "groups.csv", G); wcsv(out / "tests.csv", T); wcsv(out / "spread_vs_floor.csv", S)

    # ---- figure
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    cats = [("3.9.1", "with_fix"), ("3.9.1", "without_fix"), ("3.9.1", "with_fix_seed0_repeat"),
            ("4.2.1_seeds", "incremental"), ("4.2.1_ablation", "i_defaults"), ("4.2.1_ablation", "ii_fallback_off")]
    fig, axes = plt.subplots(1, len(names), figsize=(3.2 * len(names), 4.2), sharey=False)
    for ax, n in zip(axes, names):
        mmref = {d["name"]: d["mm"] for d in cfg["distances"]}[n]
        for i, c in enumerate(cats):
            v = [r[f"{n}_err_pct"] for r in rows if (r["family"], r["condition"]) == c and r[f"{n}_err_pct"] != ""]
            ax.scatter(i + rng.uniform(-0.15, 0.15, len(v)), v, s=8, alpha=0.6, color="C0" if c[0] == "3.9.1" else "C1")
        if n in floor:
            f = 100 * floor[n] / mmref
            ax.axhspan(-f, f, color="0.85", zorder=0, label="±1 SD click noise")
        ax.axhline(0, color="k", lw=0.6)
        ax.set_xticks(range(len(cats))); ax.set_xticklabels(["3.9 fix", "3.9 nofix", "3.9 s0", "4.2 seeds", "4.2 i", "4.2 ii"], rotation=60, fontsize=7)
        ax.set_title(n + (" (low conf.)" if n in LOWCONF else ""), fontsize=9); ax.set_ylabel("signed error % (scale: mag_height)", fontsize=7)
    axes[0].legend(fontsize=6, loc="best")
    fig.tight_layout(); fig.savefig(out / "summary.png", dpi=150)
    print(f"{len(rows)} models; sigma={sigma:.3f} px from {len(pairs)} pairs; floor(mm)={ {k: round(v, 3) for k, v in floor.items()} }; wrote {out}")


if __name__ == "__main__":
    main()
