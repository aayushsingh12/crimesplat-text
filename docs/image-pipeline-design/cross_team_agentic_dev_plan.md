# Crime Scene Reconstruction — Full Pipeline & Cross-Team Agentic Development Plan

Status: design draft, pre-implementation.

This document is meant to be readable standalone — by a teammate, a reviewer, or a future
agent session with no prior context. It covers, in order:

1. What the system does and why it's built the way it is
2. The full 8-step pipeline, in detail, end to end
3. The OKF ground-truth + low-confidence escalation system (new in this revision)
4. The Neo4j schema the pipeline writes into (summarized here; full detail in
   `imp_docs/neo4j_schema.md`)
5. How the 4-person team splits this into independently buildable workstreams
6. The contracts each workstream must honor so the pieces integrate without a big-bang merge
7. Repo structure, agent-scoping guidance, and integration checkpoints

---

## 1. What the system is

**Crime Scene Reconstruction using Scene Graphs** takes three kinds of raw evidence —
witness statements/police reports (text), crime-scene photographs (images), and CCTV/
bodycam footage (video) — and turns them into one queryable, time-aware knowledge
structure plus a navigable 3D reconstruction of the scene, segmented by the actual "beats"
of the incident (entry, confrontation, exit, etc.).

Three design principles shape every decision below:

- **Modular, late fusion, not one monolithic model.** Text, image, and video are processed
  by independent, swappable extractors. They only combine at the graph level. This means a
  better object detector or a compliance-flagged model can be swapped without retraining
  anything else, and it's why the team can build all three extractors in parallel.
- **Provenance over confidence-blending.** Nothing in the graph is silently averaged away.
  Every fact keeps a pointer to exactly which source produced it and why it was trusted (or
  not), because a forensic system has to be able to justify its conclusions, not just state
  them.
- **Everything is a timestamped hypothesis, not ground truth.** Every node and edge in the
  fused graph carries a time interval and a confidence value. This is what makes the final
  structure a *panoptic 4D scene graph* rather than a plain scene graph: time is a first-class
  property of facts, not metadata bolted on afterward.

---

## 2. The 8-step pipeline, in detail

### Step 1 — Text pipeline (witness statements, police reports)

**Input**: raw unstructured text documents.
**Output**: a set of typed, timestamped claims about entities and their relations.

