#!/usr/bin/env python3
"""Interactive landmark clicker (matplotlib). Records named points as pixel coordinates.

Run in the `crime-image` env (it has matplotlib + Tk):
    python eval/click_landmarks.py --config eval/landmarks_config.json \\
        --images-dir pipelines/image/data/galanakis2021/photos_corrected \\
        --out eval/results/landmarks/clicks.csv

CSV columns: point_name,image,x,y,img_w,img_h,exif_orientation_applied
  * x,y are in the UPRIGHT full-resolution image frame (the frame of `photos_corrected/`),
    "pixel-index coordinates": the CENTRE of the top-left pixel is (0,0) (matplotlib
    convention). COLMAP's convention puts that centre at (0.5,0.5); landmark_distances.py
    adds 0.5. If the file carries an EXIF Orientation tag, the tool applies it
    (ImageOps.exif_transpose) and records the tag; with --display-downscale k the image is
    shown k times smaller but x,y are mapped back to full resolution.

Keys (matplotlib's own key bindings and toolbar are disabled so they cannot eat clicks):
  left click   place / move the red marker for the CURRENT point in the CURRENT image
  Enter/space  accept the marker and go to the next task (point, image)
  n            this point is NOT visible in this image: skip it (remembered)
  u            undo: remove the pending marker; if none, reopen the previous task and delete its click
  b            go back one task WITHOUT deleting (to re-check)
  scroll       zoom around the cursor        r  reset zoom       arrows / w a s d  pan
  q            save and quit (the file is also saved after every accept/skip; re-run to resume)
Order: all images of point 1, then point 2, ... (see landmarks_config.json). At the end the tool
reports points with fewer than --min-images clicks.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

FIELDS = ["point_name", "image", "x", "y", "img_w", "img_h", "exif_orientation_applied"]


def load_upright(path: Path, display_downscale: int = 1):
    """-> (uint8 array for display, (w_full, h_full) upright, exif orientation tag applied)."""
    im = Image.open(path)
    tag = int(im.getexif().get(0x0112, 1) or 1)
    if tag != 1:
        im = ImageOps.exif_transpose(im)
    im = im.convert("RGB")
    w, h = im.size
    if display_downscale > 1:
        im = im.resize((max(1, w // display_downscale), max(1, h // display_downscale)), Image.BOX)
    return np.asarray(im), (w, h), tag


def disp_to_full(x, y, k):
    """display pixel-index coords -> full-res pixel-index coords (centre-aligned mapping)."""
    return (x + 0.5) * k - 0.5, (y + 0.5) * k - 0.5


def full_to_disp(x, y, k):
    return (x + 0.5) / k - 0.5, (y + 0.5) / k - 0.5


class ClickSession:
    """State machine without any GUI (unit-testable)."""

    def __init__(self, tasks, out_csv: Path):
        self.tasks = list(tasks)  # [(point_name, image_name, description)]
        self.out = Path(out_csv)
        self.skip_path = self.out.with_suffix(".skipped.csv")
        self.clicks = {}   # (point,image) -> dict(x,y,img_w,img_h,exif)
        self.skipped = set()
        self.pending = None  # (x_full, y_full, w, h, tag)
        self._load()
        self.idx = self._first_undone()

    def _load(self):
        if self.out.exists():
            for r in csv.DictReader(open(self.out)):
                self.clicks[(r["point_name"], r["image"])] = dict(
                    x=float(r["x"]), y=float(r["y"]), img_w=int(r["img_w"]), img_h=int(r["img_h"]),
                    exif=int(r["exif_orientation_applied"]))
        if self.skip_path.exists():
            for r in csv.DictReader(open(self.skip_path)):
                self.skipped.add((r["point_name"], r["image"]))

    def _first_undone(self):
        for i, (p, im, _) in enumerate(self.tasks):
            if (p, im) not in self.clicks and (p, im) not in self.skipped:
                return i
        return len(self.tasks)

    @property
    def done(self):
        return self.idx >= len(self.tasks)

    def current(self):
        return self.tasks[self.idx] if not self.done else None

    def place(self, x_full, y_full, w, h, tag):
        self.pending = (float(x_full), float(y_full), int(w), int(h), int(tag))

    def accept(self):
        if self.done or self.pending is None:
            return False
        p, im, _ = self.tasks[self.idx]
        x, y, w, h, tag = self.pending
        self.clicks[(p, im)] = dict(x=x, y=y, img_w=w, img_h=h, exif=tag)
        self.skipped.discard((p, im))
        self.pending = None
        self.idx += 1
        self.save()
        return True

    def skip(self):
        if self.done:
            return False
        p, im, _ = self.tasks[self.idx]
        self.skipped.add((p, im))
        self.clicks.pop((p, im), None)
        self.pending = None
        self.idx += 1
        self.save()
        return True

    def undo(self):
        if self.pending is not None:
            self.pending = None
            return "pending cleared"
        if self.idx == 0:
            return "nothing to undo"
        self.idx -= 1
        p, im, _ = self.tasks[self.idx]
        self.clicks.pop((p, im), None)
        self.skipped.discard((p, im))
        self.save()
        return f"reopened {p} / {im}"

    def back(self):
        if self.idx > 0:
            self.idx -= 1
        self.pending = None
        ent = self.clicks.get(self.tasks[self.idx][:2]) if not self.done else None
        if ent:
            self.pending = (ent["x"], ent["y"], ent["img_w"], ent["img_h"], ent["exif"])

    def save(self):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        order = {t[:2]: i for i, t in enumerate(self.tasks)}
        with open(self.out, "w", newline="") as f:
            w = csv.writer(f); w.writerow(FIELDS)
            for (p, im), d in sorted(self.clicks.items(), key=lambda kv: order.get(kv[0], 1e9)):
                w.writerow([p, im, f"{d['x']:.3f}", f"{d['y']:.3f}", d["img_w"], d["img_h"], d["exif"]])
        with open(self.skip_path, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["point_name", "image"])
            for p, im in sorted(self.skipped):
                w.writerow([p, im])

    def counts(self, point_names):
        return {p: sum(1 for (q, _) in self.clicks if q == p) for p in point_names}


def build_tasks(cfg, include_optional):
    tasks = []
    for pt in cfg["points"]:
        if pt.get("optional") and not include_optional:
            continue
        for im in pt["images"]:
            tasks.append((pt["name"], im, pt["description"]))
    return tasks


def build_gui(session: ClickSession, images_dir: Path, display_downscale: int = 1, show_help=True):
    import matplotlib
    import matplotlib.pyplot as plt
    for k in [k for k in matplotlib.rcParams if k.startswith("keymap.")]:
        matplotlib.rcParams[k] = []
    matplotlib.rcParams["toolbar"] = "None"
    fig, ax = plt.subplots(figsize=(13, 9))
    st = dict(img=None, name=None, size=None, tag=1, view=None, artists=[], msg="")
    title = fig.suptitle("", x=0.01, y=0.995, ha="left", va="top", fontsize=9)

    def set_title(text, width=90):
        """Wrap to ~width chars per line and reserve exactly enough top margin for all lines."""
        lines = [l for para in text.split("\n") for l in (textwrap.wrap(para, width) or [""])]
        title.set_text("\n".join(lines))
        fig.subplots_adjust(top=max(0.5, 1 - (0.0215 * len(lines) + 0.012)), bottom=0.01, left=0.01, right=0.99)
        return lines

    def full_xy(xd, yd):
        return disp_to_full(xd, yd, display_downscale)

    def draw():
        for a in st["artists"]:
            a.remove()
        st["artists"] = []
        if session.done:
            set_title("ALL TASKS DONE. Press q to save and quit.")
            fig.canvas.draw_idle(); return
        p, im, desc = session.current()
        if st["name"] != im:
            arr, size, tag = load_upright(images_dir / im, display_downscale)
            ax.clear(); ax.imshow(arr, interpolation="nearest"); ax.axis("off")
            st.update(img=arr, name=im, size=size, tag=tag, view=(ax.get_xlim(), ax.get_ylim()))
        for (q, imq), d in session.clicks.items():
            if imq == im:
                xd, yd = full_to_disp(d["x"], d["y"], display_downscale)
                st["artists"] += [ax.plot(xd, yd, "o", mfc="none", mec="lime", ms=12)[0],
                                  ax.text(xd + 8, yd - 8, q, color="lime", fontsize=9)]
        if session.pending is not None:
            xd, yd = full_to_disp(session.pending[0], session.pending[1], display_downscale)
            st["artists"].append(ax.plot(xd, yd, "+", c="red", ms=22, mew=1.5)[0])
        n_done = len(session.clicks) + len(session.skipped)
        st["title_lines"] = set_title(
            f"[{session.idx + 1}/{len(session.tasks)}] POINT {p}  |  {im}\n{desc}\n"
            f"Keys: click=place, Enter=accept, n=not visible, u=undo, b=back, scroll=zoom, r=reset zoom, "
            f"arrows/wasd=pan, q=save+quit.   {st['msg']}")
        fig.canvas.draw_idle()

    def on_click(ev):
        if ev.inaxes is not ax or ev.button != 1 or session.done:
            return
        x, y = full_xy(ev.xdata, ev.ydata)
        w, h = st["size"]
        session.place(x, y, w, h, st["tag"]); st["msg"] = f"placed ({x:.1f},{y:.1f})"; draw()

    def on_scroll(ev):
        if ev.inaxes is not ax:
            return
        f = 0.7 ** ev.step
        x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
        ax.set_xlim(ev.xdata - (ev.xdata - x0) * f, ev.xdata + (x1 - ev.xdata) * f)
        ax.set_ylim(ev.ydata - (ev.ydata - y0) * f, ev.ydata + (y1 - ev.ydata) * f)
        fig.canvas.draw_idle()

    def pan(dx, dy):
        x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
        sx, sy = (x1 - x0) * 0.2, (y1 - y0) * 0.2
        ax.set_xlim(x0 + dx * sx, x1 + dx * sx); ax.set_ylim(y0 + dy * sy, y1 + dy * sy)

    def on_key(ev):
        k = ev.key
        if k in ("enter", " "):
            st["msg"] = "accepted" if session.accept() else "nothing to accept: click first"
            if st["msg"] == "accepted":
                st["name"] = None
        elif k == "n":
            session.skip(); st["name"] = None; st["msg"] = "skipped"
        elif k == "u":
            st["msg"] = session.undo(); st["name"] = None
        elif k == "b":
            session.back(); st["name"] = None
        elif k == "r" and st["view"]:
            ax.set_xlim(st["view"][0]); ax.set_ylim(st["view"][1])
        elif k in ("left", "a"):
            pan(-1, 0)
        elif k in ("right", "d"):
            pan(1, 0)
        elif k in ("up", "w"):
            pan(0, -1)
        elif k in ("down", "s"):
            pan(0, 1)
        elif k == "q":
            session.save(); plt.close(fig); return
        draw()

    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("scroll_event", on_scroll)
    fig.canvas.mpl_connect("key_press_event", on_key)
    draw()
    return fig, ax, dict(draw=draw, state=st)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--images-dir", required=True, help="UPRIGHT full-resolution images (photos_corrected)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-images", type=int, required=True, help="report points clicked in fewer images than this")
    ap.add_argument("--include-optional", action="store_true")
    ap.add_argument("--display-downscale", type=int, default=1, help="show image k times smaller (coords still full-res)")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    tasks = build_tasks(cfg, a.include_optional)
    sess = ClickSession(tasks, Path(a.out))
    import matplotlib.pyplot as plt
    build_gui(sess, Path(a.images_dir), a.display_downscale)
    plt.show()
    sess.save()
    names = sorted({t[0] for t in tasks})
    cnt = sess.counts(names)
    bad = {p: c for p, c in cnt.items() if c < a.min_images}
    print("clicks per point:", cnt)
    if bad:
        print(f"WARNING: points with < {a.min_images} images: {bad}  (re-run to resume)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
