# Query summary — all queries run against `galanakis2021`'s region lookup

Single reference table for demo narration. Every query actually run so far
(via `query_regions.py` + `render_query.py`, unmodified) against the
314-region lookup built by `tag_regions.py` — no cherry-picking, weak/wrong
results included exactly like strong ones. Full narrative and the
threshold discussion live in `pipelines/image/docs/phase2_decision.md`;
this table is just the reference list.

| Query | Top-1 similarity | SIFT support pts | Verdict | Source image | Result file |
|---|---|---|---|---|---|
| "blood spatter" | 0.3226 | 22 | plausible match — lands on a blood-marked evidence card | IMG_0463.jpg | `queries/blood_spatter.jpg` |
| "blood stain" | 0.3072 | 10 | plausible match — lands on a blood-marked card | IMG_0457.jpg | `queries/blood_stain.jpg` |
| "evidence marker" | 0.3004 | 16 | plausible match — lands on/near an evidence marker card | IMG_0457.jpg | `queries/evidence_marker.jpg` |
| "footprint" | 0.2937 | 1 | plausible match — lands exactly on the bloody-footprint card | IMG_0457.jpg | `queries/footprint.jpg` |
| "body" | 0.2870 | 1 | plausible match — lands on the mannequin's arm/hand | IMG_0459.jpg | `queries/body.jpg` |
| "mannequin" | 0.2769 | 6 | plausible match — lands on the mannequin's face | IMG_0464.jpg | `queries/mannequin.jpg` |
| "shoe" | 0.2765 | 20 | plausible match — lands exactly on the mannequin's shoe | IMG_0457.jpg | `queries/shoe.jpg` |
| "floor" | 0.2650 | 9 | weak / ambiguous — lands on an evidence card sitting on the floor, not a plain floor surface | IMG_0457.jpg | `queries/floor.jpg` |
| "a car" | 0.2592 | 1 | wrong region — absent-object query, no car exists in this scene | IMG_0485.jpg | `queries/a_car.jpg` |
| "weapon" | 0.2493 | 12 | wrong region — no weapon in this scene; also lands right at the top frame edge | IMG_0464.jpg | `queries/weapon.jpg` |

## Reading this honestly

- **Similarity alone does not separate the verdicts cleanly.** All ten
  scores sit in the same narrow 0.249–0.323 band — even the two clearly
  wrong matches ("a car," "weapon") aren't dramatically lower than the
  strong matches, consistent with `phase2_decision.md`'s CLIP
  zero-shot-score-compression finding. There is no obvious score cutoff
  that separates the "plausible match" rows from the "wrong region" rows
  in this table.
- **SIFT support count doesn't cleanly separate them either, on this
  larger sample.** `phase2_decision.md` flagged support-point count as a
  *promising but untested* secondary signal after only one comparison
  (22 vs. 1). This batch complicates that: "footprint" and "body" are
  both **correct, visually exact matches with only 1 supporting SIFT
  point** — the same low support count "a car" (also 1 point) had as a
  wrong match. Support count alone would misclassify both of those two
  correct matches as unreliable. Not a contradiction so much as evidence
  that no single scalar (similarity or support count) reliably separates
  hits from misses here on its own.
- **"floor" is a useful edge case**: not wrong exactly, but ambiguous —
  the region it landed on genuinely is on the floor, just also happens to
  be a specific evidence card rather than bare floor surface. Whether
  that counts as a "hit" depends on how literally the query is read.
- **"weapon" landing at the top frame edge** is worth flagging separately
  from the general wrong-match issue: this specific projection is right at
  a frame boundary, which is its own source of noise (see
  `failure_modes.md`'s frustum-edge finding) independent of the CLIP
  match being wrong.

No threshold logic was built from any of this — this table is
observational demo material, per scope.
