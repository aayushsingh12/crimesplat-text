# 03. Where the project shines

## 1. The gap it actually fills

Existing tools sit in two groups that do not talk to each other.

| Group | Examples | Has | Lacks |
|---|---|---|---|
| Link analysis and case management | i2 Analyst's Notebook, HOLMES2 (UK), CCTNS (India), records systems | People, phones, vehicles, statements, timelines | Any model of the physical scene |
| Scene documentation | Laser scanners with FARO Zone 3D or Leica software, photogrammetry, 360° capture | Accurate geometry, measurements | Any link to who said what |

An investigator who wants to know whether a statement is compatible with the room does it in their head, with photographs spread on a desk. **Your project is the join between the claim layer and the spatial layer.** Neither half is new. The join is.

## 2. The headline feature: check testimony against geometry

Three checks, each a small computation on data you already produce.

### Line of sight

- A statement says: "From the bedroom doorway I saw him standing by the wardrobe."
- The text pipeline extracts a claim: observer position, target position, the relation `SAW`.
- Both positions are pinned in the splat.
- Render depth from the observer's eye height towards the target and test whether anything blocks it.
- Output: **visible**, **partly occluded** or **not visible**, with a rendered view from the witness's position and the source frames behind that view.

### Travel time

- Statements give a person at place A at one time and place B at another.
- With metric scale, the path length along the floor gives a minimum plausible time at walking and running speed.
- Output: **feasible** or **too fast**, with the numbers.

### Reach and position

- "The phone was on the desk when I left" against the scene video showing it on the floor.
- "He was behind the door" against the door's swing and the wall.
- Output: the claim and the observed state, side by side.

### Why this is the right headline

- **It needs every pipeline.** Text gives the claim, the splat gives the geometry, the graph holds the link, the dashboard shows it. No part is decoration.
- **It is demonstrable in thirty seconds.** Click a statement, the camera flies to the witness's position, the target is behind a wardrobe, the claim turns amber.
- **It is measurable.** For a staged case you can stand at each position and photograph what is really visible. That gives ground truth and an accuracy number.
- **It separates two kinds of discrepancy.** "Disagrees with another witness" is weak. "Disagrees with the room" is strong. That distinction is the honest replacement for "who is lying".
- **Nobody has it.** I found no forensic tool or paper that tests extracted testimony against a reconstructed scene. I searched briefly, so check again before claiming it, and do not write "first" or "novel" in the paper; describe what it does.

### Limits to state

- Positions come from human pins, so the result depends on where the pin was put. Report sensitivity: move the observer by 30 cm and see whether the verdict changes.
- Occlusion from a splat is noisy near floaters. Use the depth from well-observed views and mark low-coverage regions as "not enough data".
- The scene is as it was when filmed, not as it was during the event. Doors move. The output is a lead for the investigator, never a finding.

## 3. The second strength: provenance all the way down

Every item on screen can answer "says who?" in one click.

- A fact in the graph leads to its claims, each claim to a verbatim quote in a document.
- A point in the splat leads to the video frames that observed it.
- A frame leads to a file hash recorded at ingest.

Most LLM-over-documents systems cannot do this, and it is the property that makes an AI tool tolerable in an investigation. Your grounding rule (reject any claim whose quote is not a verbatim substring of the source) is simple and strong. Measure it: how many hallucinated claims does it remove, and what does it cost in recall?

## 4. The third strength: it says "unknown"

- The video pipeline returns "unitless" when it cannot find the floor.
- The image query documents that it has no reliable threshold.
- Contested facts stay contested.

Write this up as a design principle with examples. Forensic reviewers care about known failure behaviour more than about peak quality.

## 5. A strength you did not mention: the SfM reliability finding

The COLMAP fallback study is a real, careful result with direct forensic meaning: a newer SfM version registers *more* images and reports nothing wrong, while a large share of the extra images are in grossly wrong positions. For evidence localisation that is the worst kind of error, because a higher registration rate looks like an improvement. It is the easiest paper to finish. See [04](04-publication-strategy.md).

## 6. Uses you may not be seeing

- **Scene video is becoming mandatory.** Indian criminal procedure since 2024 requires a forensic visit and video recording of the scene for serious offences (details and the caution about section numbers are in [06](06-police-workflow-fit.md)). That creates a large supply of walk-through videos with no tool that turns them into anything navigable. Your video pipeline takes exactly that input and runs on a 4 GB laptop GPU.
- **Cold-case and handover briefings.** A new investigator inherits thousands of pages. A claim graph with a timeline and a walkable scene shortens the reading-in period. This is where the Short-family-style text ingestion is useful.
- **Defence review.** The same provenance that helps the police lets a defence lawyer audit every machine-made link. Saying so strengthens the ethics section.
- **Training.** Staged cases with scripted ground truth (see [05](05-unified-demo-case.md)) are teaching material for police academies and forensic courses, and they are a dataset you can release.
- **Low-cost capture.** A laser scanner costs tens of lakhs of rupees and needs a trained operator. A phone and a laptop do not. Accuracy is lower, and you should say by how much, but for many stations the alternative is nothing.

## 7. One sentence for the abstract

A provenance-preserving case graph that links what people said to where it could have happened, so that each statement can be checked against the reconstructed scene and traced back to its source.
