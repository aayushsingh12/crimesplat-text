# 06. How investigations work today, and where this fits

I am describing general practice from background knowledge, not from interviews. Statute section numbers below are from memory: check each against the bare act before it goes on a slide. One conversation with a serving investigating officer or a forensic science laboratory scientist would be worth more than this whole document; try to get one before the final review.

## 1. How a serious case is worked

| Stage | What happens | What it produces |
|---|---|---|
| Report | A complaint is registered (in India, an FIR) | A short narrative, often second-hand |
| First response | Officers secure the scene | Notes, sometimes bodycam or phone video |
| Scene examination | Photographs (overall, mid-range, close-up with scale), sketch with measurements, video, evidence collection, seizure memo | Hundreds of photos, a hand sketch, lists |
| Statements | Witnesses, victim, suspects, each recorded separately, often several times | Pages of narrative with vague times |
| External records | CCTV pulls, call detail records, post-mortem, lab reports | Files in many formats, arriving over weeks |
| Analysis | The investigating officer builds a timeline and a theory | A case diary, link charts, and a lot held in memory |
| Charge | The file is assembled for the prosecutor and court | A charge sheet with annexures |

## 2. Where it hurts

- **The scene is perishable.** It is released within hours or days, then cleaned, reoccupied or demolished. Every later question about the space has to be answered from whatever was captured on day one.
- **Photos do not carry spatial relationships.** Three hundred photographs do not tell you whether the hallway is visible from the bed. The sketch helps but is a flat drawing made by hand.
- **Statements are compared by reading.** Contradictions across fifty pages are found by a person who remembers page 12 while reading page 40.
- **Sources live in separate systems.** Records in one system, photos on a disc, CCTV on a drive, lab reports on paper.
- **Handover loses knowledge.** Officers are transferred. Long cases change hands. The new officer inherits the paper but not the mental model.
- **Tunnel vision.** Once a theory forms, facts that do not fit it are easy to miss.
- **Good 3D capture is rare.** Laser scanning is accurate but expensive and needs trained staff, so most scenes get photos and a sketch.

## 3. Where your project helps, pain by pain

| Pain | What the project offers | How strong |
|---|---|---|
| Perishable scene | A walkable reconstruction from one phone video, on a laptop GPU | Strong, if the capture protocol is followed |
| Photos without spatial context | Click a surface to see every frame that observed it; snap to the source view | Strong; already built in the video viewer |
| Reading-based comparison | Claims on a common timeline, discrepancies listed with both quotes | Strong for text; needs the rebuilt pipeline |
| "Could they have seen that?" | Line-of-sight and travel-time checks on the reconstruction | The distinctive part; not yet built |
| Scattered sources | One case index reachable by time, place, person or claim | Moderate; it is an index over files, not a records system |
| Handover | Timeline, claim graph and scene as a briefing | Moderate |
| Tunnel vision | Contested facts stay visible instead of being resolved away | Moderate; depends on interface design |

## 4. Why reconstruction matters to them

- **Hypothesis testing.** Positions, sightlines, reach, paths and timings are spatial questions. They cannot be asked of a photograph.
- **Sequence.** Where things ended up constrains the order in which things happened.
- **Statement testing.** A reconstruction is a neutral reference to hold accounts against.
- **Briefing.** Supervisors, prosecutors and judges understand a space faster by moving through it than by reading a description.
- **Revisiting.** Years later, a cold-case reviewer or an appeal court can look again without the scene existing.

## 5. The Indian opening

Your project is at a Bengaluru university, so the local procedure is the best motivation you have.

- The Bharatiya Nagarik Suraksha Sanhita, 2023 requires a forensic expert to visit the scene and the process to be video-recorded for offences punishable with seven years or more (I recall section 176(3)), and requires audio-video recording of search and seizure (I recall section 105). An official mobile application (eSakshya) exists for recording and uploading this material.
- The Bharatiya Sakshya Adhiniyam, 2023 governs admissibility of electronic records, with a certificate requirement (I recall section 63, the successor to the old 65B).

What follows from that:

- Walk-through video of serious crime scenes is now produced as routine. Today it is watched, at best. Your video pipeline turns that same file into a navigable scene with no extra equipment.
- Hashing at ingest and an append-only provenance log, which the video pipeline already has, are what the certificate regime expects. Say so.
- The reconstruction is a *derived* aid. The certified original video remains the evidence. This framing avoids the admissibility fight.

## 6. What a police reader will reject

- **Anything that looks like automated accusation.** A "who is lying" score would end the conversation.
- **Unexplained numbers.** A distance without an error bar, a confidence without a meaning.
- **Cloud processing of case material.** It must run on local hardware.
- **Extra work at the scene.** If capture takes more than a few added minutes, it will not happen. A two-loop walk-through and a few printed markers is about the limit.
- **A tool that needs a specialist.** The officer must be able to run it.
- **Reconstructions that look real but are wrong.** Shade or hide poorly observed regions rather than render plausible fill.

## 7. How to describe the tool

- It is a case review aid: an index of the file, a comparison of accounts and a reconstruction to test them against.
- It is not evidence, not a measuring instrument without markers, and not a judge of credibility.
- Every item on screen links to its source, and every machine suggestion is labelled and awaits a person.

## 8. Questions to put to an officer or forensic scientist

1. How is the scene video used after it is recorded?
2. How do you compare statements across witnesses today?
3. Which spatial question came up late in a case that the photographs could not answer?
4. Would you trust a reconstruction to brief a prosecutor? What would it need to show?
5. Who would run a tool like this: the investigating officer, a forensic unit, a cyber cell?
6. What can leave the station's network, and what cannot?

Two or three quoted answers in your report and paper will do more for the "usefulness to the crime department" argument than any feature.
