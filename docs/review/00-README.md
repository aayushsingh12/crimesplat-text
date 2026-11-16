# Crime Scene Reconstruction using Scene Graphs: project review

Written 2026-11-16 from a full read of both capstone decks (Phase 2 ESA, Phase 3 Review 1), the `crime-splat` repo (image pipeline) and the local `crimesplat-video` repo (video pipeline). Nothing was implemented or changed in either repo.

## The verdict in one page

**What you have is three good parts and no whole.**

| Part | Real state | Quality |
|---|---|---|
| Text → claims (yours) | Worked on the Short family case (452 entities, quote-grounded claims, review queue). Dashboard lost; unclear whether the pipeline code survived. | Design is the strongest idea in the project |
| Photos → splat + text query (`crime-splat`) | Works on one staged scene. 20 of 30 photos registered, PSNR about 12 dB, no metric scale, text query has no usable threshold. | Reconstruction is weak; the documentation and the side study on COLMAP are excellent |
| Video → splat + viewer (`crimesplat-video`) | Static-scene MVP, end to end, tested. Synthetic: 3.9 mm trajectory error. Real 480p clip: 20.6 dB. | Best-engineered part |
| Fusion, Neo4j, cross-modal links | Design documents only | Not built |
| 4D panoptic scene graph from video, actors, events | Not built | Not built |

**The four answers, short.**

1. **Publishing.** Do not build the paper on blood spatter. The most publication-ready thing in the project is one you did not mention: your teammate's study showing that COLMAP 4.2.1's structure-less fallback registers images into grossly wrong poses in sparse photo sets. The second paper is the integrated system, evaluated on a staged case with scripted ground truth. See [04](04-publication-strategy.md).
2. **Interconnection.** Your three demo datasets are three different cases (Short family text, Galanakis room photos, your bedroom video). No amount of code links them. Stage one mock case yourselves and capture all modalities of it. See [05](05-unified-demo-case.md).
3. **The shiny factor.** Checking testimony against reconstructed geometry: "the witness says they saw this from the doorway" becomes a line-of-sight test in the splat. It is the one feature that needs all three pipelines at once and that no existing tool has. See [03](03-where-it-shines.md).
4. **Police fit and what will not work.** The tool is an investigative aid for organising and cross-checking a case file, not evidence and not a lie detector. Blood spatter analysis, "who is lying", a 4D scene graph of the crime itself, and automatic photo-to-victim matching with CLIP do not work the way you describe them. See [02](02-what-will-not-work.md) and [06](06-police-workflow-fit.md).

## Documents

| File | Answers |
|---|---|
| [01-current-state.md](01-current-state.md) | What is actually built, what the slides claim that the code does not do |
| [02-what-will-not-work.md](02-what-will-not-work.md) | The parts that will not work as imagined, and what to do instead |
| [03-where-it-shines.md](03-where-it-shines.md) | The differentiator, the headline feature, what makes it different from existing tools |
| [04-publication-strategy.md](04-publication-strategy.md) | Paper options ranked, venues, outlines, claims to remove |
| [05-unified-demo-case.md](05-unified-demo-case.md) | One staged case that exercises every pipeline and gives ground truth |
| [06-police-workflow-fit.md](06-police-workflow-fit.md) | How investigations work today, where this fits, why reconstruction matters |
| [07-integration-architecture.md](07-integration-architecture.md) | How I would combine the repos and rebuild the dashboard |
| [08-plan-and-open-questions.md](08-plan-and-open-questions.md) | Four-week plan to the December submission, and what I need from you |

## Sources used for the related-work claims

- Cho and Woo, "Accuracy of three-dimensional Gaussian Splatting for virtual crime scene reconstruction", Frontiers in Computer Science, 2026: https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2026.1755361/full
- Rangelov et al., NeRF vs Gaussian Splatting comparison (indoor and outdoor): https://research.utwente.nl/en/publications/evaluating-3d-reconstruction-a-side-by-side-comparison-of-nerf-an/
- Rangelov et al., camera settings for 3DGS and NeRF in indoor crime scenes, Sensors 2024: https://doaj.org/article/e9959bd2467f4dd0bf40cf42351be063
- Liscio, FARO Zone 3D area-of-origin preliminary validation: https://acsr.org/post/a-preliminary-validation-for-the-faro-zone-3d-area-of-origin-tool
- HemoVision least-squares area-of-origin validation: https://bvbvf1.bib-bvb.de/vufind/PrimoRecord/cdi_kuleuven_dspace_20_500_12942_690325
- HemoVision marker-based structure from motion, Forensic Science International 2024: https://pesquisa.bvsalud.org/bvsms/resource/pt/mdl-39024802
- Kowalske et al., manual vs computer-aided bloodstain reconstruction: https://hull-repository.worktribe.com/output/5175749/technical-note-parameters-of-bloodstain-pattern-spatial-reconstruction-in-manual-vs-computer-aided-data-acquisition
- Knowledge-graph LLMs on true-crime narratives (secondary summary): https://www.promptlayer.com/research-papers/can-ai-crack-the-case-using-knowledge-graphs-to-analyze-true-crime
- LLMs for knowledge-graph consistency against provenance: https://par.nsf.gov/biblio/10529111
- Language Embedded 3D Gaussians (CVPR 2024): https://arxiv.org/pdf/2311.18482
- ReLaGS, Relational Language Gaussian Splatting: https://www.alphaxiv.org/abs/2603.17605.md

I read abstracts and search summaries for these, not the full papers. Read each one before citing it.
