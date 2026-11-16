# Neo4j Graph Schema — Crime Scene Reconstruction

Status: design draft, pre-implementation. Covers the Master/Global Scene Graph that all
modality pipelines (text, image, video) fuse into, and that the QuerySplat reconstruction
and query-agent layers read from.

## Design principles

- **Claims vs. Entities are separate node types.** Nothing from a single source (a witness
  statement, a video track, a photo) is ever written directly as ground truth. Raw
  per-source assertions are `:Claim` nodes; only the fusion/resolution step produces
  canonical `:Entity` / `:Event` nodes, linked back to the claims that produced them.
- **Every fact carries an interval, not a point in time.** Text timestamps are often
  imprecise ("shortly after 8pm"); video timestamps are frame-precise. `t_start`/`t_end`
  on relationships lets both coexist — a precise fact just has `t_start == t_end`.
- **Provenance is a first-class traversal**, not a metadata field. `:Entity` ->
  `:RESOLVED_FROM` -> `:Claim` -> `:EXTRACTED_FROM` -> `:Evidence` must always be walkable
  for any fact in the graph, for forensic auditability.
- **OKF (Open Knowledge Format) is the intermediate interchange layer, not the resolver.**
  Per-source scene graphs are exported as OKF markdown+YAML bundles (one file per
  claim/entity, human- and agent-readable, git-trackable) before ingestion. OKF itself does
  not do conflict resolution, provenance modeling, or confidence scoring — the fusion agent
  reading multiple OKF bundles and writing `:Claim` nodes (and later `:Entity` nodes via
  `:RESOLVED_FROM`) is our own component, not something OKF provides.
- **Conflicts are never silently discarded.** A contested fact stays as multiple `:Claim`
  nodes attached to an `:Entity` with `resolution_status: "contested"`; only when a rule
  (e.g. "visual > narrative") or manual override picks a winner does `:RESOLVED_FROM`
  collapse it to one canonical version — and the rule that decided is recorded.

## Node labels

### `:Entity` (base label; always paired with a subtype label)

Canonical, resolved, post-fusion entity. Combine with one of `:Person`, `:Object`,
`:Weapon`, `:Vehicle`, `:Location` (multi-label node, e.g. `:Entity:Person`).

| Property | Type | Notes |
|---|---|---|
| `id` | string (UUID) | canonical identity, survives merges |
| `type` | string | "Person" \| "Object" \| "Vehicle" \| "Location" ... |
| `name` | string | display label, e.g. "Suspect", "Kitchen Knife" |
| `first_seen` | datetime | |
| `last_seen` | datetime | |
| `confidence` | float | resolved confidence, post-fusion |
| `resolution_status` | string | "resolved" \| "contested" \| "single-source" |

### `:Claim`

Raw, per-source assertion, pre-resolution. Maps ~1:1 from an OKF bundle entry on ingestion.

| Property | Type | Notes |
|---|---|---|
| `id` | string | |
| `source_modality` | string | "text" \| "image" \| "video" |
| `source_id` | string | witness_id / report_id / frame_range / video_id |
| `raw_label` | string | what that source called it, e.g. "the man in the alley" |
| `confidence_tier` | string | "sensor" \| "visual" \| "narrative" |
| `extracted_at` | datetime | |
| `okf_path` | string | pointer back to the source OKF markdown file |

### `:Event`

An "action point" — a discrete beat of the crime timeline. This is what QuerySplat scenes
are segmented and rendered against.

| Property | Type | Notes |
|---|---|---|
| `id` | string | |
| `label` | string | "Entry", "Confrontation", "Weapon Drawn", "Exit" |
| `t_start` | datetime | |
| `t_end` | datetime | |
| `confidence` | float | |
| `sequence_index` | int | ordering fallback when timestamps are fuzzy/missing |

### `:Location`

| Property | Type | Notes |
|---|---|---|
| `id` | string | |
| `name` | string | |
| `geo_bounds` | (optional) | polygon/bbox if known |
| `splat_region_id` | string (optional) | pointer into a splat's coordinate space |

### `:Scene`

A QuerySplat asset — one per action point (per the reconstruction design: photos/video
frames are split into multiple splats keyed to `:Event`s, not one continuous
reconstruction).

