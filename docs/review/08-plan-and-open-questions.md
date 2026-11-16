# 08. Four-week plan and open questions

Dates assume the mid-December 2026 submission on your Gantt chart. Today is 16 November.

## 1. Before anything else (today)

- Commit and push `crimesplat-video`: 17 modified files and an untracked `docs/reports/` folder are sitting only on your laptop.
- Find out what survives of the text pipeline: code, prompts, the claim files for the Short family case, the Neo4j dump. Check old laptops, teammates' clones, cloud drives and the demo recording.
- Agree with the team and your guide on the reframing in [00](00-README.md): no bloodstain analysis, no lie detection, one staged case, testimony-vs-geometry as the headline.

## 2. Week by week

### Week 1 (17 to 23 November): the case and the contracts

- Write the scenario, the documents, the planted discrepancies and the hidden answer file.
- Print markers, stage the room, film and photograph everything in one session ([05](05-unified-demo-case.md) has the list).
- Run the walk-through through the video pipeline on the first evening. If it fails, refilm while the room is still staged.
- Restore or rewrite the text extraction to the point where it emits claim files for the staged documents.
- Fix the case-folder layout and the anchor format ([07](07-integration-architecture.md)).
- Paper A: figures from the committed CSVs; methods and limitations drafted.

**End of week check:** one splat of the staged room with metric scale from markers, and claim files for every document.

### Week 2 (24 to 30 November): the join

- Neo4j loader from the case folder; conflict rules; review queue.
- Pin placement in the viewer, writing anchors.
- Documents pane and timeline pane in the web app, driven by one selection model.
- Hand-label the gold claim set for the staged documents (two people, independently, then reconcile).
- Photo-folder ingest into the video base; rerun the Galanakis scene for the comparison number.

**End of week check:** click a claim, the camera flies to its pin; click a pin, its claims are listed.

### Week 3 (1 to 7 December): the headline and the numbers

- Line-of-sight and travel-time checks with sensitivity runs.
- Discrepancy drawer.
- Run every evaluation in [04](04-publication-strategy.md): extraction, grounding ablation, discrepancy detection, distances, visibility verdicts.
- User study with 8 to 12 students, about 30 minutes each.
- Paper A: full draft to your guide.

**End of week check:** every table in paper B has numbers, including the bad ones.

### Week 4 (8 to 14 December): writing and rehearsal

- Paper B draft; preprint if your guide agrees.
- Final report and slides with the corrected claims ([01](01-current-state.md), section 2).
- Rehearse the eight-step demo twice on the presentation machine, offline.
- Record a backup video of the demo.
- Tag releases in both repositories; archive the staged dataset.

## 3. If time runs short, cut in this order

1. User study (keep three informal sessions and report them as such).
2. Travel-time check (keep line of sight).
3. Natural-language question box.
4. Photo-folder ingest and the Galanakis rerun.
5. Neo4j itself: the demo can run from the case-folder files with an in-memory graph. Keep the schema in the report.

Do not cut the staged case, the gold labels or the line-of-sight check. Without those there is no paper B and no headline.

## 4. Risks

| Risk | Sign | Response |
|---|---|---|
| Text pipeline is fully lost | No code found by Wednesday | Rewrite the core only: extraction with quote check, claim files. Skip the entailment pass until week 3 |
| Staged room does not reconstruct | Under 85 % of keyframes registered, or unitless | Refilm the same day: slower, more texture on the floor, markers in view |
| Visibility checks are unstable | Verdicts flip in the sensitivity runs | Report three states with an "uncertain" band; that is still a result |
| Guide insists on bloodstain analysis | Review feedback | Offer stain-photo linking with scale bars, and show the published 5 to 17 cm area-of-origin errors as the reason for not going further |
| Team time | Exams, placements | The cut list above |

## 5. What I need from you before we plan the build

1. **What survives of the text pipeline and dashboard?** Code, prompts, claim files, database dump, recordings.
2. **Which language model did the extraction use, and can it run locally?**
3. **Exact final dates:** report, demo, paper.
4. **What does your department count as "published"?** Submitted, accepted, indexed where?
5. **Is your teammate planning to submit the COLMAP study, and under whose names?** The repository rules say the author steers it; this needs a conversation, not an assumption.
6. **Which GPU machines do you have for the next four weeks?** The repos mention a 4 GB laptop, an 8 GB laptop and a short window on a larger card.
7. **Can you get a room for a day**, and one conversation with a police officer or forensic scientist?
8. **Does your guide have a view on the staged case replacing the Short family material in the demo?**

## 6. What I did not verify

- I did not run either pipeline. Every number is quoted from the repositories' own reports.
- I read abstracts and search summaries of the related papers, not the full texts.
- The statute section numbers in [06](06-police-workflow-fit.md) and the bloodstain-analyst error figure in [02](02-what-will-not-work.md) are from memory.
- I did not read `crime-splat`'s full study history, only its latest results file and agent context.
- I did not check any venue's scope, indexing or deadline.
