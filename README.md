# crimesplat-text

Text pipeline and dashboard for *Crime Scene Reconstruction using Scene Graphs*.
It turns a case file into grounded claims, builds a temporal scene graph from them, and shows
the graph in a dashboard that works like a video editor: drag the playhead along the timeline
and the graph shows what the case file asserts for that moment.

## What it does

```
case page ──fetch──► numbered passages + source files + captioned photos
passages  ──chunk──► extraction chunks
chunks    ──extract (LLM)──► claims: subject, predicate, object, verbatim quote, certainty, source
claims    ──build──► entities, timed claims, events  =  build/bundle.json
bundle    ──serve──► dashboard
```

- **Passage.** One bullet or paragraph of the case file. It is the unit of evidence.
- **Claim.** One subject-predicate-object triple that a passage asserts. A claim is kept only if
  its quote is a verbatim substring of its passage. Nothing is marked as true: each claim keeps
  its wording strength (stated, reported, alleged, speculated) and who the passage attributes it to.
- **Entity.** A node. Following the panoptic split, a *thing* is a countable instance that can be
  followed over time (person, group, object, weapon, vehicle, document) and *stuff* is a setting
  (location). Descriptions such as clothing or state are attributes on the node.
- **Time.** Every claim has an interval, taken from the passage's own wording when it gives one
  and from its date heading otherwise. A node's claims over time form its track on the timeline.
- **Event.** A beat of the case: the claims of a group of passages. The crime itself is an
  `action_point`; the others are discovery, investigation, legal, media and background.

The graph is built from text, so it is a graph of what sources say, organised like a panoptic
scene graph. It is not computed from pixels.

## Run it

Python 3.10+ with no extra packages. `pdftotext`, `pdftoppm` and `tesseract` are used for scanned
files if they are installed.

```bash
python -m crimetext fetch cases/short_family
```

```bash
python -m crimetext chunk cases/short_family
```

```bash
python -m crimetext build cases/short_family
```

```bash
python -m crimetext serve cases/short_family
```

Then open http://127.0.0.1:8765/.

The extraction output for the Short family case is already in `cases/short_family/work/extract/`,
so `extract` can be skipped. To run it again:

```bash
python -m crimetext extract cases/short_family --backend claude-cli --model haiku --force
```

Backends: `claude-cli` (the `claude` command, logged in), `ollama` (a local model, for case
material that must not leave the machine), `files` (another tool writes the chunk outputs).
The prompt is `crimetext/prompt.md`. To check one chunk by hand:

```bash
python -m crimetext.extract cases/short_family chunk_003.json
```

## Dashboard

| Area | What it shows |
|---|---|
| Timeline (bottom) | Event clips on one track per kind, claim density, a track per main entity, photo markers, a draggable playhead. Wheel zooms, shift-drag pans, space plays through the events. |
| Stage (centre) | The scene graph for the event under the playhead. Circles are things, squares are places. Solid arrows are stated, dashed are reported, dotted are alleged or speculated. |
| Modes | **Event**: one event's claims. **Up to now**: everything asserted before the playhead. **Entity**: every claim about one entity. |
| Left | Events, source passages, photos with captions, entities. |
| Inspector (right) | For any node, arrow, claim, event, passage or photo: the claims behind it, the exact quote highlighted in its passage, the source file and its SHA-256. |

## A new case

Make `cases/<name>/case.json` with `title`, `source_url`, the `timeline_section` heading, an
`incident_window`, optional `section_times` (a date for an undated section) and optional `aliases`
(names to merge). Put extra photos in `cases/<name>/photos/` and their captions in
`captions.json`. Then run the commands above.

## Limits

- Entity merging is rule-based plus the `aliases` list. Unnamed people ("unidentified man ...")
  are kept apart on purpose.
- The Short family extraction was done by Claude Haiku. All 737 claims pass the quote check;
  the quote check does not prove that the triple reads the quote correctly, and no one has
  reviewed the claims by hand yet.
- Newspaper scans are downloaded, hashed and OCR'd for reference. Claims are extracted from the
  case page only.
- One source inconsistency is kept as written: a witness is "Rick Lemons" in one passage and
  "Gary Lemons" in others.
- Photo dates come from file names and captions. Photos are linked to entities by caption text.

`docs/review/` holds the project review written before this pipeline.