| Property | Type | Notes |
|---|---|---|
| `id` | string | |
| `splat_uri` | string | path/URI to the `.ply` / splat asset |
| `source_modality` | string | "image" \| "video_frame_range" |
| `action_point_id` | string | the `:Event` this scene renders |
| `t_start` | datetime | |
| `t_end` | datetime | |
| `frame_range` | string (optional) | if derived from video |

### `:Evidence`

The raw source document/media — distinct from `:Claim`, which is an extracted assertion
*from* this evidence.

| Property | Type | Notes |
|---|---|---|
| `id` | string | |
| `modality` | string | "witness_statement" \| "police_report" \| "cctv" \| "bodycam" \| "photo" |
| `file_uri` | string | |
| `captured_at` | datetime | |
| `custody_id` | string | chain-of-custody reference |

## Relationships

### Core relational/temporal facts (dynamic predicate types)

Predicate is the relationship type itself — `:HOLDING`, `:ATTACKED`, `:FLED_TOWARD`,
`:LOCATED_AT`, etc. — all carrying the same property set:

| Property | Type | Notes |
|---|---|---|
| `t_start` | datetime | |
| `t_end` | datetime | |
| `confidence` | float | |
| `resolution_status` | string | "resolved" \| "contested" |

### Provenance chain

```
(:Claim)-[:EXTRACTED_FROM]->(:Evidence)
(:Claim)-[:ASSERTS {predicate, t_start, t_end}]->(:Claim)
(:Entity)-[:RESOLVED_FROM {resolution_rule}]->(:Claim)
```

`resolution_rule` records why a claim won during fusion, e.g. `"visual>narrative"`,
`"majority_vote"`, `"manual_override"`. A contested `:Entity` simply has multiple
`:RESOLVED_FROM` edges (or none collapsed yet) to competing `:Claim`s.

### Event structure

```
(:Entity)-[:PARTICIPATED_IN {role}]->(:Event)   # role = "suspect"|"victim"|"witness"|"instrument"
(:Event)-[:OCCURRED_AT]->(:Location)
(:Event)-[:PRECEDES]->(:Event)                   # explicit ordering, independent of timestamp precision
```

### Splat / reconstruction linkage

```
(:Scene)-[:RENDERS]->(:Event)
(:Scene)-[:DEPICTS]->(:Entity)
(:Scene)-[:DERIVED_FROM]->(:Evidence)
```

`(:Scene)-[:RENDERS]->(:Event)` is what lets the query agent, given a Cypher hit on an
`:Event` or `:Entity`, immediately resolve which splat asset to hand to QuerySplat.

## Constraints & indexes

```cypher
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT claim_id  IF NOT EXISTS FOR (c:Claim)  REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT event_id  IF NOT EXISTS FOR (e:Event)  REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT scene_id  IF NOT EXISTS FOR (s:Scene)  REQUIRE s.id IS UNIQUE;

CREATE INDEX event_time  IF NOT EXISTS FOR (e:Event)  ON (e.t_start, e.t_end);
CREATE INDEX entity_time IF NOT EXISTS FOR (e:Entity) ON (e.first_seen, e.last_seen);
```

## Example query

"Show me the fight" -> resolve to an `:Event` by label/embedding match, then:

```cypher
MATCH (ev:Event {label: "Confrontation"})<-[:RENDERS]-(s:Scene)
MATCH (ev)<-[:PARTICIPATED_IN]-(ent:Entity)
RETURN s.splat_uri, ev.t_start, ev.t_end, collect(ent)
```

Returns everything the query agent needs: which splat to load in QuerySplat, the time
window to scrub to, and which entities to highlight.

## Open items

- Text scene-graph schema (BERT-NER output -> `:Claim`/OKF bundle mapping) — not yet
  designed.
- Image and video pipeline designs — not yet finalized.
- `:Claim` -> `:Entity` resolution rule set (the actual "sensor > narrative" logic, and how
  contested facts surface to a human investigator) — not yet designed.
- Confirm what "Open Knowledge Format" concretely refers to in our stack before treating it
  as a load-bearing dependency name in diagrams/specs.
