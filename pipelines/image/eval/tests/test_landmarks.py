"""Synthetic tests for click_landmarks.py (GUI part runs only if matplotlib exists; see __main__),
landmark_distances.py and landmark_align.py. Everything is generated; no real data."""
import csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from PIL import Image

import colmap_io as ci
import landmark_distances as ld
import landmark_align as la
import click_landmarks as cl
from align import Sim3
from synth import *


# ---------------------------------------------------------------- frames / EXIF
def make_exif_image(path, upright_w, upright_h, mark_xy, tag=6):
    """Upright image with a bright dot at mark_xy; saved STORED (rotated) with EXIF Orientation=tag."""
    up = Image.new("RGB", (upright_w, upright_h), (20, 20, 20))
    arr = np.asarray(up).copy(); arr[mark_xy[1] - 2:mark_xy[1] + 3, mark_xy[0] - 2:mark_xy[0] + 3] = 255
    up = Image.fromarray(arr)
    inv = {6: Image.ROTATE_90, 8: Image.ROTATE_270, 3: Image.ROTATE_180, 1: None}[tag]  # upright -> stored
    stored = up if inv is None else up.transpose(inv)
    ex = Image.Exif(); ex[0x0112] = tag
    stored.save(path, exif=ex, quality=100, subsampling=0)
    return stored.size


def test_upright_to_stored_matches_pil():
    for tag in (1, 3, 6, 8):
        p = Path(__file__).parent / f"_tmp_exif{tag}.jpg"
        try:
            ws, hs = make_exif_image(p, 120, 80, (90, 17), tag)
            import click_landmarks
            arr, (w, h), t = click_landmarks.load_upright(p)
            assert t == tag and (w, h) == (120, 80)
            ys, xs = np.where(arr[..., 0] > 200)
            xu, yu = xs.mean() + 0.5, ys.mean() + 0.5          # upright dot centre, continuous coords
            xs_, ys_ = ld.upright_to_stored(xu, yu, tag, ws, hs)
            st = np.asarray(Image.open(p).convert("RGB"))[..., 0]  # stored pixels (no transpose)
            yy, xx = np.where(st > 200)
            assert abs(xx.mean() + 0.5 - xs_) < 0.6 and abs(yy.mean() + 0.5 - ys_) < 0.6, (tag, xx.mean() + .5, yy.mean() + .5, xs_, ys_)
        finally:
            p.unlink(missing_ok=True)


# ---------------------------------------------------------------- click session (no GUI)
def test_click_session_roundtrip_undo_skip_resume(tmp_path):
    tasks = [("P", "a.jpg", "d"), ("P", "b.jpg", "d"), ("Q", "a.jpg", "d")]
    s = cl.ClickSession(tasks, tmp_path / "c.csv")
    s.place(10.25, 20.5, 400, 300, 6); assert s.accept()
    assert not s.accept()                      # nothing pending
    s.place(1, 1, 400, 300, 6); assert s.undo() == "pending cleared"
    s.skip()                                   # b.jpg not visible
    s.place(5, 6, 400, 300, 6); s.accept(); assert s.done
    rows = list(csv.DictReader(open(tmp_path / "c.csv")))
    assert [(r["point_name"], r["image"], float(r["x"]), float(r["y"])) for r in rows] == \
        [("P", "a.jpg", 10.25, 20.5), ("Q", "a.jpg", 5.0, 6.0)]
    assert set(rows[0]) == set(cl.FIELDS)
    s2 = cl.ClickSession(tasks, tmp_path / "c.csv")   # resume: everything done
    assert s2.done and len(s2.clicks) == 2 and ("P", "b.jpg") in s2.skipped
    assert "reopened" in s2.undo() and not s2.done and ("Q", "a.jpg") not in s2.clicks


def test_downscale_mapping_roundtrip():
    for k in (1, 2, 3, 4):
        for x, y in ((0.0, 0.0), (10.3, 7.9), (399.0, 299.0)):
            xd, yd = cl.full_to_disp(x, y, k)
            assert abs(cl.disp_to_full(xd, yd, k)[0] - x) < 1e-9
    # a 2x2 block of full-res pixels centred at full (0.5,0.5) is display pixel 0: (0.5*... )
    assert np.allclose(cl.disp_to_full(0, 0, 2), (0.5, 0.5))


