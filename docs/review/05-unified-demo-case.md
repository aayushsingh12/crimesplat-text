# 05. One case that exercises everything

## 1. Why the current demo cannot be connected

| Dataset | Text | Photo set for 3D | Video | Ground truth |
|---|---|---|---|---|
| Short family | Yes (news, FBI notes) | No (single news photos) | No | None; the case is unsolved |
| Galanakis 2021 room | No | Yes (30 photos) | No | None measured by you |
| Your bedroom clip | No | No | Yes | None |

No entity appears in more than one of these. There is nothing for a fusion step to fuse. This is a data problem, and it is solved with one afternoon of filming.

## 2. The staged case

Write a fictional incident, stage it in a room you control, and capture every modality of the same scene. Because you wrote the script, you know the truth, which gives you evaluation numbers for every stage.

### Scenario (example; change freely)

A break-in at a hostel room or flat. One "victim" (a mannequin, a stuffed dummy or a taped outline; avoid a real person lying on the floor in published images). One intruder, played by a teammate, seen by two "witnesses". Props: a toy knife, an overturned chair, a dropped phone, a bag, red-paint stains on paper sheets.

### What to script

- **A true timeline**, minute by minute: who was where, what moved.
- **Four to six documents**:
  - a first-information-style police report;
  - three witness statements;
  - a scene examination note listing the evidence items and their positions;
  - a short news item written from the outside.
- **Planted discrepancies**, 8 to 12 in total, each labelled in a hidden answer file:

| Type | Example |
|---|---|
| Time | Witness A says 21:10, witness B says 21:40 |
| Identity | "Tall man in a red jacket" against "short, dark hoodie" |
| Sequence | Chair fell before the shout, against after |
| Position | Phone on the desk, against phone on the floor in the scene video |
| Line of sight, impossible | Witness C claims to have seen the knife from a spot where the wardrobe blocks the view |
| Line of sight, possible | A control: a claim that the geometry supports |
| Travel time, impossible | Seen at the gate and in the room 5 seconds apart |

Include true statements that merely sound odd, so the system is tested for false alarms too.

### What to capture, in this order

1. **Markers and scale.** Print 8 to 10 ArUco markers, tape them flat to the floor and walls, and measure 6 to 8 marker-to-marker distances with a tape. Add a printed scale bar next to each stain sheet.
2. **Walk-through video**, the main input. Phone held at chest height, 1080p or 4K, original file, slow, two loops of the room, textured floor in view. Follow `crimesplat-video/docs/gpu-day-runbook.md`.
3. **A second walk-through with a person moving through**, to exercise masking.
4. **Still photographs** as walk-around capture: 60 to 100 overlapping photos, then mid-range and close-up shots of each evidence item *with the surroundings still in frame* so they register.
5. **Witness-position photos.** Stand at each scripted observer position at eye height and photograph towards each scripted target. These are the ground truth for the visibility checks.
6. **Optional fixed camera** on a tripod recording the acted incident. It cannot be splatted, but it shows how fixed-camera footage attaches to the timeline as a located source.

Everyone on camera consents in writing. Nothing from a real case appears.

## 3. How the modalities connect

The connection is a set of shared identifiers and anchors, not a model.

```
document ──quote──► Claim ──resolved──► Entity (person / object / place) ──anchor──► xyz in scene S
                      │                     ▲                                   ▲
                      └── t_start, t_end    │ confirmed link                    │ pin dropped in viewer
photo / video frame ──► image region ───────┘                                   │
video ──► Scene S (splat, camera path, frame times) ────────────────────────────┘
```

- **Entity.** One node per real-world thing, produced by fusion from claims.
- **Anchor.** A 3D point (or small box) in a named scene, with who placed it and how. A person can have many anchors, each with a time interval.
- **Evidence.** Every document, photo and video, with its hash.
- **Scene.** One per reconstruction, with its coordinate frame and scale status.

### Where anchors come from

| Source | Reliability | Use |
|---|---|---|
| Human pin in the viewer | High | Primary. A case of this size needs about 20 pins, a few minutes of work |
| Scene examination note with measurements | High if scale is known | Convert measurements to coordinates from a marker origin |
| SAM + CLIP text query | Low | Suggestions only; a person accepts or rejects |
| Camera pose of a photo or frame | High | "This photo was taken from here" |

Do not try to automate anchoring for the capstone. Human pins with recorded provenance are defensible. Automatic ones are not, on your own evidence.

## 4. The demo, as the examiner sees it

1. **Open the case.** Timeline along the bottom with three lanes (text, image, video). Documents on the left, the scene in the centre.
2. **Click the police report.** Claims highlight in the text. Click one: "phone found on the floor near the desk". The camera flies to the phone's pin. The panel shows the two source frames that observed that spot.
3. **Open discrepancies.** A list of the planted contradictions, each with two quotes. Pick the time conflict; both witnesses appear as overlapping bands on the timeline.
4. **Run the line-of-sight check** on witness C. The view jumps to C's position at eye height. The wardrobe blocks the knife. The claim is marked "not supported by geometry", with the rendered view and the real photo from that position side by side.
5. **Run it on the control claim.** It passes. This matters: it shows the check does not flag everything.
6. **Scrub the timeline.** Pins for people move between their asserted positions; contested positions show as two ghosted markers labelled by source.
7. **Ask a question** in plain language: "Who was in the room at 21:15 and who says so?" The answer lists entities with their claims and quotes.
8. **Show a failure.** A region with poor coverage is shaded "not enough data". A query for an absent object returns its caveat.

Steps 4 and 5 are the ones people will remember.

## 5. What this case gives you besides a demo

- Ground truth for every table in the system paper ([04](04-publication-strategy.md)).
- A metric test scene for the COLMAP fallback paper.
- A dataset you can publish: videos, photos, documents, script, measurements.
- A regression test: rerun the whole case after every change.
- A clean answer to the ethics question.

## 6. Keep the Short family material for one thing only

Use it as a text-scale stress test: how the extraction behaves on 14 real, messy documents. Report counts and review-queue size. Show no photographs of the victims and no suspect node in any public material.
