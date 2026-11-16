"""Claim confidence and the human review record.

Confidence is a transparent rule score, not a model probability. It starts from how strongly the
passage words the claim and loses points for things a reviewer would want to look at. Claims
under the case's threshold wait for a person. Decisions are stored by a content key, so they
survive a rebuild or a re-extraction that produces the same claim.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

BASE = {"stated": 0.90, "reported": 0.72, "alleged": 0.52, "speculated": 0.38}
DEFAULT_THRESHOLD = 0.70
_VAGUE = re.compile(r"\b(unidentified|unknown|unnamed|someone|anyone|person or persons|several|multiple|people who)\b", re.I)
_STOP = {"the", "and", "from", "with", "that", "this", "short", "county", "office", "home"}


def claim_key(c: dict) -> str:
    raw = "|".join(str(c.get(k, "")) for k in ("pid", "s", "p", "o", "quote"))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _mentioned(name: str, text: str) -> bool:
    toks = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) > 3 and t not in _STOP]
    return not toks or any(t in text for t in toks)


def score(c: dict, passage: dict, timed: bool):
    """Return (confidence 0..1, [reasons]). `c` is a raw extracted claim."""
    if c.get("demo"):
        return 1.0, ["hand-written demo link: not from the case file, not scored"]
    conf, why = BASE.get(c.get("certainty"), 0.9), [f"wording is '{c.get('certainty')}'"]
    text, quote = passage["text"].lower(), (c.get("quote") or "").lower()

    def cut(amount, reason):
        nonlocal conf
        conf -= amount
        why.append(f"-{amount:.2f} {reason}")

    if not _mentioned(c["s"], text):
        cut(0.15, "subject is not named in the passage (resolved from context)")
    elif not _mentioned(c["s"], quote):
        cut(0.04, "subject is named in the passage but not in the quote")
    if not _mentioned(c["o"], text):
        cut(0.15, "object is not named in the passage")
    if _VAGUE.search(c["s"]) or _VAGUE.search(c["o"]):
        cut(0.08, "an unnamed or collective party is involved")
    if c.get("p") == "OTHER":
        cut(0.06, "relation is outside the fixed vocabulary")
    if c.get("p") in ("KILLED", "SHOT", "ATTACKED", "ABDUCTED", "THREATENED", "SUSPECTED_OF", "CHARGED_WITH", "ARRESTED"):
        cut(0.10, "accusatory relation: always worth a human look")
    if not timed:
        cut(0.05, "no date for this claim")
    if len(quote.split()) < 4:
        cut(0.05, "very short quote")
    return round(max(0.05, min(0.99, conf)), 2), why


def load(case_dir: Path) -> dict:
    p = case_dir / "review" / "decisions.json"
    return json.loads(p.read_text()) if p.exists() else {}


def decide(case_dir: Path, key: str, decision: str, note: str = "", reviewer: str = "") -> dict:
    """decision: accepted | rejected | reset. Appends to an audit log as well as the current state."""
    if decision not in ("accepted", "rejected", "reset"):
        raise ValueError("decision must be accepted, rejected or reset")
    d = case_dir / "review"
    d.mkdir(exist_ok=True)
    state = load(case_dir)
    entry = {"decision": decision, "note": note[:500], "reviewer": reviewer[:80],
             "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if decision == "reset":
        state.pop(key, None)
    else:
        state[key] = entry
    (d / "decisions.json").write_text(json.dumps(state, indent=1, ensure_ascii=False))
    with (d / "log.jsonl").open("a") as f:
        f.write(json.dumps({"key": key} | entry, ensure_ascii=False) + "\n")
    return entry
