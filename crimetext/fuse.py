"""Fuse per-chunk claims into one case bundle: entities, timed claims, events, photos.

The bundle is the temporal scene graph. Nodes are entities ("thing" or "stuff"), edges are
claims with a time interval, and an event is the set of claims that make up one beat of the
case. Nothing is resolved to "truth": each edge keeps its quote, passage, certainty and source.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import extract, ingest, review, scenes, timeparse
from .schema import ENTITY_TYPES, LITERAL_TYPES

IMG = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_TITLES = r"^(the|a|an|mr|mrs|ms|dr|sheriff|sgt|lt|capt|captain|detective|investigator|agent|special agent|judge|deputy)\.? "


def key(name: str) -> str:
    k = extract.norm(name)
    k = re.sub(r"[\"'().,]", "", k)
    k = re.sub(r"\b(jr|sr|inc|llc)\b", "", k)
    prev = None
    while prev != k:
        prev, k = k, re.sub(_TITLES, "", k)
    return re.sub(r"\s+", " ", k).strip()


class Entities:
    def __init__(self, manual: dict):
        self.alias = {}                       # key -> canonical key
        self.names = defaultdict(Counter)     # canonical key -> surface forms
        self.types = defaultdict(Counter)
        self.display = {}
        for canon, others in manual.items():
            self.display[key(canon)] = canon
            for o in [canon, *others]:
                self.alias[key(o)] = key(canon)

    def add(self, name, typ):
        k = self.alias.get(key(name), key(name))
        self.names[k][name.strip()] += 1
        self.types[k][typ] += 1
        return k

    def merge_people(self):
        """'Michael Wayne Short' -> 'Michael Short'; a lone first name -> the only person who has it."""
        people = [k for k in self.names if self.types[k].most_common(1)[0][0] == "PERSON"]
        weight = {k: sum(self.names[k].values()) for k in people}
        merged = {}
        people = [k for k in people if " and " not in k and " or " not in k]
        full = [k for k in people if len(k.split()) >= 2]
        for k in people:
            toks = k.split()
            if len(toks) == 1:
                cands = [f for f in full if f.split()[0] == toks[0]]
            else:
                cands = [f for f in full if f != k and f.split()[-1] == toks[-1] and f.split()[0] == toks[0]
                         and (set(f.split()) < set(toks) or set(toks) < set(f.split()))]
            cands = [c for c in cands if (weight[c], c) > (weight[k], k)]   # strict order: no merge cycles
            if len(cands) == 1 or (cands and len(toks) > 1):
                merged[k] = max(cands, key=lambda c: weight[c])
        for src, dst in merged.items():
            while dst in merged and merged[dst] != src:
                dst = merged[dst]
            if dst == src or src in self.display:
                continue
            self.names[dst].update(self.names.pop(src))
            self.types[dst].update(self.types.pop(src))
            self.alias[src] = dst
        return self

    def resolve(self, k):
        seen = set()
        while k in self.alias and self.alias[k] != k and k not in seen:
            seen.add(k)
            k = self.alias[k]
        return k


def _claim_time(c, passage):
    """A claim's own time phrase wins over its passage's date heading."""
    base = passage.get("time")
    t = c.get("time_text")
    if t:
        parsed = timeparse.parse(t)
        if parsed:
            return {k: parsed[k] for k in ("start", "end", "precision")} | {"from": "claim", "text": t}
        if base and base["precision"] == "day":             # "about 9 a.m." on a dated passage
            parsed = timeparse.parse(f"{t} {passage['date_heading']}")
            if parsed and parsed["precision"] == "minute":
                return {k: parsed[k] for k in ("start", "end", "precision")} | {"from": "claim", "text": t}
    if base:
        return dict(base) | {"from": passage.get("time_from") or "heading", "text": passage["date_heading"] or "section date"}
    return None


def build(case_dir: Path, log=print):
    cfg = json.loads((case_dir / "case.json").read_text())
    passages = json.loads((case_dir / "sources" / "passages.json").read_text())
    evidence = json.loads((case_dir / "sources" / "evidence.json").read_text())
    docs = ingest.documents(case_dir)
    passages += ingest.passages(case_dir)
    evidence += docs
    demo_path, demo_claims = case_dir / "demo" / "links.json", []
    if demo_path.exists():                      # hand-written links, always labelled as such
        demo = json.loads(demo_path.read_text())
        default_when = timeparse.parse(demo.get("date", "")) or {}
        evidence.append({"id": "DEMO", "kind": "demo", "title": "Demo links " + demo["tag"], "path": "demo/links.json", "note": demo["note"]})
        for i, c in enumerate(demo["claims"], 1):
            # a claim may carry its own "date" and "event"; otherwise the file's defaults apply
            when = timeparse.parse(c["date"]) if c.get("date") else default_when
            pid = f"x{i:04d}"
            passages.append({"id": pid, "section": "Demo links " + demo["tag"], "subsection": None, "date_heading": c.get("date") or demo.get("date"),
                             "time": {k: when[k] for k in ("start", "end", "precision")} if when else None, "time_from": "heading",
                             "depth": 0, "text": c["text"], "bold": [], "links": [], "evidence": ["DEMO"], "demo": True})
            demo_claims.append(c | {"event_title": c.get("event") or demo["event_title"], "pid": pid, "quote": c["text"], "certainty": "stated", "attributed_to": None, "demo": True})
    by_pid = {p["id"]: p for p in passages}
    ents = Entities(cfg.get("aliases", {}))

    raw_claims, raw_events, dropped = [], [], 0
    for f in sorted((case_dir / "work" / "extract").glob("chunk_*.json")):
        claims, events, problems = extract.validate(case_dir, f.name)
        dropped += sum("claim" in p for p in problems)
        raw_claims += claims
        raw_events += events

    raw_claims += demo_claims
    for title in dict.fromkeys(c["event_title"] for c in demo_claims):
        raw_events.append({"title": title, "kind": "discovery", "summary": demo["note"],
                           "pids": [c["pid"] for c in demo_claims if c["event_title"] == title], "demo": True})
    # pass 1: register every entity mention, then merge name variants
    for c in raw_claims:
        c["_s"] = ents.add(c["s"], c["s_type"])
        c["_o"] = ents.add(c["o"], c["o_type"]) if c["o_type"] in ENTITY_TYPES else None
        c["_a"] = ents.add(c["attributed_to"], "PERSON") if c.get("attributed_to") else None
    ents.merge_people()

    ids, entities = {}, []
    def ent_id(k):
        k = ents.resolve(k)
        if k not in ids:
            typ = next((t for t, _ in ents.types[k].most_common() if t in ENTITY_TYPES), "OBJECT")
            ids[k] = f"N{len(ids) + 1:04d}"
            name = ents.display.get(k) or max(ents.names[k].items(), key=lambda kv: (kv[1], len(kv[0])))[0]
            entities.append({"id": ids[k], "name": name, "type": typ, "kind": ENTITY_TYPES[typ],
                             "aliases": sorted(n for n in ents.names[k] if n != name), "n_claims": 0, "photos": [],
                             "demo": "[for demo purposes]" in name})
        return ids[k]

    claims, decisions = [], review.load(case_dir)
    threshold = cfg.get("review_threshold", review.DEFAULT_THRESHOLD)
    for c in raw_claims:
        p = by_pid[c["pid"]]
        when = _claim_time(c, p)
        conf, why = review.score(c, p, bool(when))
        k = review.claim_key(c)
        claims.append({
            "key": k, "conf": conf, "conf_why": why, "review": decisions.get(k), "demo": bool(c.get("demo")),
            "id": f"C{len(claims) + 1:05d}", "pid": c["pid"], "s": ent_id(c["_s"]), "p": c["p"],
            "p_text": c.get("p_text"), "o": ent_id(c["_o"]) if c["_o"] else None,
            "literal": None if c["_o"] else c["o"], "o_type": c["o_type"], "quote": c["quote"],
            "time": when, "certainty": c["certainty"],
            "by": ent_id(c["_a"]) if c["_a"] else None, "evidence": p.get("evidence", []), "events": [],
        })
    emap = {e["id"]: e for e in entities}
    for c in claims:
        emap[c["s"]]["n_claims"] += 1
        if c["o"]:
            emap[c["o"]]["n_claims"] += 1

    # events: the extractor's beats, plus one per date heading the extractor did not cover
    by_pid_claims = defaultdict(list)
    for c in claims:
        by_pid_claims[c["pid"]].append(c)
    events, covered = [], set()
    for e in raw_events:
        covered.update(e["pids"])
        events.append({"title": e["title"].strip(), "kind": e["kind"], "summary": e.get("summary", ""), "pids": e["pids"],
                       "demo": bool(e.get("demo"))})
    leftover = defaultdict(list)
    for p in passages:
        if p["id"] not in covered and by_pid_claims[p["id"]]:
            leftover[p["date_heading"] or p["subsection"] or p["section"]].append(p["id"])
    for heading, pids in leftover.items():
        events.append({"title": heading, "kind": "investigation", "summary": "", "pids": pids})
    out_events = []
    for e in events:
        times = [by_pid[p]["time"] for p in e["pids"] if by_pid[p].get("time")]
        cl = [c for p in e["pids"] for c in by_pid_claims[p]]
        if not cl:
            continue
        # an event with no dated passage is kept as "undated": analysis, theories, profiles
        e["time"] = {"start": min(t["start"] for t in times), "end": max(t["end"] for t in times)} if times else None
        e["headings"] = sorted({by_pid[p]["date_heading"] for p in e["pids"] if by_pid[p]["date_heading"]})
        out_events.append(e)
    out_events.sort(key=lambda e: (e["time"]["start"] if e["time"] else "9999", e["pids"][0]))
    for i, e in enumerate(out_events, 1):
        e["id"] = f"V{i:03d}"
        e["claims"] = []
        for p in e["pids"]:
            for c in by_pid_claims[p]:
                c["events"].append(e["id"])
                e["claims"].append(c["id"])

    # photos: caption -> entities named in it; date from the file name
    photos, pdir = [], case_dir / "photos"
    cap_path = pdir / "captions.json"
    captions = json.loads(cap_path.read_text()) if cap_path.exists() else {}
    names = sorted(((n, e["id"]) for e in entities for n in [e["name"], *e["aliases"]]
                    if len(n) > 3 and e["type"] in ("PERSON", "LOCATION", "VEHICLE", "GROUP")), key=lambda x: -len(x[0]))
    for f in sorted(pdir.iterdir()) if pdir.exists() else []:
        if f.suffix.lower() not in IMG:
            continue
        meta = captions.get(f.name, {})
        cap = meta.get("caption") or "Uncaptioned photo (" + f.name + ")"
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", f.name)
        if not m or m[1] >= "2020":                      # upload-date file names are not capture dates
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", cap)
        linked, low = [], extract.norm(cap)
        for n, eid in names:
            if re.search(r"\b" + re.escape(extract.norm(n)) + r"\b", low) and eid not in linked:
                linked.append(eid)
        ph = {"file": f.name, "caption": cap, "date": f"{m[1]}-{m[2]}-{m[3]}" if m and m[1] < "2020" else None,
              "entities": linked, "source_url": meta.get("source_url")}
        photos.append(ph)
        for eid in linked:
            emap[eid]["photos"].append(f.name)

    used = {c["pid"] for c in claims}
    for p in passages:
        p["n_claims"] = len(by_pid_claims[p["id"]])
    bundle = {
        "case": cfg,
        "stats": {"passages": len(passages), "passages_with_claims": len(used), "claims": len(claims),
                  "claims_dropped_ungrounded_or_invalid": dropped, "entities": len(entities),
                  "events": len(out_events), "timed_claims": sum(1 for c in claims if c["time"]),
                  "photos": len(photos), "evidence": len(evidence), "documents": len(docs),
                  "demo_claims": len(demo_claims),
                  "chunks": len(list((case_dir / "work" / "chunks").glob("chunk_*.json"))),
                  "chunks_extracted": len(list((case_dir / "work" / "extract").glob("chunk_*.json")))},
        "review": {"threshold": threshold, "decided": len(decisions),
                   "below_threshold": sum(1 for c in claims if c["conf"] < threshold)},
        "scenes": scenes.load_all(case_dir), "documents": docs, "doc_types": ingest.DOC_TYPES,
        "evidence": evidence, "passages": passages, "entities": entities, "claims": claims,
        "events": out_events, "photos": photos,
    }
    out = case_dir / "build"
    out.mkdir(exist_ok=True)
    (out / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False))
    log(json.dumps(bundle["stats"]))
    return bundle
