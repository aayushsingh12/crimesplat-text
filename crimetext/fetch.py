"""Fetch a case page and turn it into numbered passages, source files and captioned photos.

A passage is one bullet or paragraph of the page. It is the unit of evidence: every claim
extracted later must quote a passage verbatim.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from . import timeparse

UA = "Mozilla/5.0 (X11; Linux x86_64) crimetext-research-client"
VOID = {"br", "img", "hr", "input", "meta", "link", "source"}
BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "td", "blockquote"}


def http_get(url: str, timeout=60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class _Blocks(HTMLParser):
    """Flatten the article into blocks: (tag, text, links, bold spans, list depth, only_bold)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.images = [], []
        self.stack = []          # open block elements, innermost last
        self.skip = 0            # inside script/style
        self.depth = 0           # <ul>/<ol> nesting
        self.bold = 0
        self.href = None

    def _open(self, tag):
        self.stack.append({"tag": tag, "text": [], "links": [], "bold": [], "depth": self.depth, "plain": 0})

    def _close(self):
        b = self.stack.pop()
        text = re.sub(r"\s+", " ", "".join(b["text"])).strip()
        text = re.sub(r"\s+([.,;:])", r"\1", text)
        if text:
            bold = [re.sub(r"\s+", " ", x).strip() for x in b["bold"] if x.strip()]
            self.blocks.append({"tag": b["tag"], "text": text, "links": b["links"], "bold": bold,
                                "depth": b["depth"], "only_bold": b["plain"] == 0 and bool(bold)})

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg", "nav", "header", "footer", "form"):
            self.skip += 1
            return
        if self.skip:
            return
        if tag in ("ul", "ol"):
            self.depth += 1
        if tag in BLOCK:
            # a nested <li> closes nothing; text before it stays with the parent
            self._open(tag)
        elif tag in ("strong", "b"):
            self.bold += 1
            if self.stack:
                self.stack[-1]["bold"].append("")
        elif tag == "a":
            self.href = a.get("href")
        elif tag == "img":
            src = a.get("data-src") or a.get("src") or ""
            self.images.append({"src": src, "alt": (a.get("alt") or "").strip()})

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "nav", "header", "footer", "form"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("ul", "ol"):
            self.depth = max(0, self.depth - 1)
        if tag in BLOCK and self.stack and any(b["tag"] == tag for b in self.stack):
            while self.stack and self.stack[-1]["tag"] != tag:
                self._close()
            self._close()
        elif tag in ("strong", "b"):
            self.bold = max(0, self.bold - 1)
        elif tag == "a":
            self.href = None

    def handle_data(self, data):
        if self.skip or not self.stack:
            return
        b = self.stack[-1]
        if self.href and data.strip().lower() in ("source", "sources", "link"):
            b["links"].append(self.href)      # a bare "Source" link is provenance, not text
            return
        if self.href and self.href.startswith("http") and data.strip():
            b["links"].append(self.href)
        b["text"].append(data)
        if self.bold and b["bold"]:
            b["bold"][-1] += data
        elif data.strip("  .,;:-–"):
            b["plain"] += 1


def parse_page(page: str, timeline_section: str | None = None, section_times: dict | None = None):
    m = re.search(r"<article.*?</article>", page, re.S) or re.search(r"<main.*?</main>", page, re.S)
    p = _Blocks()
    p.feed(m.group(0) if m else page)
    passages, section, sub, when, in_timeline, section_when = [], "Summary", None, None, False, None
    for b in p.blocks:
        tag, text = b["tag"], b["text"]
        if tag in ("h1", "h2"):
            section, sub, when = text, None, None
            in_timeline = bool(timeline_section) and text.strip() == timeline_section
            section_when = timeparse.parse((section_times or {}).get(text.strip(), ""))
            continue
        if tag in ("h3", "h4"):
            sub = text
            continue
        if tag == "p" and b["only_bold"] and len(text) < 90:
            parsed = timeparse.parse(text) if in_timeline else None
            if parsed:
                when = parsed           # a date heading in the timeline
            else:
                sub = text              # a bold sub-heading elsewhere
            continue
        if len(text) < 12:
            continue
        passages.append({
            "id": f"p{len(passages) + 1:04d}", "section": section, "subsection": sub,
            "date_heading": when["text"] if (when and in_timeline) else None,
            # an undated section can be given a date in case.json ("section_times"); the heading stays empty
            "time": ({k: when[k] for k in ("start", "end", "precision")} if (when and in_timeline)
                     else {k: section_when[k] for k in ("start", "end", "precision")} if section_when else None),
            "time_from": "heading" if (when and in_timeline) else "section" if section_when else None,
            "depth": b["depth"], "text": text, "bold": b["bold"],
            "links": sorted(set(b["links"])),
        })
    return passages, p.images


