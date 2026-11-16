#!/usr/bin/env python3
"""ArUco marker detection over an image folder.

IMPORTANT: run this on EXACTLY the images COLMAP reconstructed (same pixels, same
orientation, same resolution). Images are read with cv2.IMREAD_IGNORE_ORIENTATION
because COLMAP ignores the EXIF orientation tag (cv2.imread would otherwise rotate
the pixels and the corner coordinates would no longer match the COLMAP model). For
this project that means the *_corrected folder, not the raw photos, if that is what
COLMAP was run on.

Output JSON:
  {"meta": {...},
   "image_sizes": {image: [width, height]},
   "detections":  {image: {marker_id: [[x,y],[x,y],[x,y],[x,y]]}},   # pixel coords, ArUco
                                                                       # corner order (marker TL,TR,BR,BL)
   "counts":      {image: n_markers_detected},
   "duplicate_ids": {image: [ids seen more than once; these are DROPPED from detections]}}
Marker ids are JSON string keys. Images are keyed by basename.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


def get_dictionary(name: str):
    if not name.startswith("DICT_") or not hasattr(cv2.aruco, name):
        raise ValueError(f"unknown ArUco dictionary {name!r}; use a cv2.aruco.DICT_* name")
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))


def detect_image(gray, detector):
    corners, ids, _rej = detector.detectMarkers(gray)
    found, dup = {}, []
    if ids is None:
        return found, dup
    ids = ids.flatten().tolist()
    cnt = Counter(ids)
    for c, i in zip(corners, ids):
        if cnt[i] > 1:
            if i not in dup:
                dup.append(i)
            continue
        found[str(i)] = c.reshape(4, 2).astype(float).tolist()
    return found, dup


def detect_folder(folder, dictionary_name, refine):
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = (cv2.aruco.CORNER_REFINE_SUBPIX if refine == "subpix"
                                     else cv2.aruco.CORNER_REFINE_NONE)
    det = cv2.aruco.ArucoDetector(get_dictionary(dictionary_name), params)
    out = {"meta": {"dictionary": dictionary_name, "corner_refinement": refine,
                    "opencv": cv2.__version__, "folder": str(folder)},
           "image_sizes": {}, "detections": {}, "counts": {}, "duplicate_ids": {}}
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in IMG_EXT)
    if not files:
        raise FileNotFoundError(f"no images in {folder}")
    for p in files:
        g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
        if g is None:
            raise IOError(f"cannot read {p}")
        found, dup = detect_image(g, det)
        out["image_sizes"][p.name] = [int(g.shape[1]), int(g.shape[0])]
        out["detections"][p.name] = found
        out["counts"][p.name] = len(found)
        if dup:
            out["duplicate_ids"][p.name] = dup
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True)
    ap.add_argument("--dictionary", required=True, help="e.g. DICT_4X4_50, DICT_5X5_100, DICT_ARUCO_ORIGINAL")
    ap.add_argument("--corner-refinement", required=True, choices=["none", "subpix"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = detect_folder(a.images, a.dictionary, a.corner_refinement)
    json.dump(res, open(a.out, "w"), indent=1)
    tot = sum(res["counts"].values())
    print(f"{len(res['counts'])} images, {tot} detections; per-image counts: {res['counts']}")


if __name__ == "__main__":
    main()
