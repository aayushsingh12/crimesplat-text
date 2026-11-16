# Phase 1 — Text Processing Pipeline: Technologies & Implementation

Status: design draft, pre-implementation. Owner: Workstream W1 (Aayush K. Singh), per
`imp_docs/cross_team_agentic_dev_plan.md`. This document is standalone — it should be
readable by someone with no prior context on the project.

Covers Step 1 of the 8-step pipeline: turning raw witness statements and police reports
into OKF claim bundles, ready for fusion (Step 4). Nothing in this document depends on the
image or video pipelines existing.

---

## 1. Goal

Take unstructured text (witness statements, police reports) and produce a set of typed,
timestamped, confidence-scored **claims** — subject–predicate–object triplets about
entities and their relations — written out as OKF bundle files under
`okf/claims/text/`, per the shared contract in `pipelines/shared/okf_schema/`.

This pipeline does **not** decide what's true. It only extracts what a given source
*claims*. Resolution across sources happens later, in fusion (Step 4, owned by W4).

## 2. Why this is the first workstream to build

- No dependency on image/video pipelines, Neo4j, or fusion logic — it can be built and
  validated entirely on its own.
- Cheapest to iterate on: no GPU-heavy training, fast feedback loop between a change and
  seeing its effect on output quality.
- Already has a working prototype from Phase 2 (BERTScore 0.7945 on a Mumbai-attack news
  case study), so this phase is about hardening that prototype into something that emits
  contract-compliant OKF bundles, not starting from zero.

## 3. Pipeline stages

### 3.1 Entity extraction — BERT-NER

**Technology**: a BERT-based Named Entity Recognition model (e.g. `dslim/bert-base-NER` or
a domain-adapted checkpoint, via Hugging Face `transformers`).

Extracts typed entity spans directly from raw text. No separate LLM restructuring pass —
BERT-NER's output is the entity layer the rest of the pipeline builds on.

**Entity types** (the taxonomy, to be finalized but starting point below):

| Type | Examples |
|---|---|
| `PERSON` | "the suspect", "witness B", a named individual |
| `WEAPON` | "AK-47", "kitchen knife" |
| `LOCATION` | "the alley", "Chhatrapati Shivaji Terminus" |
| `ORGANISATION` | "Lashkar-e-Taiba", "Springfield PD" |
| `DATETIME` | "Thursday", "earlier this week", explicit timestamps |
| `OBJECT` | generic physical objects not covered above (backpack, vehicle, etc.) |
| `EMOTION` / `ATTRIBUTE` | descriptive qualifiers attached to a PERSON or OBJECT span |

Each extracted span carries the model's own token-level confidence score, which becomes
the starting point for the claim's `confidence` value (see 3.4).

### 3.2 Relation construction

**Technology**: dependency parsing (spaCy) or a rule-based clause-linking pass over
BERT-NER's output — not a separate LLM call.

Entities that co-occur within the same sentence/clause are linked into a
subject–predicate–object triplet, with the predicate derived from the connecting
verb/phrase (e.g. "The suspect fled toward the alley" →
`(suspect, FLED_TOWARD, alley)`). This is the step that turns a flat list of typed spans
into an actual relational claim.

Where a sentence contains more than two entities or an ambiguous predicate, prefer
producing multiple lower-confidence claims over one falsely-confident triplet — ambiguity
here is exactly what the low-confidence review queue (Section 5) exists for.

### 3.3 Temporal normalization

**Technology**: a temporal-expression parser (e.g. `dateparser`, or a rule-based normalizer
for common forensic-report phrasing) applied to `DATETIME` spans and to any relative time
language governing a sentence/clause ("shortly after", "earlier this week").

Produces `t_start`/`t_end` for each claim:
- An explicit date/time → `t_start == t_end` (a point).
- A vague or relative expression → a widened interval reflecting the actual uncertainty
  (e.g. "earlier this week" relative to a document dated Nov 26 → an interval spanning the
  few days prior), rather than fabricating false precision.
- No temporal information available in context → both fields left null; the claim is still
  written, just without a time anchor (fusion may later infer one via alignment with other
  modalities).

### 3.4 Confidence scoring

Each claim's `confidence` is derived from:
- the BERT-NER token-level confidence of its constituent entity spans, and
- a penalty applied when the relation-construction step (3.2) had to pick between multiple
  plausible predicates/structures for the same sentence.

`confidence_tier` is fixed at `"narrative"` for every claim this pipeline produces — text
is always the lowest-trust modality per the project's modality reliability hierarchy,
regardless of how confident the extraction itself was. (`confidence_tier` says *how much to
trust this kind of source*; `confidence` says *how sure the extractor is that it read this
source correctly*. They are independent.)

