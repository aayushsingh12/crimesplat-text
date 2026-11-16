# 01. Current state: what is built, and what the slides claim

Everything here comes from the two decks and the two repositories. Where a number is quoted, the source file is named.

## 1. Component by component

### Text pipeline and dashboard (W1)

- **Shown in the Phase 3 deck:** chunking, joint entity and relation extraction against a fixed taxonomy (7 entity types, 25 relation types), verbatim-quote grounding with hard rejection, a second entailment pass that lowers confidence to 0.3 or below, routing below 0.6 to a human review queue, one markdown + YAML file per claim. The dashboard screenshot shows the Short family case with 452 entities, 912 of 1,439 facts timed and 103 claims awaiting a human decision.
- **In the repos:** nothing. `crime-splat/docs/phase1_text_pipeline.md` is a design draft and describes a different method (BERT-NER plus dependency parsing) from the one in the deck (a single structured-output pass). The integration guide lists `pipelines/text/`, `okf/`, `fusion/` and `query_agent/` as not existing.
- **Reported metric:** BERTScore F1 0.7945 on a Mumbai-attack article. This measures how similar a regenerated text is to the source. It does not measure whether the extracted claims are correct.
- **Status:** the dashboard is lost. I do not know whether the extraction code is lost too. This is the first open question in [08](08-plan-and-open-questions.md).

### Image pipeline, `crime-splat` (W2)

- **Built:** EXIF orientation fix, COLMAP, nerfstudio Splatfacto, pruning, SAM + CLIP region tagging, text query, a WebGL viewer, evaluation tools (Sim(3) alignment, pose error, ArUco marker triangulation, landmark distances).
- **Verified numbers** (`pipelines/image/docs/methods_draft.md`):
  - one scene (Galanakis 2021, 30 photos); 20 to 22 photos register, depending on the run;
  - 18 training and 2 evaluation images: PSNR 11.76, SSIM 0.639, LPIPS 0.586;
  - training with 17 images runs out of memory on the 8 GB card;
  - a second scene (FFS `th_0085`) fails at COLMAP because macro close-ups share no features with wide shots;
  - no metric scale anywhere;
  - text query: "blood spatter" scores 0.3226 and the absent "a car" scores 0.2592, so no threshold separates hits from misses (`demo_assets/query_summary.md`).
- **The side study** (`strengthen/RESULTS_S.md`, `AGENT_CONTEXT.md`): on sparse ETH3D subsets, images that COLMAP 4.2.1 registers only through its structure-less fallback are grossly mis-posed far more often than the others.
  - Fresh subsets 11 to 30: 32 of 56 fallback-gained images gross at size 12, against 12 of 1,701 core images. At size 16: 46 of 105 against 35 of 2,263.
  - 7,880 runs, rules declared and hashed before results, replicated on fresh subsets.
  - Two attempted in-mapper fixes do not help, reported as negative results.
  - The fallback's RANSAC is unseeded, which explains the run-to-run registration split on the forensic scene.
- **Status:** the pipeline is a working demo on one scene. The study is close to a finished paper.

### Video pipeline, `crimesplat-video` (W3)

- **Built:** ingest with SHA-256, sharpest-frame selection, YOLO11 people masks, COLMAP with loop closure, gravity, floor and metric scale estimation, gsplat MCMC training with a Gaussian cap, SPZ packaging, a three.js + Spark viewer with click-a-surface-to-see-source-frames, snap-to-source-view and a timeline. Unit tests and an end-to-end regression test.
- **Verified numbers** (`README.md`, `docs/reports/2026-11-08-first-real-footage.md`):
  - synthetic room: 105 of 105 keyframes, 3.9 mm trajectory error, 0.3 % scale error, 28.6 dB held-out;
  - real 480p WhatsApp bedroom clip: 105 of 112 keyframes, 20.6 dB held-out, scale reported as unitless because the glossy floor gave no features.
- **Not built:** people tracking, 3D lifting of actors, evidence proposals, event detection, multi-camera CCTV. All are on the roadmap as Phase 2 and later.
- **Uncommitted work:** `git status` shows 17 modified files and untracked `docs/reports/`. Given that you already lost the dashboard, commit and push this today.

### PSG image scene graph

- Shown in the deck on a street image (cars, road, pavement). Not in either repo. Not shown on a crime-scene image.

### Fusion, Neo4j, cross-modal linking, query agent

- `docs/neo4j_schema.md` and `docs/cross_team_agentic_dev_plan.md` are careful designs: claims separate from entities, intervals not points, provenance as a traversal, conflicts kept as contested rather than discarded.
- No code. The integration guide's Cypher was never executed.

## 2. Where the slides say more than the code does

Fix these before the next review. A panel member who opens the repo will find them.

| Slide claim | What is true |
|---|---|
| "Establishing first forensic 3DGS benchmark" | Not first. Cho and Woo (2026) measure 3DGS accuracy on a mock crime scene with millimetre-level results; Rangelov et al. compare NeRF and 3DGS for crime scenes. A 2-image evaluation set at 12 dB is also not a benchmark. |
| "The only publicly available forensic photogrammetry dataset" | Your own repo uses a second one (Fictional Forensic Scene). |
| "Katsos et al., 2021" (Phase 2) and "Galanakis et al. (2021)" (Phase 3) for the same Zenodo DOI | Pick the correct citation and use it everywhere. |
| Crime-Splat diagram: "feature distillation, embed into Gaussians, language-embedded splat" | The code does not distil features into Gaussians. It tags 2D SAM regions with CLIP and gives each region one 3D point from COLMAP's SIFT tracks. |
| "QuerySplat (feed-forward, pose-free reconstruction)" in the tool list | Not in the repo. |
| 83.33 % registration | Not reproducible. The verified range is 66.67 to 73.33 % (the Phase 3 deck already says this; the Phase 2 number should be retired). |
| "4D Temporal Scene Graph" from text; PSG4DFormer for video | The text graph is a temporal knowledge graph of claims, not a panoptic scene graph. No video scene graph exists. |
| BERTScore 0.7945 "validates preservation of semantic ground truth" | It validates similarity of a paraphrase. Replace with claim-level precision and recall against a hand-labelled gold set. |
| Reference list | Four references, one duplicated. |

## 3. What is good and should be kept

- **The claim model.** Claims are never truth; every claim carries a verbatim quote; ungrounded claims are dropped; low-confidence claims go to a person. This is the right design for this domain and most published LLM-graph systems do not have it.
- **Honest-failure behaviour.** The video pipeline reports "unitless" instead of guessing a scale. The image pipeline documents that its query has no threshold. For a forensic tool this is worth more than a higher PSNR.
- **Provenance.** SHA-256 on ingest, append-only logs, snap-to-source-frame in the viewer.
- **The COLMAP study's method.** Declared rules, hashed declarations, negative results kept.

## 4. The structural problem

The work has split into three projects that share a title:

- two splat stacks (nerfstudio Splatfacto + gsplat.js, and gsplat MCMC + Spark) that do the same job at different quality;
- three demo datasets from three unrelated cases;
- a graph design that nothing writes to;
- a teammate's research that has moved to a general SfM question and away from the forensic system.

The remaining four weeks should go to joining these, not to adding a new pipeline. [07](07-integration-architecture.md) gives the joining plan.
