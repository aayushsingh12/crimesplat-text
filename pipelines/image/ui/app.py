"""Text-query-to-3D-highlight demo UI.

Streamlit front end for the query -> rendered image backend. Wired to the
two real, verified end-to-end results from Phase 2 (see
pipelines/image/docs/phase2_decision.md) -- NOT a live call into the
SAM+CLIP pipeline. That pipeline is CPU-based (SAM mask generation +
region tagging) and takes minutes, not demo-interactive seconds, and has
only ever been exercised on these two queries. Any other input text gets a
clear "not yet supported" state rather than silently attempting to run the
real pipeline live.

Run:
    streamlit run app.py
"""

from pathlib import Path

import streamlit as st

ASSETS_DIR = Path(__file__).parent / "assets"
PLACEHOLDER_IMAGE = ASSETS_DIR / "placeholder.png"

EXAMPLE_QUERIES = ["blood spatter", "a car"]


# ---------------------------------------------------------------------------
# INTEGRATION POINT
#
# Real backend results, not live calls. Both were produced by the actual
# pipeline (pipelines/image/scripts/tag_regions.py -> query_regions.py ->
# render_query.py) against the galanakis2021 checkpoint and copied here --
# see phase2_decision.md for the full run. Contract:
#     run_query(text: str) -> dict with keys:
#         status: "match" | "low_confidence" | "unsupported"
#         image_path: str | None
#         similarity: float | None
#         message: str
# ---------------------------------------------------------------------------
QUERY_RESULTS = {
    "blood spatter": {
        "status": "match",
        "image_path": str(ASSETS_DIR / "blood_spatter_result.jpg"),
        "similarity": 0.3226,
        "message": 'Verified match (similarity 0.3226). Marker lands on a blood-marked evidence card.',
    },
    "a car": {
        "status": "low_confidence",
        "image_path": str(ASSETS_DIR / "car_result.jpg"),
        "similarity": 0.2592,
        "message": (
            "Low-confidence match — this query returned a result, but the system "
            "could not distinguish it from a real match. See known limitation below."
        ),
    },
}


def run_query(text: str) -> dict:
    """Looks up a pre-computed, verified result for the exact two queries
    this demo has actually run end-to-end. Does NOT invoke the real
    SAM+CLIP pipeline live -- see module docstring."""
    key = text.strip().lower()
    if key in QUERY_RESULTS:
        return QUERY_RESULTS[key]
    return {
        "status": "unsupported",
        "image_path": None,
        "similarity": None,
        "message": (
            "Not yet supported in this demo — only \"blood spatter\" and \"a car\" "
            "have verified end-to-end results. The real pipeline is CPU-based "
            "(SAM + CLIP) and untested on arbitrary queries, so it is not run live here."
        ),
    }


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="3D Scene Query", page_icon="🔎", layout="centered")

st.title("🔎 Text-Query-to-3D-Highlight")
st.caption(
    "Enter a natural-language query to locate and render the matching region "
    "in the reconstructed 3D scene."
)

st.info(
    "**Proof-of-concept on one scene.** Two verified queries only "
    "(\"blood spatter\", \"a car\"). Similarity-score threshold not yet "
    "reliable — see the limitation below before treating any result as "
    "confirmed.",
    icon="⚠️",
)

if "query_text" not in st.session_state:
    st.session_state.query_text = ""

st.subheader("Example queries")
example_cols = st.columns(len(EXAMPLE_QUERIES))
for col, example in zip(example_cols, EXAMPLE_QUERIES):
    if col.button(example, width='stretch'):
        st.session_state.query_text = example

with st.form("query_form"):
    query_text = st.text_input(
        "Query",
        key="query_text",
        placeholder='e.g. "blood spatter"',
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("Search", width='stretch')

st.divider()

result_area = st.container()

if submitted:
    if not query_text.strip():
        st.warning("Enter a query before searching.")
    else:
        with st.spinner(f'Searching for "{query_text}" ...'):
            result = run_query(query_text)
        with result_area:
            st.subheader("Result")
            if result["status"] == "unsupported":
                st.warning(result["message"])
                st.image(str(PLACEHOLDER_IMAGE), width='stretch')
            else:
                if result["status"] == "low_confidence":
                    st.warning(result["message"], icon="⚠️")
                else:
                    st.success(result["message"], icon="✅")
                st.image(result["image_path"], width='stretch')
            st.caption(f'Query: "{query_text}"')
else:
    with result_area:
        st.subheader("Result")
        st.image(str(PLACEHOLDER_IMAGE), width='stretch')
        st.caption("Submit a query to see a result here.")

st.divider()
st.caption(
    "**Known limitation:** similarity score alone does not reliably separate "
    "real matches from absent-object queries in this scene — 0.2592 (\"a car\", "
    "absent) and 0.3226 (\"blood spatter\", present) both sit in the same "
    "moderate CLIP-similarity band, not the wide separation a safe fixed "
    "threshold would need. Consistent with known CLIP zero-shot score "
    "compression. As it stands, the system will confidently mark a wrong "
    "answer for a query about something that isn't in the scene, with "
    "nothing in the output to distinguish that from a real match. Full "
    "detail in pipelines/image/docs/phase2_decision.md."
)

# ---------------------------------------------------------------------------
# Live 3D viewer (ns-viewer) -- link-out, not an embed
#
# An embedded iframe (st.components.v1.iframe) was attempted against
# ns-viewer on this checkpoint and stalls indefinitely at nerfstudio's own
# eval-image-caching step, with the viser HTTP/websocket server already up
# but the scene never finishing init -- no error, just no progress past
# that point. Rather than embed a viewer that will show a permanently
# blank/loading frame, this links out to wherever ns-viewer is actually
# running (start it yourself: see README), so the link works in any
# environment where the viewer doesn't hit this stall.
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Live 3D viewer")
st.caption(
    "An embedded live view was attempted (ns-viewer + st.components.v1.iframe) "
    "and did not work reliably in this environment -- it stalls at nerfstudio's "
    "eval-image-caching step with no error. Linking out instead: start "
    "`ns-viewer --load-config outputs/colmap_pruned/splatfacto/2026-08-24_010039/config.yml` "
    "yourself, then open it below once it's ready."
)
st.link_button("Open ns-viewer in a new tab", "http://localhost:7007", width='stretch')