If `confidence` falls below the extraction threshold (starting value: **0.6**, per
`cross_team_agentic_dev_plan.md` Section 3), the pipeline additionally writes a note into
`okf/review/` flagging the claim for human sanity-check before fusion touches it. The claim
itself is still written to `okf/claims/text/` regardless — being below threshold doesn't
mean discard, it means flag.

### 3.5 OKF bundle output

Every claim is written as one markdown+YAML file into `okf/claims/text/`, matching the
shared contract exactly:

```yaml
---
type: Claim
source_modality: text
source_id: witness_B_statement_2026-08-20
raw_label: "the man in the alley"
confidence_tier: narrative
confidence: 0.74
extracted_at: 2026-08-23T18:40:00Z
predicate: FLED_TOWARD
target_claim_id: claim_loc_00417
t_start: 2026-08-20T20:04:00Z
t_end: 2026-08-20T20:06:00Z
---
"...the man in the alley ran toward the parking lot moments after the shot..."
```

The body is the supporting excerpt from the source text — kept for human review and audit,
not parsed programmatically downstream.

## 4. Technology stack

| Component | Technology | Purpose |
|---|---|---|
| Entity extraction | BERT-NER (Hugging Face `transformers`) | typed entity span extraction |
| Relation construction | spaCy dependency parser / rule-based clause linking | building subject–predicate–object triplets |
| Temporal normalization | `dateparser` / rule-based normalizer | resolving relative time expressions into `t_start`/`t_end` |
| Evaluation | BERTScore | measuring semantic fidelity of extracted claims against source text |
| Output format | OKF (markdown + YAML frontmatter) | portable, git-trackable claim bundles |
| Runtime | Python | pipeline implementation language |

Deliberately **not** using an LLM (e.g. Gemini) as a structuring step in this revision —
the earlier design had Gemini turn NER output into typed scene-graph triplets; the current
design does that mapping directly and deterministically from BERT-NER + dependency parsing,
keeping the pipeline auditable and removing an external API dependency from the critical
path. This can be revisited if BERT-NER + rule-based relation construction proves
insufficient on real forensic report language.

## 5. Low-confidence handling

This pipeline participates in the shared review-queue contract described in
`cross_team_agentic_dev_plan.md` Section 3. Concretely, for W1:

- Extraction threshold: **0.6**.
- Below threshold → claim is still written to `okf/claims/text/`, plus a `ReviewItem` file
  is written to `okf/review/` with `stage: extraction`, the claim id, the confidence score,
  and a short reason (e.g. "ambiguous predicate between two plausible readings of this
  clause").
- This pipeline never resolves conflicts between multiple text sources itself (e.g. two
  witnesses disagreeing) — that's fusion's job (Step 4 / W4). W1 only ever emits claims,
  never resolved entities.

## 6. Directory structure

```
pipelines/text/
├── extract_entities.py      # BERT-NER wrapper
├── build_relations.py        # dependency parsing / clause-linking → triplets
├── normalize_time.py          # temporal expression resolution
├── emit_okf.py                 # writes claim + review files matching the shared schema
├── evaluate.py                  # BERTScore evaluation harness
├── tests/
│   └── test_okf_conformance.py  # validates emitted bundles against pipelines/shared/okf_schema/
└── README.md
```

## 7. Validation before this workstream is considered done

1. **Schema conformance**: every emitted file in `okf/claims/text/` validates against
   `pipelines/shared/okf_schema/`. Run as part of CI, not manually.
2. **Semantic fidelity**: BERTScore (or equivalent) run against a held-out set of
   labeled/known-correct claims, tracking precision/recall/F1 — the Phase 2 prototype's
   0.7945 F1 is the baseline to match or beat.
3. **Review-queue behavior**: a synthetic low-confidence input actually produces a
   `ReviewItem` file in `okf/review/`, not a silently-dropped or silently-promoted claim.
4. **No resolution logic present**: confirm this pipeline never writes to `okf/resolved/`
   or attempts to merge/deduplicate entities across sources — that boundary belongs to W4
   only.

## 8. Open items

- Finalize the entity type taxonomy (Section 3.1) — current list is a starting point, not
  final.
- Decide whether `dateparser` alone is sufficient for forensic-report time phrasing or
  whether a custom rule set is needed.
- Confirm the extraction confidence threshold (0.6) against real data once a larger
  evaluation set exists — currently carried over from the cross-team plan's starting
  proposal, not independently validated for text specifically.
- `pipelines/shared/okf_schema/` needs to exist as an actual file before `emit_okf.py` and
  its conformance test can be implemented.
