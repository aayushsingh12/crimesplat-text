# Text-Query-to-3D-Highlight — UI

A Streamlit front end for the query -> rendered PNG backend. This directory is
self-contained and independent of the rest of `pipelines/image/` — it needs no
GPU and doesn't touch COLMAP/Splatfacto/SAM/CLIP code.

Wired to the **two real, verified end-to-end results** from Phase 2 (see
`pipelines/image/docs/phase2_decision.md`) — not a live call into the
SAM+CLIP pipeline. That pipeline is CPU-based and takes minutes per image,
not demo-interactive seconds, and has only ever been exercised on these
two queries.

## Running it

```bash
cd pipelines/image/ui
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (defaults to http://localhost:8501).

Try the two example query buttons — `"blood spatter"` (a verified match) or
`"a car"` (a verified low-confidence/wrong match, kept in the demo
deliberately to show the known threshold limitation). Any other text
returns a "not yet supported in this demo" state rather than silently
attempting to run the real pipeline live.

## Wiring up the real backend

The UI's integration point is still the single contract:

```
run_query(text: str) -> dict  # status, image_path, similarity, message
```

**The only place to edit is `run_query()` and the `QUERY_RESULTS` lookup in
`app.py`.** To add a new verified query, run the real pipeline
(`tag_regions.py` -> `query_regions.py` -> `render_query.py`, see
`phase2_decision.md`), copy its rendered image into `assets/`, and add an
entry to `QUERY_RESULTS`. This UI intentionally does not call the CPU-based
SAM+CLIP pipeline live — every entry in `QUERY_RESULTS` must be a real,
already-rendered result, not a live inference.

## Files

- `app.py` — the Streamlit app (UI + the `run_query()` integration point).
- `generate_placeholder.py` — one-off script that generated
  `assets/placeholder.png`. Not needed at runtime; rerun only if you want to
  regenerate the placeholder image.
- `assets/placeholder.png` — the "no result yet" mock image.
- `requirements.txt` — pinned dependency (Streamlit) for this UI's venv.
