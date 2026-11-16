"""The investigator's own working record: actions, notes, hypotheses, dismissed comparison items.

Kept apart from the case graph on purpose. The graph is what sources say; this is what the
investigator thinks and plans. Stored as plain JSON under casework/, with an append-only log.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

KINDS = ("tasks", "notes", "hypotheses", "dismissed")


def load(case_dir: Path) -> dict:
    out = {}
    for k in KINDS:
        p = case_dir / "casework" / f"{k}.json"
        out[k] = json.loads(p.read_text()) if p.exists() else []
    return out


def save(case_dir: Path, kind: str, items: list, who: str = "", what: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError("kind must be one of " + ", ".join(KINDS))
    if not isinstance(items, list) or len(json.dumps(items)) > 2_000_000:
        raise ValueError("items must be a list of reasonable size")
    d = case_dir / "casework"
    d.mkdir(exist_ok=True)
    (d / f"{kind}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    with (d / "log.jsonl").open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "who": who[:80], "what": what[:200],
                            "count": len(items)}, ensure_ascii=False) + "\n")
    return {"kind": kind, "count": len(items)}
