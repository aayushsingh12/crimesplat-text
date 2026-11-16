# 02. What will not work as you imagine it

Each section says what you described, why it fails, and the version that does work.

## 1. Blood spatter analysis through 3DGS

**What you described:** a splat of the scene used for digital forensics such as blood spatter analysis, and a paper built on that.

**Why it fails.**

- **Wrong measurement.** Bloodstain pattern analysis measures the width and length of individual stains (a few millimetres each) to get impact angles, then intersects those directions to estimate an area of origin. That measurement is made on sharp, scaled, perpendicular 2D photographs. A splat is a blurred, learned re-rendering of those photographs. It cannot be more accurate than its inputs and yours is far less accurate: 12 dB PSNR on the photo scene.
- **Your own negative result.** Stain-level detail needs macro photographs. Your second-scene test showed macro close-ups break structure-from-motion because they share no features with the wide shots.
- **No metric scale.** The image pipeline has none. Area-of-origin results are reported in centimetres.
- **No ground truth.** The stains in the Galanakis scene are printed sheets lying on a floor. There is no impact event and no known origin to compare against.
- **The bar is already set by dedicated tools.** Published area-of-origin errors are roughly 5 to 17 cm: FARO Zone 3D about 5.7 cm in a preliminary validation, HemoVision's photogrammetric method 8.12 cm, a least-squares method 17.29 cm for near-wall impacts. Cho and Woo's 3DGS accuracy study reports that small, thin items such as bloodstains have the highest relative error.
- **The discipline itself is contested.** Reviews of forensic science since 2009 have questioned its error rates, and I recall a 2021 black-box study of analysts reporting about 11 % erroneous conclusions on samples with known cause (verify the figure before citing). A CS capstone with no forensic co-author and no wet-lab experiments will not be reviewed kindly in that field.
- **Time.** A valid experiment needs blood or a validated substitute, controlled impacts with measured origins, and repeated trials. You have four weeks.

**What does work.** Use the splat as a *spatial index* to the stain photographs. The investigator sees where each stain photo was taken, clicks a stain, and gets the original macro image with its scale bar. The analysis stays with the analyst and the original photo. That is documentation, and it is honest.

## 2. "See who is lying"

**Why it fails.** The system can detect that two statements disagree. It cannot know why. Honest witnesses disagree constantly: memory, stress, viewing angle, time estimates. A dashboard that ranks people by suspected deception will produce confident wrong leads and will be attacked on ethical grounds by any reviewer.

**What does work.** Surface *discrepancies*, each with both source quotes side by side, a type (time, place, identity, sequence, physically impossible) and no verdict. Add the geometry checks from [03](03-where-it-shines.md): those separate "disagrees with another person" from "disagrees with the room". Never write "lying" in the interface, the slides or the paper.

## 3. A panoptic scene graph across the duration of the crime

**What you described:** a scene graph at 9:00, another at 9:34, covering the whole crime, saved in Neo4j.

**Why it fails.**

- A panoptic scene graph is computed from pixels. For almost every crime there are no pixels of the act. Bodycam and crime-scene photos are recorded afterwards. CCTV, when it exists, is a fixed camera at low resolution.
- So the graph "at 9:00" comes from what people said, which makes it a graph of claims, not a scene graph. Calling it a 4D panoptic scene graph invites a reviewer to ask for PSG metrics you cannot report.
- PSG models are trained on everyday categories (person, car, road, bench). They have no classes for blood, casings, ligatures or wounds, and the relations they output ("person on floor") are not forensic findings. Your own demo of it is a street scene.
- PSG-4D methods need RGB-D or multi-view video of the dynamic event. The video repo's own research note concludes that dynamic reconstruction from one moving camera is not feasible for this footage.

**What does work.**

- Call the main structure what it is: a **temporal claim graph** with intervals and provenance. That is already the Neo4j design.
- Per time window, show the *asserted* state of the world: who was where, according to whom, with contested facts marked contested.
- Keep image scene-graph output as a minor source of image claims, or drop it. It is not carrying weight.

## 4. CLIP matching photos to people and descriptions

**Why it fails.**

- CLIP similarity scores are compressed into a narrow band. Your own table shows every query between 0.249 and 0.323, with wrong answers inside the band of right ones.
- CLIP does not identify individuals. Matching a photo to "Jennifer Short" is face recognition, which CLIP does badly and which you should not be doing on real victims anyway.

**What does work.**

- Use captions and metadata first. The Short family images in your deck already have captions ("Jennifer Short room mattress"). Run the *text* pipeline on the caption and link through entities.
- Use CLIP only to *rank suggestions* that a person accepts or rejects. Every image-to-entity link is human-confirmed and records who confirmed it.

## 5. Splatting whatever footage a case happens to have

- **Fixed CCTV cannot be reconstructed.** One static viewpoint has no parallax. The video repo lists this as a hard blocker.
- **Real bodycam is hard.** Fisheye lens, motion blur, low light, people filling the frame. The only real clip tested so far is a calm phone walk-through of an empty room.
- **Standard forensic photo sets fail.** Overall, mid-range and close-up photography is not walk-through capture, and your second scene shows what happens.
- **News photos of a real case** (the Short family images) are single low-resolution views. They cannot be reconstructed at all.

**What does work.** State a capture protocol as a requirement: a slow walk-through video of the scene, at least 1080p, original file, textured floor in view, a scale reference. That is a contribution in itself, and Indian procedure now produces exactly this kind of video (see [06](06-police-workflow-fit.md)).

## 6. The splat as evidence, and as a measuring tool

- A splat is an optimised appearance model. It contains floaters and invented surfaces in poorly observed regions. A court will ask for the method's known error rate, and a 3DGS render has none that transfers between scenes.
- The image pipeline has no scale. The video pipeline's scale comes from an assumed camera height. Neither supports a statement like "the knife was 1.4 m from the body".

**What does work.**

- Position the splat as an *investigative and briefing aid*. Every view can be snapped back to a source frame.
- Add ArUco markers or scale bars to the capture, compute scale from them with the tools already in `crime-splat/pipelines/image/eval/`, and report every distance with its error. Without that, show no distances.

## 7. Storage

You said the project makes storage easier. It does not reduce storage: originals must be kept unmodified with their hashes, and the splat is an extra derived file. The real gain is *findability*: one case, one index, every item reachable from a time, a place, a person or a claim. Say that instead.

## 8. Cloud language models on case files

Real case files cannot be sent to a commercial API. If the extraction step depends on one, the system is a demo only. Run the extraction on a local model for the paper, or state the limitation plainly and use only staged data.

## 9. The Short family case as the demo

It is a real, unsolved triple homicide with a child victim. Your dashboard screenshot has a "suspect" entity with a sketch attached. A machine-generated graph that attaches claims to a named or pictured person in an open case is an ethical and reputational risk for a university project, and you cannot evaluate against it because nobody knows the truth. Use it, at most, as a text-only stress test of extraction. Use a staged case for everything shown publicly.