def gui_click_test(tmp):
    """Full GUI under Agg: EXIF-6 image, display downscale 2, zoom, undo, accept -> CSV in upright full-res coords."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backend_bases import MouseEvent, KeyEvent
    tmp = Path(tmp); tmp.mkdir(exist_ok=True)
    truth = (301, 117)
    make_exif_image(tmp / "i1.jpg", 400, 300, truth, tag=6)
    make_exif_image(tmp / "i2.jpg", 400, 300, (50, 250), tag=6)
    s = cl.ClickSession([("dot", "i1.jpg", "desc"), ("dot", "i2.jpg", "desc")], tmp / "clicks.csv")
    fig, ax, h = cl.build_gui(s, tmp, display_downscale=2)
    cv = fig.canvas

    def disp_pix(xd, yd):
        return ax.transData.transform((xd, yd))
    def click(xd, yd):
        px, py = disp_pix(xd, yd)
        cv.callbacks.process("button_press_event", MouseEvent("button_press_event", cv, px, py, button=1))
    def key(k):
        cv.callbacks.process("key_press_event", KeyEvent("key_press_event", cv, k))
    # zoom with the scroll wheel around the dot, then click a wrong spot, undo, click the right spot
    px, py = disp_pix(*cl.full_to_disp(*truth, 2))
    for _ in range(3):
        cv.callbacks.process("scroll_event", MouseEvent("scroll_event", cv, px, py, button="up", step=1))
        px, py = disp_pix(*cl.full_to_disp(*truth, 2))
    x0, x1 = ax.get_xlim(); assert (x1 - x0) < 200 * 0.5, "zoom did not shrink the view"
    click(*[v + 20 for v in cl.full_to_disp(*truth, 2)]); key("u")
    assert s.pending is None
    # sub-pixel-accurate click at the dot centre (dot occupies full px truth-2..truth+2 -> centre index = truth)
    click(*cl.full_to_disp(truth[0], truth[1], 2)); key("enter")
    assert not s.done
    key("n")                                   # second image: not visible
    assert s.done
    rows = list(csv.DictReader(open(tmp / "clicks.csv")))
    assert len(rows) == 1
    x, y = float(rows[0]["x"]), float(rows[0]["y"])
    assert (int(rows[0]["img_w"]), int(rows[0]["img_h"]), int(rows[0]["exif_orientation_applied"])) == (400, 300, 6)
    assert abs(x - truth[0]) < 0.6 and abs(y - truth[1]) < 0.6, (x, y, truth)
    # title: wrapped, every line <= 90 chars, whole text inside the figure, axes start below it (long description)
    long_desc = "word " * 60
    s2 = cl.ClickSession([("dot", "i1.jpg", long_desc.strip())], tmp / "clicks2.csv")
    fig2, ax2, h2 = cl.build_gui(s2, tmp, display_downscale=2)
    fig2.canvas.draw()
    lines = h2["state"]["title_lines"]
    assert len(lines) >= 5 and max(len(l) for l in lines) <= 90, lines
    bb = fig2._suptitle.get_window_extent(fig2.canvas.get_renderer())
    fb = fig2.bbox
    assert bb.x0 >= fb.x0 - 1 and bb.x1 <= fb.x1 + 1 and bb.y0 >= fb.y0 - 1 and bb.y1 <= fb.y1 + 1, (bb, fb)
    assert bb.y0 >= ax2.get_position().y1 * fb.height - 2, "title overlaps the image axes"
    plt.close(fig2); plt.close(fig)
    return x, y


# ---------------------------------------------------------------- distances
def scene():
    # landmarks (metres): a magazine-like rectangle and a "shoe" segment, distances known exactly
    P = {"mag_TL": (0.0, 0.0, 1.0), "mag_TR": (0.210, 0.0, 1.0), "mag_BL": (0.0, 0.0, 0.703),
         "shoe_toe": (1.0, 1.0, 0.0), "shoe_heel": (1.0 + 0.330, 1.0, 0.0),   # true 330 mm, config will say 320
         "lip_L": (0.5, -0.5, 0.2), "lip_R": (0.5 + 0.05055, -0.5, 0.2)}
    return {k: np.array(v) for k, v in P.items()}


CFG = {"primary_reference": "mag_height",
       "points": [], "ratios": [["mag_height", "mag_width"], ["shoe_length", "mag_height"]],
       "distances": [dict(name="mag_height", a="mag_TL", b="mag_BL", mm=297.0),
                     dict(name="mag_width", a="mag_TL", b="mag_TR", mm=210.0),
                     dict(name="shoe_length", a="shoe_toe", b="shoe_heel", mm=320.0),
                     dict(name="lip_length", a="lip_L", b="lip_R", mm=50.55)]}


def build_models(tmp, noise_px, rng, tag_raw=6):
    tmp = Path(tmp)
    pts = scene()
    W, H = 640, 480
    cam = {1: ci.Camera(1, "SIMPLE_RADIAL", W, H, np.array([500.0, 320.0, 240.0, -0.05]))}
    poses = ring_cameras(10, radius=3.0, height=1.2, target=(0.5, 0.0, 0.5))
    imgs = make_images(poses)  # names set by synth.make_images
    names = [im.name for im in imgs]
    # upright-frame clicks
    clicks = []
    for im in imgs:
        for pn, X in pts.items():
            uv, depth = ci.project(cam[1], im.R, im.tvec, X[None])
            uv = uv[0] + rng.normal(scale=noise_px, size=2)
            if depth[0] > 0 and 0 < uv[0] < W and 0 < uv[1] < H:
                clicks.append((pn, im.name, uv[0] - 0.5, uv[1] - 0.5))   # index coords = continuous - 0.5
    with open(tmp / "clicks.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(cl.FIELDS)
        for pn, nm, x, y in clicks:
            w.writerow([pn, nm, f"{x:.4f}", f"{y:.4f}", W, H, 1])
    # model A: all images, upright frame
    write_model_txt(tmp / "mA", cam, imgs)
    # model B: image 0,1,2 unregistered (a flip-set style gap)
    write_model_txt(tmp / "mB", cam, imgs[3:])
    # model C: only one image registered -> every point must be dropped
    write_model_txt(tmp / "mC", cam, imgs[:1])
    spec = [dict(run_id="A", condition="with_fix", model_dir=str(tmp / "mA"), frame="upright"),
            dict(run_id="B", condition="with_fix", model_dir=str(tmp / "mB"), frame="upright"),
            dict(run_id="C", condition="with_fix", model_dir=str(tmp / "mC"), frame="upright")]
    return spec, tmp / "clicks.csv", names


def test_distances_noise_free_and_gaps(tmp_path):
    rng = np.random.default_rng(0)
    spec, clicks, names = build_models(tmp_path, 0.0, rng)
    obs = ld.load_clicks(clicks)
    for s in spec[:2]:
        base, diag, dist, errs, ratios = ld.run_model(CFG, obs, s, None, 2.0, 0.01, False)
        assert all(r["status"] == "ok" for r in diag), diag
        assert abs(dist["mag_height"] - 0.297) < 1e-6 and abs(dist["lip_length"] - 0.05055) < 1e-7
        prim = {e["distance"]: e for e in errs if e["is_primary"]}
        # scale fixed by mag_height (297 mm): width exact, lips exact, shoe is 330 vs config 320 -> +3.125 %
        assert abs(prim["mag_width"]["err_pct"]) < 1e-4 and abs(prim["lip_length"]["err_pct"]) < 1e-4
        assert abs(prim["shoe_length"]["err_pct"] - 100 * (330 / 320 - 1)) < 1e-3
        # leave-one-reference-out: with shoe as reference the other distances are off by -3.03 % (=320/330-1)
        shoe_ref = {e["distance"]: e for e in errs if e["reference"] == "shoe_length"}
        assert abs(shoe_ref["mag_width"]["err_pct"] - 100 * (320 / 330 - 1)) < 1e-3
        # scale-free ratio shoe_length/mag_height vs PDF 320/297 -> +3.125 %
        r = {x["ratio"]: x for x in ratios}
        assert abs(r["shoe_length/mag_height"]["err_pct"] - 100 * (330 / 320 - 1)) < 1e-3
        assert abs(r["mag_height/mag_width"]["err_pct"]) < 1e-4
    base, diag, dist, errs, ratios = ld.run_model(CFG, obs, spec[2], None, 2.0, 0.01, False)
    assert dist == {} and errs == [] and all("<2 registered" in r["status"] for r in diag)


def test_distances_error_scales_with_click_noise(tmp_path):
    """Precision is bounded by click noise: errors must grow ~linearly with noise_px (1 px at f=500 px, 3 m range = ~6 mm)."""
    errs = {}
    for noise in (0.1, 1.0):
        d = tmp_path / f"n{noise}"; d.mkdir()
        spec, clicks, _ = build_models(d, noise, np.random.default_rng(1))
        _, _, _, e, _ = ld.run_model(CFG, ld.load_clicks(clicks), spec[0], None, 2.0, 50.0, False)
        errs[noise] = {x["distance"]: abs(x["err_pct"]) for x in e if x["is_primary"]}
    print("click-noise sensitivity (|err| %, primary reference mag_height):", errs)
    for k in ("mag_width", "lip_length"):
        assert errs[1.0][k] > errs[0.1][k] > 0, (k, errs)
    assert errs[0.1]["mag_width"] < 2.0


def test_raw_frame_mapping_through_distances(tmp_path):
    """A 'raw' model whose images are stored rotated (EXIF 6): clicks given upright must map to the stored frame."""
    rng = np.random.default_rng(2)
    pts = scene()
    Ws, Hs = 480, 640                                  # stored (sideways) size; upright = 640 x 480
    cam = {1: ci.Camera(1, "SIMPLE_RADIAL", Ws, Hs, np.array([500.0, 240.0, 320.0, -0.03]))}
    imgs = make_images(ring_cameras(8, radius=3.0, height=1.2, target=(0.5, 0.0, 0.5)))
    raw = tmp_path / "raw"; raw.mkdir()
    rows = []
    for im in imgs:
        make_exif_image(raw / im.name, 640, 480, (100, 100), tag=6)       # stored size 480x640, tag 6
        for pn, X in pts.items():
            uv, d = ci.project(cam[1], im.R, im.tvec, X[None]); xs, ys = uv[0]       # stored continuous coords
            if d[0] > 0 and 0 < xs < Ws and 0 < ys < Hs:
                xu, yu = Hs - ys, xs                                         # stored -> upright for rotate-90-CW
                rows.append((pn, im.name, xu - 0.5, yu - 0.5, 640, 480, 6))
    with open(tmp_path / "clicks.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(cl.FIELDS); w.writerows(rows)
    write_model_txt(tmp_path / "m", cam, imgs)
    spec = dict(run_id="R", condition="without_fix", model_dir=str(tmp_path / "m"), frame="raw")
    base, diag, dist, errs, ratios = ld.run_model(CFG, ld.load_clicks(tmp_path / "clicks.csv"), spec, raw, 2.0, 0.01, False)
    assert all(r["status"] == "ok" for r in diag), diag
    assert abs(dist["mag_height"] - 0.297) < 1e-6


def test_drop_rules(tmp_path):
    rng = np.random.default_rng(3)
    spec, clicks, _ = build_models(tmp_path, 0.0, rng)
    obs = ld.load_clicks(clicks)
    _, diag, dist, _, _ = ld.run_model(CFG, obs, spec[0], None, 179.0, 0.01, False)   # impossible angle -> dropped
    assert dist == {} and all("ray angle" in r["status"] for r in diag)


# ---------------------------------------------------------------- landmark_align
def test_landmark_align_recovers_sim3_and_flags_bad_pick(tmp_path):
    rng = np.random.default_rng(0)
    src = rng.normal(size=(8, 3)) * 2
    R = rand_rot(rng); s, t = 7.5, np.array([3.0, -2.0, 60.0])
    dst = s * src @ R.T + t
    names = [f"p{i}" for i in range(8)]
    out = la.analyse(names, src, dst, True, 4, [("p0", "p1", float(np.linalg.norm(dst[0] - dst[1])))])
    assert abs(out["scale"] - s) < 1e-9 and out["rmse"] < 1e-9
    assert abs(out["checks"][0]["err_aligned"]) < 1e-9
    dst_bad = dst.copy(); dst_bad[3] += [0.5, 0, 0]          # one bad pick
    o2 = la.analyse(names, src, dst_bad, True, 4, [])
    loo = [p["leave_one_out_residual"] for p in o2["pairs"]]
    assert int(np.argmax(loo)) == 3 and loo[3] > 0.4 and o2["rmse"] > 0.05


if __name__ == "__main__":
    # crime-image has PIL + matplotlib but no pytest: tiny runner (tmp_path = fresh temp dir per test)
    import inspect, tempfile, traceback
    ok = fail = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)):
        try:
            fn(*([Path(tempfile.mkdtemp())] if "tmp_path" in inspect.signature(fn).parameters else []))
            print("PASS", name); ok += 1
        except Exception:
            print("FAIL", name); traceback.print_exc(); fail += 1
    x, y = gui_click_test(tempfile.mkdtemp())
    print("PASS gui_click_test: clicked (%.3f, %.3f) vs truth (301, 117)" % (x, y)); ok += 1
    print(f"{ok} passed, {fail} failed"); sys.exit(1 if fail else 0)
