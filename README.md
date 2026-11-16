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

| Page | What it is for |
|---|---|
| **Intake** | Where the case stands (collect, extract, build, review, scenes) and where material is added: official documents (witness statements, police reports, lab reports, court papers), photographs, scene photographs, footage. |
| **Case file** | The file as a navigable record: people, agencies, places, objects and weapons, vehicles, events, documents and sources with hashes, photographs, 3D scenes, and the review record. Every row opens in the investigation. |
| **Investigation** | The timeline workspace. Bottom: event clips per kind, claim density, a track per main entity, photo markers, a draggable playhead (wheel zooms, shift-drag pans, space plays). Centre: the scene graph for the event under the playhead, or the 3D scene with its pins. Right: for any node, arrow, claim, event, passage or photo, the claims behind it, the quote highlighted in its passage, the source and its SHA-256. |
| **Scene from photos** | The image pipeline: the splat, its source viewpoints, text search in the scene, the photo set, and the pipeline's requirements and run button. |
| **Scene from video** | The connection to the video pipeline: store footage with its hash, start the pipeline on it, and import the finished scene into the case. |

### Analysis and Workbook

**Analysis** is recomputed from the claims on every visit, so it follows review decisions.

- **Points to compare.** Places where the file says two things about one subject: suspected and
  later cleared, found at more than one place, stated as fact in one passage and alleged in
  another, the same fact on different dates, differing descriptions of an unidentified person.
  Both passages are shown side by side with no verdict. Items can be dismissed or turned into
  an action.
- **Corroboration.** How many passages repeat each fact, and which accusations (killing,
  abduction, suspicion, arrest, charge) rest on a single passage.
- **Leads and gaps.** People who gave information with no interview recorded, people and
  vehicles still unidentified, items collected with no examination recorded, and stretches
  around the incident with nothing recorded for a key person. Each means "no record in this
  file", not "not done".
- **Connection finder.** The shortest chain of claims linking any two entities.
- **Person dossier** and **Case brief.** One printable page per person, and a printable summary
  of the case with open points, actions and hypotheses.

**Workbook** is the investigator's own record, stored under `casework/` and kept apart from the
graph: actions (with assignee and due date, tied to a claim, person or event), notes, and
hypotheses. A hypothesis collects claims marked as supporting or contradicting it and shows the
balance weighted by claim confidence. Any claim, entity or event in the investigation has
"+ Action", "+ Note" and "Add to hypothesis" at the top of the inspector.

### Human review

Every claim gets a confidence between 0 and 1 from fixed rules (`crimetext/review.py`): the strength
of the passage's wording, minus points for a subject or object that is not named in the passage,
unnamed parties, accusatory relations, missing dates and very short quotes. Claims under the
threshold (`review_threshold` in `case.json`, default 0.70) wait in the Review tab, lowest first.
A reviewer opens the claim, reads the passage, and accepts or rejects it (keys A and R). Rejected
claims leave the graph. Decisions are stored in `review/decisions.json` with reviewer, time and
note, and every action is appended to `review/log.jsonl`.

### 3D scenes and the image pipeline

`pipelines/image/` is the image pipeline from the crime-splat repository (COLMAP, nerfstudio
Splatfacto, pruning, SAM + CLIP region tagging, text query, export), with its documentation.
Its two research data trees (`eval/results`, `strengthen`) are not copied.

```bash
python -m crimetext scene cases/short_family --splat /path/to/splat.ply --id bedroom --title "Bedroom" --location "Bedroom of the Short residence [for demo purposes]"
```

This copies the splat into `scenes/<id>/` with its hash and takes the pipeline's camera poses,
photo labels and stored query results from `pipelines/image/`. In the dashboard:

- **Viewpoints.** Each registered source photo is a button that puts the camera exactly where
  that photo was taken.
- **Find in scene.** Text search answers in the shape of the pipeline's query server. With the
  pipeline's `region_lookup.json` in the scene folder and `open_clip` installed it runs live
  CLIP matching through `pipelines/image/scripts/query_regions.py`. Without them it serves the
  queries the pipeline already ran, with their rendered results and hand-checked verdicts, and
  says so. The pipeline's own caveat is always shown: similarity does not separate real matches
  from absent objects.
- **Pins.** Select an entity, choose "Pin in 3D scene", click the surface. A pin stores the
  entity name, the point in the splat frame, who placed it and when. Pins are never placed
  automatically.
- **Run the pipeline.** "Scene from photos" checks the pipeline's requirements (COLMAP, the two
  conda environments, an 8 GB GPU, at least 18 photos) and starts `pipelines/image/quickstart.sh`
  on the scene's photos when they are met.

The scene has no metric scale, so the dashboard shows no distances.

### The video pipeline

The video pipeline lives in its own repository (crimesplat-video) and is used in place, not
copied. `crimetext/videopipe.py` finds it (`video_pipeline_dir` in `case.json`, else
`$CRIMESPLAT_VIDEO`, else `~/Projects/crimesplat-video`), checks that it can run (repository,
`uv`, its environment, `ffmpeg`, a GPU), and for a stored footage file runs
`crimesplat init` and `crimesplat run` with the compute profile that fits the GPU. When the
pipeline has written its Scene Package, the package is imported as a scene of the case: splat,
camera path as viewpoints, frame thumbnails as source views, units and quality figures. From
then on it behaves like any other scene: pins, viewpoints, the scene picker in the investigation.

### Demo links

`cases/short_family/demo/links.json` holds hand-written links between the 3D scene and the case:
the reconstructed room stands for a bedroom of the Short residence, the mannequin for Michael
Short, the blood stains are tied to the .22-caliber pistol named in the case file, and so on.
None of this comes from the case file. Every such entity carries **[for demo purposes]** in its
name, every such claim is flagged, drawn in purple with a dashed outline, excluded from review,
and can be hidden with one chip. The scene itself is the Galanakis 2021 staged forensic room.
There is no knife or other weapon in that scene, so no weapon is pinned.

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
- No language-model backend was reachable on the development machine, so `extract` and the
  dashboard's "Run extraction" button have only been seen to fail cleanly. Documents added through
  Intake are stored, hashed and cut into passages, and wait for extraction.
- The image pipeline's requirements are not installed on the development machine, so "Run image
  pipeline" has not been run from the dashboard. The splat in the demo was built by the pipeline
  elsewhere.
- The video connection was checked by importing an existing synthetic Scene Package and viewing
  it. A full run started from the dashboard has not been done yet.
- Live CLIP search needs the pipeline's region index, which is not in the crime-splat repository.
- Newspaper scans are downloaded, hashed and OCR'd for reference. Claims are extracted from the
  case page only.
- One source inconsistency is kept as written: a witness is "Rick Lemons" in one passage and
  "Gary Lemons" in others.
- Photo dates come from file names and captions. Photos are linked to entities by caption text.

`docs/review/` holds the project review written before this pipeline.
