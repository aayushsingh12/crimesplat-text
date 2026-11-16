"""Official documents added to a case after the first fetch: witness statements, police reports,
lab reports, court papers.

An upload is stored unmodified under documents/ with its SHA-256, its text is cut into numbered
passages, and those passages wait in their own extraction chunk. Nothing enters the graph until
the extractor has run on that chunk and the claims have passed the quote check.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from . import timeparse

DOC_TYPES = ["witness_statement", "police_report", "scene_examination", "lab_report", "medical_report",
             "court_document", "news_article", "other"]
TEXT_EXT = (".txt", ".md")


def _index(case_dir: Path) -> list:
    p = case_dir / "documents" / "index.json"
    return json.loads(p.read_text()) if p.exists() else []


def _text_of(path: Path) -> str:
    if path.suffix.lower() in TEXT_EXT:
        return path.read_text(errors="replace")
    if path.suffix.lower() == ".pdf":
        txt = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True).stdout
        if len(txt.strip()) > 100:
            return txt
        from .fetch import _ocr                      # scanned PDF: OCR the first pages
        out = path.with_suffix(".ocr.txt")
        _ocr(path, out, pages=8)
        return out.read_text()
    raise ValueError("supported document types: .txt, .md, .pdf")


def add_document(case_dir: Path, filename: str, data: bytes, title="", doc_type="other", date="", author="") -> dict:
    d = case_dir / "documents"
    d.mkdir(exist_ok=True)
    idx = _index(case_dir)
    sha = hashlib.sha256(data).hexdigest()
    if any(x["sha256"] == sha for x in idx):
        raise ValueError("this exact file is already in the case")
    doc_id = f"D{len(idx) + 1:03d}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)[:80] or "document.txt"
    path = d / f"{doc_id}_{safe}"
    path.write_bytes(data)
    text = _text_of(path)
    when = timeparse.parse(date) if date else None
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    title = title.strip() or safe
    passages = [{
        "id": f"{doc_id.lower()}-{i:04d}", "section": f"Document: {title}", "subsection": doc_type.replace("_", " "),
        "date_heading": when["text"] if when else None,
        "time": {k: when[k] for k in ("start", "end", "precision")} if when else None, "time_from": "heading" if when else None,
        "depth": 0, "text": p, "bold": [], "links": [], "evidence": [doc_id],
    } for i, p in enumerate((p for p in paras if len(p) > 25), 1)]
    entry = {"id": doc_id, "kind": "document", "doc_type": doc_type if doc_type in DOC_TYPES else "other", "title": title,
             "author": author, "date": date, "path": str(path.relative_to(case_dir)), "sha256": sha, "bytes": len(data),
             "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_passages": len(passages)}
    (d / f"{doc_id}.passages.json").write_text(json.dumps(passages, indent=1, ensure_ascii=False))
    idx.append(entry)
    (d / "index.json").write_text(json.dumps(idx, indent=1, ensure_ascii=False))
    chunks = case_dir / "work" / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    for n in range(0, len(passages), 28):      # one or more extraction chunks for this document only
        part = [{k: p[k] for k in ("id", "section", "subsection", "date_heading", "text")} for p in passages[n:n + 28]]
        (chunks / f"chunk_{doc_id.lower()}_{n // 28 + 1:02d}.json").write_text(json.dumps({"passages": part}, indent=1, ensure_ascii=False))
    return entry


def documents(case_dir: Path) -> list:
    """Index entries with their extraction state."""
    out = []
    for e in _index(case_dir):
        chunks = sorted((case_dir / "work" / "chunks").glob(f"chunk_{e['id'].lower()}_*.json"))
        done = [c for c in chunks if (case_dir / "work" / "extract" / c.name).exists()]
        out.append(e | {"chunks": len(chunks), "chunks_extracted": len(done),
                        "state": "in graph" if chunks and len(done) == len(chunks) else "awaiting extraction"})
    return out


def passages(case_dir: Path) -> list:
    out = []
    for e in _index(case_dir):
        p = case_dir / "documents" / f"{e['id']}.passages.json"
        if p.exists():
            out += json.loads(p.read_text())
    return out


def save_media(case_dir: Path, sub: str, filename: str, data: bytes, allowed: tuple) -> dict:
    """Store a photo or video unmodified with its hash. Used for case photos, scene photos and footage."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)[:100]
    if not safe.lower().endswith(allowed):
        raise ValueError(f"allowed file types: {', '.join(allowed)}")
    d = case_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / safe).write_bytes(data)
    rec = {"file": safe, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "added_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    log = d / "uploads.jsonl"
    with log.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec
