# 07. How I would combine the projects

No code here. This is the shape I would build, the choices behind it, and what to drop.

## 1. Principles

1. **One reconstruction stack.** Two is one too many for four people and four weeks.
2. **Files first, database second.** Each pipeline writes plain files into a case folder. Neo4j is loaded from those files and can always be rebuilt.
3. **Human-confirmed links.** Machines propose; people confirm; the record says who.
4. **One viewer.** The dashboard is the video viewer with two more panes, not a new application.
5. **Everything in git, pushed daily.** You have already lost one component.

## 2. Choose the video repo as the base

| Need | `crime-splat` (image) | `crimesplat-video` |
|---|---|---|
| Training | nerfstudio Splatfacto; 12 dB on its scene; out of memory below 18 images on 8 GB | gsplat MCMC with a Gaussian cap; 20.6 dB on a 480p clip; runs on 4 GB |
| Viewer | gsplat.js, with an unfixed spike artefact in 15 of 20 preset views | Spark, clean, with click-to-source and timeline |
| Scale | None | Estimated, or honestly "unitless" |
| Provenance | Not built in | Hash, log, manifest |
| Packaging | Per-scene paths hardcoded in several scripts | Scene Package with manifest |
| Tests | Evaluation tool tests | Unit and end-to-end tests |

**Decision.** `crimesplat-video` becomes the reconstruction and viewer base. From `crime-splat`, carry over three things:

- **Photo-set input.** Add an ingest path that accepts a folder of photos (with the EXIF orientation fix) and feeds the same SfM and training stages. The capped MCMC trainer should also remove the 17-image memory failure. Rerun the Galanakis scene through it and compare; a jump from 12 dB would be a clear result.
- **The evaluation tools** in `pipelines/image/eval/`: ArUco detection and triangulation, Sim(3) alignment, marker distance error. These give marker-based metric scale, which the video pipeline lacks when the floor has no texture.
- **The SAM + CLIP region tagger and query**, as a suggestion source only.

Keep `crime-splat` as the home of the COLMAP study. Do not merge that research tree into the product.

One caution from the study: the video pipeline uses pycolmap 4.2.1, the version whose fallback registrations the study found unreliable. Record which images registered through the fallback and either exclude them or flag their frames in the viewer. This is a rare case where your own research directly improves your own system; mention it in both papers.

## 3. The case folder

```
cases/<case_id>/
  evidence/            originals, never modified
    manifest.jsonl     id, type, sha256, captured_at, source
  claims/
    text/*.md          one claim per file: YAML header + quote
    image/*.md
    video/*.md
  review/              items awaiting a human decision, and the decisions
  scenes/<scene_id>/   Scene Package: splat, cameras, frames, manifest, scale status
  anchors.jsonl        entity or claim -> scene, xyz, t_start, t_end, placed_by, method
  checks/              results of line-of-sight and travel-time checks, with renders
  graph/               export loaded into Neo4j
```

Your existing claim-per-file format fits this unchanged. The integration guide in `crime-splat/pipelines/image/INTEGRATION.md` already proposes compatible image claim and manifest formats; reuse its field names.

## 4. Minimal graph

Use the designed schema, cut down to what the demo needs.

- **Nodes:** `Evidence`, `Claim`, `Entity` (Person, Object, Place), `Event`, `Scene`, `Anchor`.
- **Edges:** `EXTRACTED_FROM` (claim to evidence), `RESOLVED_FROM` (entity to claim), `ASSERTS` (claim to a subject-relation-object triple with an interval), `ANCHORED_AT` (entity to anchor), `IN_SCENE` (anchor to scene), `CONFLICTS_WITH` (claim to claim, with a type), `CHECKED_BY` (claim to check result).

Fusion for the capstone can be simple and explicit:

- merge entities by exact and alias match, plus human merge in the review pane;
- mark two claims as conflicting when they assert incompatible values for the same subject and relation in overlapping intervals;
- let a language model *propose* further conflicts, which enter the review queue with both quotes.

Do not build a learned fusion model. Rule-based plus review is explainable, and you can measure it against the planted contradictions.

## 5. The checks module

A small service over a Scene Package:

- **Line of sight.** Inputs: scene, observer anchor, eye height, target anchor. Method: render depth from the observer towards the target, compare with the target distance over a small cone, and return visible fraction, a rendered image and the nearest source frames. Mark the result "insufficient coverage" when the region has few supporting views.
- **Travel time.** Inputs: two anchors and two times. Method: floor-plane path length (straight line first; a walkable-area path if time allows) divided by walking and running speeds.
- **Sensitivity.** Rerun with the observer moved by a fixed offset in several directions; report whether the verdict holds.

Both need metric scale, so both refuse to run on a unitless scene. That refusal is correct behaviour, and worth showing.

## 6. The dashboard, rebuilt smaller

The lost dashboard had many panels (work, evidence, inspector, narrative, board, beats, theories). Do not rebuild all of them. Three linked panes and one drawer:

| Pane | Shows | Linked behaviour |
|---|---|---|
| **Documents and claims** (left) | Source text with highlighted quotes; claim list; review queue | Selecting a claim selects its entities, time band and anchor |
| **Scene** (centre) | The splat, pins, camera path, source-frame overlay | Selecting a pin selects the claims about it |
| **Timeline** (bottom) | Lanes for text, image and video; contested intervals | Scrubbing filters claims and moves pins |
| **Discrepancies and checks** (drawer) | Conflicts with both quotes; check results with renders | Opens the relevant claim, time and view |

One selection model drives all panes: selecting anything sets a current entity, time window and scene position, and every pane reacts. That single rule is the "interconnectedness" you asked for.

Build it inside `crimesplat-video/web`, which is already Vite, TypeScript and three.js with the scene viewer working.

## 7. What to cut

- PSG image scene graphs, unless they produce a result on the staged case in a day.
- 4D or dynamic splatting.
- Automatic actor tracking and 3D lifting. People appear as pins at asserted positions.
- Feed-forward pose-free reconstruction.
- Synthetic data from games.
- Any bloodstain analysis beyond linking stains to their photographs.

## 8. Division of work

| Person | Owns |
|---|---|
| Aayush | Text pipeline recovery, claim format, discrepancy detection, the checks module |
| Vedanth | Paper A; photo ingest and marker-based scale in the video base; fallback flagging |
| Pranav | Dashboard panes and the selection model in `web/` |
| Dhruv | Neo4j loader and queries; staged case documents, script and ground-truth files |

All four film the staged case together in the first week.
