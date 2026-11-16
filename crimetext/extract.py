"""Chunk passages, run the LLM extraction, and check every claim against its passage.

Backends: "claude-cli" (headless `claude -p`), "ollama" (local model), or "files" (chunks are
filled in by an external agent that writes work/extract/chunk_NNN.json). The validator is the
same for all of them: a claim survives only if its quote is a verbatim substring of its passage.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from .schema import CERTAINTY, ENTITY_TYPES, EVENT_KINDS, LITERAL_TYPES, PREDICATES

PROMPT = (Path(__file__).parent / "prompt.md").read_text()


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def is_content(p) -> bool:
    return p["section"] not in ("Summary",) or ":" in p["text"]


def make_chunks(case_dir: Path, size=28):
    passages = [p for p in json.loads((case_dir / "sources" / "passages.json").read_text()) if is_content(p)]
    out = case_dir / "work" / "chunks"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("chunk_*.json"):
        f.unlink()
    chunks, cur = [], []
    for p in passages:
        # keep a date heading's passages together where possible
        if len(cur) >= size and (not cur or p["date_heading"] != cur[-1]["date_heading"] or len(cur) >= size + 12):
            chunks.append(cur)
            cur = []
        cur.append({k: p[k] for k in ("id", "section", "subsection", "date_heading", "text")})
    if cur:
        chunks.append(cur)
    for i, c in enumerate(chunks, 1):
        (out / f"chunk_{i:03d}.json").write_text(json.dumps({"passages": c}, indent=1, ensure_ascii=False))
    return len(chunks)


def validate(case_dir: Path, name: str, fix=False):
    """Return (kept claims, kept events, problems). Problems are strings an extractor can act on."""
    chunk = json.loads((case_dir / "work" / "chunks" / name).read_text())
    by_id = {p["id"]: p for p in chunk["passages"]}
    path = case_dir / "work" / "extract" / name
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        return [], [], [f"{name}: not valid JSON ({e})"]
    problems, claims = [], []
    for i, c in enumerate(data.get("claims", [])):
        tag = f"claim {i} ({c.get('pid')}, {c.get('s')} {c.get('p')} {c.get('o')})"
        p = by_id.get(c.get("pid"))
        if not p:
            problems.append(f"{tag}: pid not in this chunk"); continue
        if not c.get("s") or not c.get("o"):
            problems.append(f"{tag}: empty subject or object"); continue
        if c.get("p") not in PREDICATES:
            problems.append(f"{tag}: predicate not in the allowed list"); continue
        if c.get("s_type") not in ENTITY_TYPES:
            problems.append(f"{tag}: bad s_type {c.get('s_type')}"); continue
        if c.get("o_type") not in ENTITY_TYPES and c.get("o_type") not in LITERAL_TYPES:
            problems.append(f"{tag}: bad o_type {c.get('o_type')}"); continue
        q = norm(c.get("quote") or "")
        if len(q.split()) < 2 or q not in norm(p["text"]):
            problems.append(f"{tag}: UNGROUNDED quote {c.get('quote')!r} is not in passage text {p['text']!r}"); continue
        if c.get("certainty") not in CERTAINTY:
            c["certainty"] = "stated"
        claims.append(c)
    events = []
    for e in data.get("events", []):
        pids = [x for x in e.get("pids", []) if x in by_id]
        if pids and e.get("title"):
            e["pids"] = pids
            e["kind"] = e.get("kind") if e.get("kind") in EVENT_KINDS else "investigation"
            events.append(e)
        else:
            problems.append(f"event {e.get('title')!r}: no valid pids")
    return claims, events, problems


# ---- LLM backends -------------------------------------------------------------------------

def _parse_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def call_llm(backend: str, model: str, user: str) -> str:
    if backend == "claude-cli":
        r = subprocess.run(["claude", "-p", "--model", model, "--output-format", "json", "--append-system-prompt", PROMPT],
                           input=user, capture_output=True, text=True, timeout=900)
        d = json.loads(r.stdout)
        if d.get("is_error"):
            raise RuntimeError(d.get("result"))
        return d["result"]
    if backend == "ollama":
        body = json.dumps({"model": model, "stream": False, "format": "json",
                           "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request("http://localhost:11434/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            return json.loads(r.read())["message"]["content"]
    raise ValueError(f"unknown backend {backend}")


def run(case_dir: Path, backend="claude-cli", model="haiku", force=False, log=print):
    out = case_dir / "work" / "extract"
    out.mkdir(parents=True, exist_ok=True)
    for chunk in sorted((case_dir / "work" / "chunks").glob("chunk_*.json")):
        dest = out / chunk.name
        if dest.exists() and not force:
            continue
        if backend == "files":
            log(f"{chunk.name}: waiting for an external extractor"); continue
        user = "Passages:\n" + chunk.read_text()
        for attempt in range(3):
            data = _parse_json(call_llm(backend, model, user))
            if data is None:
                continue
            dest.write_text(json.dumps(data, indent=1, ensure_ascii=False))
            _, _, problems = validate(case_dir, chunk.name)
            bad = [p for p in problems if "UNGROUNDED" in p]
            if not bad:
                break
            user = ("Passages:\n" + chunk.read_text() + "\n\nYour previous output had ungrounded quotes. "
                    "Return the full corrected JSON.\n" + "\n".join(bad[:30]))
        log(f"{chunk.name}: done")


if __name__ == "__main__":      # python -m crimetext.extract <case_dir> <chunk_NNN.json>
    case, name = Path(sys.argv[1]), sys.argv[2]
    claims, events, problems = validate(case, name)
    print(f"{name}: {len(claims)} grounded claims, {len(events)} events, {len(problems)} problems")
    for p in problems:
        print("  -", p)
    sys.exit(1 if problems else 0)
