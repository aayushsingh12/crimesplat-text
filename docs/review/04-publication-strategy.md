# 04. Publication strategy

## 1. The constraint to accept first

Your Gantt chart ends in mid-December 2026. A reputed journal takes three to nine months from submission to decision. So "published in a reputed journal by the end of the capstone" is not available. What is available:

- a paper **submitted** to a journal, with a preprint, by December;
- a paper **accepted** at a conference or workshop with a short review cycle;
- both, with different content.

Ask your guide which of these the department counts. Many departments accept "submitted to a Scopus-indexed venue". I have not checked any deadline; check each venue's current call before choosing.

## 2. The options, ranked

| Rank | Paper | Readiness | Novelty risk | Verdict |
|---|---|---|---|---|
| 1 | **A. COLMAP fallback mis-registration study** | Experiments frozen; needs figures and writing | Low | Submit first |
| 2 | **B. The integrated system with testimony-vs-geometry checks** | Needs the staged case and integration | Medium | The capstone's own paper |
| 3 | **C. Grounded claim extraction and discrepancy detection** | Needs a gold set and baselines | Medium | Fold into B, or split out if B grows too long |
| 4 | **D. Capture protocol for forensic splats** | Half the evidence exists | Low, but modest | A short paper or a section of B |
| 5 | **E. Blood spatter analysis with 3DGS** | Nothing exists | High, and likely invalid | Do not pursue (see [02](02-what-will-not-work.md)) |
| 6 | **F. "3DGS for crime scenes" accuracy paper** | One scene at 12 dB | Already published by others | Do not pursue |

## 3. Paper A: sparse-view SfM fallback registrations are often grossly wrong

This is your teammate's work. It should be their first-author paper, and it is the strongest result the team has.

**Claim.** In sparse photo sets, images that COLMAP 4.2.1 registers only through its structure-less fallback are grossly mis-posed far more often than other images, the wrong pose exists at registration, and two plausible in-mapper gates do not fix it.

**Why it is publishable.**

- Clear effect: 32 of 56 against 12 of 1,701 at subset size 12; 46 of 105 against 35 of 2,263 at size 16, on fresh subsets.
- Replicated internally, rules declared before results, negative results included.
- A concrete cause for run-to-run variation (unseeded RANSAC) with a one-line fix shown on the forensic scene.
- Practical message: a higher registration rate is not a better reconstruction.

**Weaknesses a reviewer will raise.**

- One dataset (ETH3D). No external replication.
- One software version.
- No fix offered.
- The forensic scene has no ground-truth poses, so the forensic link is by argument.

**How to strengthen it cheaply.**

- File the COLMAP issue that is already drafted. A maintainer's acknowledgement is strong evidence.
- Use the staged case from [05](05-unified-demo-case.md) with ArUco markers as a small forensic test with measured ground truth.
- Lead with rates, not odds ratios. The study's own notes already say this.

**Venues to consider.**

- Photogrammetry and vision: ISPRS Annals or Archives, The Photogrammetric Record, Journal of Imaging, a 3DV or WACV workshop.
- Forensic: Forensic Science International: Digital Investigation, with the framing "silent pose errors in photo-based scene reconstruction".

## 4. Paper B: the system paper

**Working title.** "Linking testimony to scene geometry: a provenance-preserving multimodal case graph for crime scene review."

**Contributions, in order of strength.**

1. A claim model in which every fact is traceable to a verbatim quote, a video frame or an image region, with contested facts kept.
2. Testimony-vs-geometry checks (line of sight, travel time) computed on a splat built from an ordinary walk-through video.
3. A staged, scripted case with ground truth for all modalities, released as a dataset.
4. An evaluation of each stage and a small user study.

**Evaluation you need. Each row is one table in the paper.**

| Question | Measure | Ground truth |
|---|---|---|
| Are extracted claims correct? | Claim-level precision and recall | Hand-labelled gold claims for the staged documents |
| Does grounding reduce hallucination? | Fabricated claims with and without the quote check and the entailment pass | Same gold set |
| Are discrepancies found? | Precision and recall on planted contradictions | The script |
| Is the geometry right? | Distance error between markers; scale error | Tape measurements |
| Are visibility verdicts right? | Accuracy over all scripted observer-target pairs; sensitivity to pin position | Photographs taken from each observer position |
| Does it help a person? | Time and accuracy on 6 to 8 case questions, tool against a paper folder | The script; 8 to 12 student participants |

**Baselines.** Extraction with no grounding step; a plain "give the whole case file to an LLM and ask" baseline for discrepancy detection; reading the documents for the user study.

**Outline.**

1. Introduction: the gap between link analysis and scene documentation.
2. Related work: forensic 3D documentation (laser scanning, photogrammetry, Cho and Woo, Rangelov et al.), language-embedded splats and relational splats (LangSplat-family, ReLaGS), knowledge graphs from case text, LLM consistency checking.
3. System: claim model, three ingestion paths, anchors, checks.
4. The staged case and its ground truth.
5. Results.
6. Limitations and responsible use: not evidence, pins are human, scene state at capture time, no real cases.
7. Conclusion.

**Venues to consider.** Forensic Science International: Digital Investigation (also publishes DFRWS proceedings), Forensic Science International: Reports, Journal of Forensic Sciences (technical note), IEEE Access, Multimedia Tools and Applications, and applied-vision or HCI conference tracks. For the text part alone, the Natural Legal Language Processing workshop.

## 5. Paper C, if split out

**Claim.** Quote-grounded extraction with an entailment check produces a case graph with fewer fabricated facts than ungrounded extraction, and makes cross-document discrepancies detectable.

**What it needs.**

- 5 to 10 synthetic case files with planted contradictions of labelled types. Generating them with scripts is fine if a person verifies each one.
- A gold claim set for at least two of them.
- Ablations: no grounding; grounding only; grounding plus entailment.
- A local open model as well as an API model.

## 6. Claims to remove from every draft and slide

- "First forensic 3DGS benchmark."
- "Only publicly available forensic photogrammetry dataset."
- "4D panoptic scene graph" for the text-derived graph.
- "Language-embedded splat" and "feature distillation" unless you implement them.
- BERTScore as evidence of correctness.
- Any sentence implying deception detection.
- Any distance in metres from the image pipeline.
- "Novel" and "first" in general. Describe what the system does and let the related-work section carry the comparison.

## 7. Related work you must read and cite

- Cho and Woo (2026), 3DGS accuracy on a mock crime scene. This is your nearest neighbour on the 3D side. Your difference is not accuracy; it is linking the scene to claims, and using consumer video on a laptop GPU.
- Rangelov et al. on NeRF and 3DGS for crime scenes, including camera settings.
- The area-of-origin validation papers for FARO Zone 3D and HemoVision, to show you know why you are not doing bloodstain analysis.
- Language Embedded 3D Gaussians, LangSplat and ReLaGS for open-vocabulary and relational splats.
- Work on knowledge graphs from crime narratives and on LLM checks of graph facts against their provenance.
- The Galanakis dataset paper and the Fictional Forensic Scene dataset, cited correctly.