Flow: raw text → **BERT-NER** extracts typed entity spans directly — Person, Weapon,
Location, Organisation, Date/Time, Emotion/Attribute. These typed spans are mapped
straight into scene-graph claims (subject–predicate–object triplets), without an
intermediate LLM-restructuring pass: entities that co-occur within the same
sentence/clause are linked via a relation inferred from the connecting verb/phrase, and
each resulting triplet is timestamped using whatever temporal expression governs that part
of the text (explicit date/time, or a normalized relative expression like "shortly after
8pm").

Every claim produced here is tagged:
- `source_modality: "text"`
- `confidence_tier: "narrative"` (the lowest of the three tiers — witness/report text is
  inherently the least reliable relative to sensor data, per the modality reliability
  hierarchy)
- `source_id`: which witness/report it came from

**Status**: prototyped in Phase 2 (BERTScore 0.7945 on a Mumbai-attack news case study),
rendered as a timeline-scrubbable graph. Production version needs to: (a) finalize the
entity/relation type taxonomy, (b) build the triplet-construction logic from raw NER spans
(currently semi-manual in the prototype), (c) emit output as OKF bundles (see Section 3)
instead of directly to a visualization layer.

### Step 2 — Image pipeline (crime-scene photographs)

**Input**: a set of static photographs of the scene.
**Output**: a static 3D Gaussian Splat asset, plus (where possible) claims about visible
objects/relations at capture time.

Flow: photos → **COLMAP** (structure-from-motion: recovers camera poses + a sparse point
cloud from image feature matches) → **3D Gaussian Splatting** (trained via
Splatfacto/nerfstudio, ~30k iterations) → a static `.ply` splat asset representing the
scene's geometry as it appeared at the time the photos were taken.

A critical preprocessing detail already validated in Phase 2: mixed portrait/landscape
camera metadata breaks COLMAP's feature registration unless EXIF-aware auto-orientation is
applied (with `--ImageReader.single_camera 0`). This alone improved feature registration
from 56.67% to 83.33%, and downstream splat quality (SSIM) from 0.43 to 0.60, on the
Katsos et al. forensic photogrammetry benchmark — the only public dataset of its kind.

This pipeline produces **geometry only** by default. To also produce semantic claims (e.g.
"knife on floor near table") for fusion, a relational image-captioning step (BLIP /
Instruct-BLIP) needs to run over the same photos and emit claims the same way Step 1 does,
tagged:
- `source_modality: "image"`
- `confidence_tier: "visual"`

**Status**: the geometry half (COLMAP → 3DGS) is prototyped and benchmarked in Phase 2. The
semantic-claim half (BLIP-style relational captioning → OKF claims) is not yet built.

### Step 3 — Video pipeline (CCTV / bodycam footage)

**Input**: video files.
**Output**: a time-continuous set of tracked-entity claims (who/what was where, doing what,
across a time range — not just per-frame), plus splat assets for scenes with moving
cameras.

Flow: video → **OpenCV** frame extraction → **YOLOv8** object detection per frame →
**DeepSORT** for identity-consistent multi-object tracking across frames (this is what
lets the system say "this is the same person 3 seconds later" instead of treating every
frame as a disconnected detection) → a spatiotemporal relation-generation step (ideally
PSG4DFormer-style, producing continuous "feature tubes": e.g.
`(Person_1, holding, Knife_2, t=00:05:00–00:05:12)` that survive occlusion, rather than a
disconnected graph per frame).

This is the hardest and least mature piece of the whole system. PSG4D (4D Panoptic Scene
Graph generation) is itself a recent research task (2025 CVPR reference in the project's
literature review) with no turnkey production model. Recommended build order: ship an MVP
using YOLOv8 + DeepSORT + a lightweight custom relation classifier first (co-occurrence +
simple spatial-relation rules between tracked boxes), then evaluate upgrading to a full
PSG4DFormer-style model once the MVP proves the rest of the pipeline end-to-end.

Video frames also independently feed the splat pipeline (COLMAP + 3DGS, same as Step 2)
for bodycam scenes with a moving camera.

Claims from this pipeline are tagged:
- `source_modality: "video"`
- `confidence_tier: "sensor"` (the highest tier — direct sensor footage outranks both
  narrative text and even static images, since it captures continuous motion/causality)
- `source_id`: video file / camera id
- an additional `feature_tube_id` linking together claims that are really one continuous
  tracked relation across multiple frames

**Status**: not yet built. This is the workstream to start earliest given its difficulty
(see Section 5).

### Step 4 — Fusion layer (OKF-mediated ground truth + conflict resolution)

**Input**: OKF claim bundles from Steps 1–3 (independent, unaligned, potentially
contradictory).
**Output**: a single resolved set of canonical entities/events, written as `:Entity`,
`:Event`, and `:RESOLVED_FROM` records ready for Neo4j ingestion (Step 5). Anything the
fusion agent isn't confident about is *not* silently resolved — it's routed into a
low-confidence review file instead. See Section 3 for the full mechanism.

At a high level, fusion does three things:

1. **Entity alignment** — matching claims from different modalities that refer to the same
   real-world entity (e.g. video's `Person_ID_42` and text's "the suspect"). This is done
   via similarity matching over claim descriptions/labels (embedding-based nearest-neighbor
   matching over `raw_label` text, plus spatial/temporal co-occurrence as a strong prior —
   e.g. an entity claimed to be at the same location within the same time window across two
   modalities is a much stronger match candidate than label similarity alone).
2. **Temporal alignment** — normalizing all claims onto one absolute timeline. Text
   timestamps are frequently coarse or relative; video/image timestamps are precise (frame
   number / file metadata). The fusion agent anchors relative text expressions to the
   absolute video timeline where possible, and represents any remaining imprecision as a
   wider `t_start`/`t_end` interval rather than a false point-in-time.
3. **Conflict resolution** — when aligned claims disagree (witness says "he had a gun,"
   video shows a knife), the fusion agent applies the confidence-tier hierarchy
   (`sensor > visual > narrative`) as the primary rule, but **only commits a resolution when
   its confidence in that resolution clears a threshold**. Below threshold, nothing is
   silently decided — see Section 3.

**Status**: not yet built. Depends on at least one modality's OKF output existing to
develop and test against (recommend text, since it's cheapest/fastest to produce).

### Step 5 — Master/Global Scene Graph → Neo4j

**Input**: resolved entities/events/relations from Step 4.
**Output**: the single Neo4j graph every downstream step reads from.

The OKF-resolved output (canonical `:Entity` and `:Event` nodes, `:RESOLVED_FROM` edges
back to the `:Claim`s that produced them, dynamic-predicate relationship edges like
`:HOLDING`/`:ATTACKED` carrying `t_start`/`t_end`/`confidence`) is written into Neo4j. This
is the **only** place resolved facts get written — no other pipeline stage writes `:Entity`
or `:Event` nodes directly. Full schema: `imp_docs/neo4j_schema.md`.

**Status**: not yet built. Should be built and tested against Step 1's output alone first
(single-modality ingestion, no real conflicts to resolve yet), before Step 4's fusion logic
is layered on top — this validates the write path independently of resolution correctness.

### Step 6 — Digital twin / scene reconstruction (QuerySplat, action-point segmentation)

**Input**: splat assets from Steps 2/3, plus the populated Neo4j graph (specifically
`:Event` nodes and their time intervals).
**Output**: one `:Scene` (rendered splat) per action point of the incident, not one
continuous reconstruction.

Crime-scene photos and/or extracted video frames are fed into **QuerySplat** to generate
the navigable 3D scene(s). Rather than building a single monolithic reconstruction, the
timeline is segmented into discrete **action points** — "Entry," "Confrontation," "Weapon
Drawn," "Exit," etc. — each becoming its own `:Scene` node, keyed to the `:Event` it
depicts via `t_start`/`t_end`. Which frames/photos go into which action-point's splat is
decided by querying Neo4j (Cypher) for what was happening (which entities, which relations)
within that `:Event`'s time window.

**Status**: not yet built. Depends on Step 5 (a populated graph with real `:Event` nodes to
segment against) and on evaluating QuerySplat's actual API surface for time-indexed/
segmented splat generation (open item — not yet confirmed what QuerySplat supports
out of the box vs. what needs to be built around it).

### Step 7 — Splat storage & retrieval

**Input**: `:Scene` nodes and splat assets from Step 6.
**Output**: a queryable mapping from "a moment/entity/event in the graph" to "the exact
splat asset that renders it."

Every generated splat (from images and from video frames) is registered in Neo4j via
`(:Scene)-[:RENDERS]->(:Event)`, `(:Scene)-[:DEPICTS]->(:Entity)`, and
`(:Scene)-[:DERIVED_FROM]->(:Evidence)`. This means the query engine (Step 8) never has to
inspect raw splat files to figure out what they cover — a Cypher hit on an `:Event` or
`:Entity` directly resolves to the right `.ply` asset via `splat_uri`.

**Status**: covered by the Neo4j schema (Section 4); implementation is part of Step 6's
build, not a separate pipeline stage in practice.

### Step 8 — Query engine

**Input**: a natural-language question from a forensic investigator.
**Output**: the relevant graph subset, the associated splat asset, and a time window —
handed to the reconstruction UI to seek/highlight.

An agent takes a question ("Show me the fight," "Where was suspect P2 at 20:00:00?"),
translates it into a Cypher query against Neo4j (e.g. matching an `:Event` by label or an
`:Entity` by name/role and time window), executes it, and returns the matched
entities/events plus — via the Step 7 linkage — the `splat_uri` and time range needed to
render the answer. This is intentionally a thin orchestration layer: it does no reasoning
of its own beyond query translation, because all the actual forensic reasoning already
happened during fusion (Step 4) and is sitting in the graph.

**Status**: not yet built. Should be the last piece built, since it's only as good as the
graph it queries.

---

## 3. The OKF ground-truth + low-confidence escalation system

This is the mechanism that makes OKF actually do what it's meant to do here: **hold ground
truth in one place**, while making sure nothing gets promoted to "ground truth" status
without either clearing a confidence bar or being explicitly reviewed by a human.

Important correction carried over from earlier design discussion: OKF itself (Google's
Open Knowledge Format — markdown files with YAML frontmatter, `type` the only required
field) has **no built-in conflict resolution, provenance model, or confidence scoring**.
Those are all things *we* build on top of it. OKF gives us the portable, git-trackable,
human-and-agent-readable file format; we give it the structure and workflow described
below.

### Directory structure

```
okf/
├── claims/
│   ├── text/          # raw per-source claims from Step 1, one file per claim
│   ├── image/          # raw per-source claims from Step 2
│   └── video/           # raw per-source claims from Step 3
├── resolved/            # canonical, fused, high-confidence ground truth
│   └── <entity-or-event>.md
├── review/               # LOW-CONFIDENCE QUEUE — see below
│   └── <claim-or-conflict>.md
├── contested/            # claims that conflict and were NOT auto-resolved
│   └── <entity-or-event>.md
└── log.md                 # chronological record of every promotion/resolution decision
```

### The escalation rule

Every agent that writes into this system — the Step 1/2/3 extractors when producing a
claim, and the Step 4 fusion agent when attempting to resolve one — evaluates its own
confidence before writing, and follows one rule:

> **If confidence clears the threshold for that stage, write (or promote) normally. If it
> does not, write into `okf/review/` instead, with the reason attached — never guess and
> promote anyway.**

Concretely:

- **At extraction time (Steps 1–3)**: if an extractor's confidence in a claim itself is low
  (e.g. BERT-NER assigns a weak label, or a tracked object's identity is ambiguous across
  an occlusion), the claim is still written to `okf/claims/<modality>/` as normal (it's
  just a claim, not yet ground truth) — but it also gets a note in `okf/review/` if its
  confidence falls below that modality's minimum threshold, flagging it for a human to
  sanity-check before fusion ever touches it.
- **At fusion time (Step 4)**: this is the main gate. When the fusion agent attempts to
  align/resolve claims into a canonical `:Entity` or `:Event`:
  - **High-confidence resolution** (e.g. only one claim exists, or multiple claims agree,
    or the confidence-tier hierarchy cleanly decides a conflict) → write directly to
    `okf/resolved/`, which is what gets ingested into Neo4j as `:Entity`/`:Event` with
    `resolution_status: "resolved"`.
  - **Low-confidence resolution** (the agent has a "best guess" but isn't confident enough
    to commit it as ground truth — e.g. entity alignment similarity score sits near the
    decision boundary, or the tier hierarchy doesn't cleanly apply because both conflicting
    claims are the same tier) → write to `okf/review/`, **including the agent's best-guess
    resolution and its confidence score**, but do **not** promote it to `okf/resolved/` or
    write it to Neo4j as resolved. It stays queryable but marked `resolution_status:
    "contested"` or is simply absent from the resolved graph until reviewed.
  - **True conflicts** (claims that actively contradict each other and can't be resolved by
    rule at all) → write to `okf/contested/`, same as before, always retaining every
    original claim.

### Review file format

Every file in `okf/review/` follows the OKF convention (frontmatter + body) so it's
readable by both a human investigator and another agent picking up the review later:

```yaml
---
type: ReviewItem
stage: extraction | fusion
confidence: 0.42
threshold: 0.70
reason: "Entity alignment score below decision boundary between video Person_ID_42 and text claim 'the man in the alley'"
candidate_resolution: <best-guess entity id or claim id, if the agent has one>
claim_ids: [claim_abc123, claim_def456]
created_at: <ISO8601 datetime>
resolved: false
---
Free-text explanation of what the agent tried, why it couldn't clear the confidence bar,
and what a human reviewer should check.
```

A human (or a separate, higher-scrutiny review agent) resolves the item by editing this
file — setting `resolved: true`, filling in the actual decision, and adding a
`resolution_rule: "manual_review"` field. A periodic re-ingestion pass then picks up
newly-resolved review files and promotes them into `okf/resolved/` → Neo4j, exactly like
any other resolution, just with a human in the loop instead of a rule.

### Why this matters for the schema

This directly maps onto the `:Claim` / `:Entity` / `resolution_status` design already in
`imp_docs/neo4j_schema.md`: `okf/claims/` is the pre-ingestion form of `:Claim` nodes,
`okf/resolved/` is the pre-ingestion form of `:Entity`/`:Event` nodes with
`resolution_status: "resolved"`, and `okf/review/` + `okf/contested/` are what keep
`resolution_status: "contested"` entities from ever being silently written as if they were
certain. Nothing reaches Neo4j as resolved ground truth without either clearing a
confidence threshold or a human explicitly saying so.

### Confidence thresholds (starting point — tune per modality during build)

| Stage | Threshold | Rationale |
|---|---|---|
| Text claim extraction | 0.6 | narrative tier is inherently noisier; lower bar for "worth keeping as a claim" but still flagged for review below this |
| Image claim extraction | 0.65 | |
| Video claim/tracking extraction | 0.7 | sensor tier is the most trusted, so the bar for calling something reliable is higher too |
| Fusion entity alignment | 0.75 | this decision directly creates a canonical entity — highest bar of all |
| Fusion conflict resolution (tier hierarchy applies cleanly) | n/a — auto-resolves | the hierarchy itself is the decision rule when only one tier is present in the conflict |
| Fusion conflict resolution (tier hierarchy ambiguous, e.g. same-tier conflict) | always → `okf/review/` | never auto-resolve same-tier conflicts without human input |

These numbers are a starting proposal, not settled — validate against real fusion-agent
behavior once Step 4 exists and adjust.

---

## 4. Neo4j schema (summary)

Full detail lives in `imp_docs/neo4j_schema.md`. Summary for readers of this document:

- `:Entity` (+ `:Person`/`:Object`/`:Weapon`/`:Vehicle`/`:Location`) — canonical, resolved.
- `:Claim` — raw, per-source, pre-resolution. One per OKF claim file.
- `:Event` — an action point on the crime timeline.
- `:Scene` — a QuerySplat asset rendering one `:Event`.
- `:Evidence` — the raw source document/media.
- Provenance chain: `(:Entity)-[:RESOLVED_FROM]->(:Claim)-[:EXTRACTED_FROM]->(:Evidence)`.
- Dynamic relation types (`:HOLDING`, `:ATTACKED`, etc.) all carry `t_start`, `t_end`,
  `confidence`, `resolution_status`.
- Splat linkage: `(:Scene)-[:RENDERS]->(:Event)`, `(:Scene)-[:DEPICTS]->(:Entity)`.

---

## 5. Workstreams and ownership

Mapped from the team's existing Phase-2 contribution split — carried forward into Phase
3/4 build work unless the team wants to swap:

| Workstream | Owner | Pipeline step(s) | Depends on | Produces |
|---|---|---|---|---|
| **W1 — Text pipeline** | Aayush K. Singh | Step 1 | nothing — start immediately | OKF claim bundles (`source_modality: "text"`) |
| **W2 — Image pipeline** | A V Vedanth | Step 2 | nothing — start immediately | splat assets + OKF claim bundles (`source_modality: "image"`) |
| **W3 — Video pipeline** | Pranav Saxena | Step 3 | nothing — start immediately (hardest, start earliest) | splat assets + OKF claim bundles (`source_modality: "video"`) |
| **W4 — Fusion + OKF resolution + Neo4j ingestion** | Dhruv Jain | Step 4, Step 5 | W1/W2/W3's OKF bundle *format* only, not their internals | `okf/resolved/`, `okf/review/`, populated Neo4j graph |
| **W5 — Reconstruction (QuerySplat + action-point segmentation)** | A V Vedanth (extends W2) | Step 6, Step 7 | W4's `:Event`/`:Scene` schema in place | `:Scene` nodes wired to splat assets |
| **W6 — Query agent** | Aayush K. Singh (extends W1) | Step 8 | W4 fully populated graph | Cypher-generating natural-language query agent |

W1, W2, W3 have zero dependency on each other and should run in parallel immediately — this
is the entire point of the modular architecture. W4 is the integration chokepoint: it
shouldn't start real fusion logic until at least one of W1/W2/W3 has stable OKF output to
test against (recommend text, per Section 2's build-order note).

---

## 6. Contracts every workstream must honor

This is the minimum that must be agreed before any pipeline code is written, since it's
what lets W1/W2/W3 be built without the three developers needing to coordinate directly.

### OKF claim contract (W1/W2/W3 → W4)

Every extractor, regardless of modality, emits one markdown+YAML file per claim into
`okf/claims/<modality>/`:

```yaml
---
type: Claim
source_modality: text | image | video
source_id: <string>
raw_label: <string>
confidence_tier: sensor | visual | narrative
confidence: <float, this specific claim's extraction confidence>
extracted_at: <ISO8601 datetime>
predicate: <string, optional>
target_claim_id: <string, optional>
t_start: <ISO8601 datetime, optional>
t_end: <ISO8601 datetime, optional>
feature_tube_id: <string, optional — video only>
---
Free-text description / evidence excerpt supporting this claim.
```

A bundle that doesn't validate against this shape is a broken contract in the *producing*
workstream — catch it with that workstream's own tests before it ever reaches W4.

### Splat manifest contract (W2/W3 → W5)

Every splat asset ships with a sidecar manifest stating `splat_uri`, `source_modality`,
`t_start`/`t_end` or `frame_range`, and the `:Evidence` id(s) it was built from. W5 never
inspects raw COLMAP/video output directly.

### Neo4j write-ownership contract (W4 → W5/W6)

W4 owns the only code path that writes `:Entity`, `:Event`, and `:RESOLVED_FROM` edges — by
promoting from `okf/resolved/`. No other workstream writes resolved nodes directly. W5 and
W6 only ever read via Cypher.

### Review-queue contract (W1–W4, shared)

Any agent, in any workstream, that produces a below-threshold result writes to
`okf/review/` using the format in Section 3, rather than inventing its own ad hoc
"uncertain" convention. This is the one piece of the contract that's cross-cutting rather
than owned by a single workstream boundary.

---

## 7. Repo structure, agent scoping, and integration checkpoints

### Repo structure

```
crime-graph/
├── imp_docs/                  # design docs (this file, neo4j_schema.md, decision records)
├── okf/                        # the shared OKF store — see Section 3
│   ├── claims/{text,image,video}/
│   ├── resolved/
│   ├── review/
│   └── contested/
├── pipelines/
│   ├── text/                  # W1
│   ├── image/                 # W2
│   ├── video/                 # W3
│   └── shared/
│       └── okf_schema/         # the OKF claim-file contract, versioned, shared by W1/W2/W3
├── fusion/                     # W4 — OKF ingestion, resolution rules, Neo4j writer
├── reconstruction/             # W5 — QuerySplat integration, action-point segmentation
├── query_agent/                 # W6
└── specs/                       # existing — architecture/requirement specs
```

Each `pipelines/*` directory is close to a standalone project (own dependencies, own
tests, own README describing exactly what it produces), so a coding agent can be scoped to
just that directory without needing the rest of the repo in context.

### How each person runs their agent

- **Scope the agent to the workstream directory** (e.g. `pipelines/text/` plus
  `pipelines/shared/okf_schema/` read-only for W1) — not the whole repo.
- **Contract files are the shared source of truth, not conversation memory.** If two
  workstreams' agents disagree about a claim's shape, the answer is always "what does
  `pipelines/shared/okf_schema/` say" — update that file first, then re-point both agents
  at it.
- **Every session ends with a contract-conformance check**, not just "does my pipeline
  run." W1/W2/W3: validate emitted OKF bundles against the schema. W4: validate Neo4j
  writes satisfy `neo4j_schema.md`'s constraints, and confirm the review-queue path
  actually triggers on synthetic low-confidence input. W5/W6: validate against live Cypher
  queries, not mocked data.
- **Cross-workstream changes go through a written contract update first** — e.g. if W3
  needs a new `feature_tube_id` field, that's a proposed change to
  `pipelines/shared/okf_schema/`, reviewed before any pipeline depends on it.

### Integration checkpoints

1. **Checkpoint A** — W1 alone: text → OKF claim bundles, schema-validated.
   (Already effectively done per the Phase-2 prototype; needs re-pointing at the OKF format.)
2. **Checkpoint B** — W2 alone: images → splat + OKF claim bundles, same validation.
   (Geometry half already done per Phase 2; semantic-claim half still to build.)
3. **Checkpoint C** — W4 ingests Checkpoint A's bundles into a real Neo4j instance,
   single-modality — proves the `:Claim` → `:Entity` write path and the
   `okf/resolved/`/`okf/review/` split before any real conflicts exist to resolve.
4. **Checkpoint D** — W3 lands video → OKF bundles + splats. W4 now has two-plus modalities
   to actually fuse — this is where the confidence-tier resolution rules and the
   low-confidence escalation path get tested against real contested claims for the first
   time.
5. **Checkpoint E** — W5 wires `:Scene` nodes to real splat assets, segmented by
   `:Event`/action point, reading from the now-populated graph.
6. **Checkpoint F** — W6 query agent goes live against the full graph; system integration
   and testing per the existing Gantt plan.

Each checkpoint is a go/no-go gate — don't start the next workstream's integration work
until the current checkpoint's contract is satisfied end-to-end.

---

## 8. Open items

- Confirm final ownership of W5/W6 — provisionally assigned by extension of existing
  Phase-2 roles, not yet confirmed with the whole team.
- `pipelines/shared/okf_schema/` and the `okf/` directory structure need to actually be
  created and versioned before W1/W2/W3 begin real implementation.
- Confidence thresholds in Section 3 are a starting proposal — need tuning once Step 4
  exists and real fusion behavior can be observed.
- Text entity/relation type taxonomy (Step 1) still needs finalizing.
- Image semantic-claim extraction (BLIP-style captioning → claims) not yet designed beyond
  the geometry half.
- Video relation-generation MVP design (YOLOv8 + DeepSORT + lightweight relation
  classifier, before attempting full PSG4DFormer) not yet started.
- QuerySplat's actual support for time-indexed/segmented splat generation needs evaluation
  before Step 6/Workstream W5 can be scoped precisely.
- Confirm what "Open Knowledge Format" concretely refers to in our stack (Google's OKF
  spec, as read) before treating the name as a load-bearing dependency in diagrams/specs
  beyond the file-format role described here.