def _drive_id(url: str):
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", url)
    return m.group(1) if m else None


def _ocr(pdf: Path, out: Path, pages: int = 3):
    """Text layer if the PDF has one, else OCR of the first pages. Newspaper scans OCR badly: reference only."""
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
    if len(txt.strip()) < 200:
        tmp = out.with_suffix("")
        subprocess.run(["pdftoppm", "-r", "130", "-gray", "-l", str(pages), "-png", str(pdf), str(tmp)], check=False)
        parts = []
        for png in sorted(out.parent.glob(tmp.name + "-*.png")):
            parts.append(subprocess.run(["tesseract", str(png), "-", "--psm", "3"], capture_output=True, text=True).stdout)
            png.unlink()
        txt = "\n\f\n".join(parts)
    out.write_text(txt)
    return len(txt)


def fetch(case_dir: Path, files=True, photos=True, ocr=True, log=print):
    cfg = json.loads((case_dir / "case.json").read_text())
    raw = case_dir / "raw"
    (raw / "files").mkdir(parents=True, exist_ok=True)
    page_path = raw / "page.html"
    if not page_path.exists():
        page_path.write_bytes(http_get(cfg["source_url"]))
    body = page_path.read_bytes()
    passages, images = parse_page(body.decode("utf-8", "replace"), cfg.get("timeline_section"), cfg.get("section_times"))

    # photos: full-size image + the caption the site gives it
    pdir = case_dir / "photos"
    pdir.mkdir(exist_ok=True)
    cap_path = pdir / "captions.json"
    captions = json.loads(cap_path.read_text()) if cap_path.exists() else {}
    if photos:
        seen = set()
        for im in images:
            src = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", im["src"])
            name = src.rsplit("/", 1)[-1]
            if not src.startswith("http") or "logo" in name.lower() or name in seen:
                continue
            seen.add(name)
            dest = pdir / name
            if not dest.exists():
                try:
                    dest.write_bytes(http_get(src))
                except Exception as e:
                    log(f"  photo {name}: {e}")
                    continue
            if name not in captions:      # never overwrite a caption a person has edited
                stem = re.sub(r"^\d{4}-\d{2}-\d{2}[-_ ]*", "", name.rsplit(".", 1)[0]).replace("-", " ").replace("_", " ")
                generic = re.fullmatch(r"(IMG \d+|\d{2} \d{2} \d{2})", stem.strip())
                captions[name] = {"caption": im["alt"] or ("" if generic else stem), "source_url": src}
    cap_path.write_text(json.dumps(captions, indent=2, ensure_ascii=False))

    evidence = [{"id": "E001", "kind": "webpage", "title": cfg["title"] + " (case page)", "url": cfg["source_url"],
                 "sha256": sha256(body), "path": "raw/page.html"}]
    link_to_ev = {}
    urls = sorted({u for p in passages for u in p["links"]})
    for u in urls:
        ev = {"id": f"E{len(evidence) + 1:03d}", "kind": "link", "url": u, "title": re.sub(r"^https?://(www\.)?", "", u)[:70]}
        did = _drive_id(u)
        if did:
            ev["kind"] = "file"
            dest = raw / "files" / f"{ev['id']}_{did[:8]}.pdf"
            if files and not dest.exists():
                try:
                    data = http_get(f"https://drive.google.com/uc?export=download&id={did}", 180)
                    if data[:4] == b"%PDF":
                        dest.write_bytes(data)
                    else:
                        log(f"  {ev['id']}: not a direct PDF download, skipped")
                except Exception as e:  # network errors are reported, not fatal
                    log(f"  {ev['id']}: download failed ({e})")
            if dest.exists():
                ev.update(path=str(dest.relative_to(case_dir)), sha256=sha256(dest.read_bytes()),
                          bytes=dest.stat().st_size, title=f"Case file {ev['id']} (scan)")
                t = dest.with_suffix(".txt")
                if ocr and not t.exists():
                    log(f"  OCR {dest.name}")
                    _ocr(dest, t)
                if t.exists():
                    ev["text_path"] = str(t.relative_to(case_dir))
        evidence.append(ev)
        link_to_ev[u] = ev["id"]
    for p in passages:
        p["evidence"] = ["E001"] + [link_to_ev[u] for u in p["links"]]

    (case_dir / "sources").mkdir(exist_ok=True)
    (case_dir / "sources" / "passages.json").write_text(json.dumps(passages, indent=1, ensure_ascii=False))
    (case_dir / "sources" / "evidence.json").write_text(json.dumps(evidence, indent=1, ensure_ascii=False))
    log(f"{len(passages)} passages, {len(evidence)} evidence items, {len(captions)} photos")
    return passages, evidence
