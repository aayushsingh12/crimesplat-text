/* Pages around the investigation workspace: intake, case file, scene from photos, scene from video. */
window.addEventListener("desk-ready", () => {
  const D = window.__desk, B = D.B, esc = D.esc, $ = (s) => document.querySelector(s);
  const DAY = 864e5, fmt = (iso) => (iso ? D.fmtDay(new Date(iso)) : "–");
  const kb = (n) => (n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.round(n / 1e3) + " KB");
  const demoTag = '<span class="demo-tag">for demo purposes</span>';
  const pendingN = () => B.claims.filter((c) => D.status(c) === "pending").length;

  // ---------- navigation ----------
  const pages = ["home", "file", "investigate", "analysis", "work", "image", "video"];
  function nav(page, keepHash) {
    if (!pages.includes(page)) page = "home";
    pages.forEach((p) => { $("#page-" + p).classList.toggle("on", p === page); $(`#nav [data-page=${p}]`).classList.toggle("on", p === page); });
    if (!keepHash) history.replaceState(null, "", "#" + page);
    if (page === "home") renderHome();
    if (page === "file") renderFile();
    if (page === "image") renderImage();
    if (page === "video") renderVideo();
    if (page === "analysis") window.__renderAnalysis?.();
    if (page === "work") window.__renderWork?.();
    if (page === "investigate") window.dispatchEvent(new Event("resize"));
    $("#search").classList.toggle("hidden", page !== "investigate");
  }
  window.__nav = nav;
  $("#nav").onclick = (e) => e.target.dataset.page && nav(e.target.dataset.page);
  const openEntity = (id) => { nav("investigate"); D.focusEntity(id); };
  const openEvent = (id) => { nav("investigate"); D.closeScene(); D.gotoEvent(D.V.get(id)); };
  const openClaimQueue = () => { nav("investigate"); document.querySelector(".tabs [data-tab=review]").click(); };

  async function post(url, body, raw) {
    const res = await fetch(url, raw ? { method: "POST", body } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    return res.json();
  }
  function setMsg(el, text, ok) { el.textContent = text; el.className = "msg " + (ok ? "good" : "err"); }
  function dropzone(el, input) {
    el.onclick = () => input.click();
    el.ondragover = (e) => { e.preventDefault(); el.classList.add("over"); };
    el.ondragleave = () => el.classList.remove("over");
    el.ondrop = (e) => { e.preventDefault(); el.classList.remove("over"); input.files = e.dataTransfer.files; input.dispatchEvent(new Event("change")); };
    input.onchange = () => { el.querySelector("b").textContent = [...input.files].map((f) => f.name).join(", ") || "Drop files here or click to choose"; };
  }

  // ---------- intake ----------
  function renderHome() {
    const s = B.stats, docs = B.documents || [], waiting = docs.filter((d) => d.state !== "in graph");
    const inc = B.case.incident_window || [];
    $("#page-home").innerHTML = `<div class="wrap">
      <h1>${esc(B.case.title)}</h1>
      <div class="lead">Incident window ${esc(inc[0] || "?")} to ${esc(inc[1] || "?")} · primary source <a href="${esc(B.case.source_url)}" target="_blank" rel="noopener" style="color:#8ec5ff">${esc(B.case.source_url)}</a></div>
      <div class="tiles">
        <div class="tile" data-go="file:documents"><b>${s.evidence}</b><span>evidence items</span></div>
        <div class="tile" data-go="file:documents"><b>${s.passages}</b><span>passages</span></div>
        <div class="tile" data-go="investigate"><b>${s.claims}</b><span>grounded claims</span></div>
        <div class="tile ${pendingN() ? "warn" : ""}" data-go="review"><b>${pendingN()}</b><span>claims to review</span></div>
        <div class="tile" data-go="file:people"><b>${s.entities}</b><span>entities</span></div>
        <div class="tile" data-go="file:events"><b>${s.events}</b><span>events</span></div>
        <div class="tile" data-go="file:photos"><b>${s.photos}</b><span>photos</span></div>
        <div class="tile" data-go="image"><b>${D.SCENES.length}</b><span>3D scenes</span></div>
      </div>

      <h2>Where the case stands</h2>
      <div class="steps">
        <div class="step"><div class="n">1 · Collect</div><div class="t">${s.evidence} items on file</div><div class="d">Case page, ${B.evidence.filter((e) => e.kind === "file").length} scanned files, ${docs.length} added documents. Each is stored unmodified with its SHA-256.</div></div>
        <div class="step ${s.chunks_extracted < s.chunks ? "todo" : ""}"><div class="n">2 · Extract claims</div><div class="t">${s.chunks_extracted} of ${s.chunks} chunks read</div><div class="d">A language model turns each passage into claims. A claim is kept only if its quote is found word for word in the passage.</div>${s.chunks_extracted < s.chunks ? '<button id="run-extract">Run extraction</button><div class="msg" id="extract-msg"></div>' : ""}</div>
        <div class="step"><div class="n">3 · Build graph</div><div class="t">${s.entities} entities · ${s.events} events</div><div class="d">Names merged, every claim given a time interval, claims grouped into events.</div><button id="rebuild">Rebuild</button></div>
        <div class="step ${pendingN() ? "todo" : ""}"><div class="n">4 · Human review</div><div class="t">${pendingN()} waiting · ${B.claims.filter((c) => c.review).length} decided</div><div class="d">Claims under confidence ${B.review.threshold} wait for a person to accept or reject.</div><button data-go="review">Open review queue</button></div>
        <div class="step ${D.SCENES.length ? "" : "off"}"><div class="n">5 · Scenes</div><div class="t">${D.SCENES.length} 3D scene${D.SCENES.length === 1 ? "" : "s"}</div><div class="d">Reconstructed rooms, pinned to entities of the graph.</div><button data-go="image">Open scenes</button></div>
      </div>

      <h2>Add to the case</h2>
      <div class="cards">
        <div class="card"><h3>Official document</h3><p>Witness statement, police report, scene examination note, lab or medical report, court paper. Text, Markdown or PDF. It is cut into numbered passages and waits for claim extraction.</p>
          <div class="drop" id="doc-drop"><b>Drop files here or click to choose</b></div><input type="file" id="doc-file" accept=".txt,.md,.pdf" hidden>
          <div class="form"><label>Title</label><input id="doc-title" placeholder="Statement of …">
            <label>Type</label><select id="doc-type">${B.doc_types.map((t) => `<option value="${t}">${t.replace(/_/g, " ")}</option>`).join("")}</select>
            <label>Date of document</label><input id="doc-date" placeholder="August 16, 2002">
            <label>Author / source</label><input id="doc-author" placeholder="Henry County Sheriff's Office"></div>
          <div class="btns"><button id="doc-add">Add document</button></div><div class="msg" id="doc-msg"></div></div>
        <div class="card"><h3>Photograph</h3><p>A single photograph with its caption. The caption links it to people and places named in the case. Use a file name starting with the date (2002-08-15-…) to place it on the timeline.</p>
          <div class="drop" id="ph-drop"><b>Drop files here or click to choose</b></div><input type="file" id="ph-file" accept="image/*" hidden>
          <div class="form"><label>Caption</label><input id="ph-cap" placeholder="Kitchen of the Short residence"></div>
          <div class="btns"><button id="ph-add">Add photograph</button></div><div class="msg" id="ph-msg"></div></div>
        <div class="card"><h3>Scene photographs</h3><p>A set of overlapping photographs of one room, to be reconstructed in 3D by the image pipeline.</p><div class="btns"><button data-go="image">Go to Scene from photos</button></div>
          <h3 style="margin-top:16px">Video footage</h3><p>Body-camera or walk-through footage, to be reconstructed by the video pipeline.</p><div class="btns"><button data-go="video">Go to Scene from video</button></div></div>
      </div>

      <h2>Documents added to this case (${docs.length})</h2>
      ${docs.length ? `<table class="t"><tr><th>ID</th><th>Title</th><th>Type</th><th>Date</th><th>Passages</th><th>State</th><th>SHA-256</th><th></th></tr>${docs.map((d) => `<tr><td>${d.id}</td><td>${esc(d.title)}<div class="meta">${esc(d.author || "")}</div></td><td>${esc(d.doc_type.replace(/_/g, " "))}</td><td>${esc(d.date || "–")}</td><td>${d.n_passages}</td><td><span class="pill ${d.state === "in graph" ? "done" : "wait"}">${d.state}</span></td><td class="mono">${d.sha256.slice(0, 16)}…</td><td><a href="case/${esc(d.path)}" target="_blank">open</a></td></tr>`).join("")}</table>` : '<div class="lead">None yet. The case so far comes from the case page and its linked scans.</div>'}
      ${waiting.length ? `<div class="banner" style="border-color:#6b4a12;background:#2a2112;color:#f3d9a6">${waiting.length} document(s) are stored and cut into passages but not yet in the graph. Run extraction (step 2) once a language-model backend is available.</div>` : ""}
    </div>`;
    $("#page-home").onclick = (e) => {
      const go = e.target.closest("[data-go]")?.dataset.go; if (!go) return;
      if (go === "review") return openClaimQueue();
      const [p, sec] = go.split(":"); if (sec) fileSection = sec; nav(p);
    };
    dropzone($("#doc-drop"), $("#doc-file")); dropzone($("#ph-drop"), $("#ph-file"));
    $("#doc-add").onclick = async () => {
      const f = $("#doc-file").files[0], m = $("#doc-msg"); if (!f) return setMsg(m, "Choose a file first.");
      const q = new URLSearchParams({ kind: "document", name: f.name, title: $("#doc-title").value, doc_type: $("#doc-type").value, date: $("#doc-date").value, author: $("#doc-author").value });
      const out = await post("api/upload?" + q, f, true);
      if (out.error) return setMsg(m, out.error);
      setMsg(m, `Stored as ${out.id} with ${out.n_passages} passages. Reloading…`, true); setTimeout(() => location.reload(), 700);
    };
    $("#ph-add").onclick = async () => {
      const f = $("#ph-file").files[0], m = $("#ph-msg"); if (!f) return setMsg(m, "Choose a file first.");
      const out = await post("api/upload?" + new URLSearchParams({ kind: "photo", name: f.name, caption: $("#ph-cap").value }), f, true);
      if (out.error) return setMsg(m, out.error);
      setMsg(m, "Photograph stored. Reloading…", true); setTimeout(() => location.reload(), 700);
    };
    $("#rebuild").onclick = async () => { await post("api/rebuild"); location.reload(); };
    const rx = $("#run-extract");
    if (rx) rx.onclick = async () => {
      const m = $("#extract-msg"); m.textContent = "Running…"; m.className = "msg";
      const out = await post("api/extract");
      if (out.error) return setMsg(m, "Extraction could not run: " + out.error);
      setMsg(m, "Done. Reloading…", true); setTimeout(() => location.reload(), 700);
    };
  }

  // ---------- case file ----------
  let fileSection = "overview", fileFilter = "";
  const ofType = (...t) => B.entities.filter((e) => t.includes(e.type)).sort((a, b) => b.n_claims - a.n_claims);
  const span = (e) => { const cl = (D.claimsOf.get(e.id) || []).filter((c) => c.time && c.t1 - c.t0 < 400 * DAY); return cl.length ? [Math.min(...cl.map((c) => c.t0)), Math.max(...cl.map((c) => c.t1))] : null; };
  const SECTIONS = [
    ["overview", "Overview", () => ""], ["people", "People", () => ofType("PERSON").length], ["groups", "Agencies and groups", () => ofType("GROUP").length],
    ["places", "Places", () => ofType("LOCATION").length], ["objects", "Objects and weapons", () => ofType("OBJECT", "WEAPON").length],
    ["vehicles", "Vehicles", () => ofType("VEHICLE").length], ["events", "Events", () => B.events.length], ["documents", "Documents and sources", () => B.evidence.length],
    ["photos", "Photographs", () => B.photos.length], ["scenes", "3D scenes", () => D.SCENES.length], ["reviewlog", "Review record", () => B.claims.filter((c) => c.review).length],
  ];
  function entityTable(list) {
    return `<input class="ffilter" placeholder="Filter by name…" value="${esc(fileFilter)}">
      <table class="t"><tr><th>Name</th><th>Type</th><th>Claims</th><th>First mentioned</th><th>Last mentioned</th><th>Described as</th><th>In 3D scene</th></tr>
      ${list.filter((e) => !fileFilter || [e.name, ...e.aliases].join(" ").toLowerCase().includes(fileFilter.toLowerCase())).slice(0, 400).map((e) => {
        const sp = span(e), at = (D.claimsOf.get(e.id) || []).filter((c) => c.s === e.id && !c.o).slice(0, 3).map((c) => c.literal);
        return `<tr class="click" data-ent="${e.id}"><td><b>${esc(e.name)}</b> ${e.demo ? demoTag : ""}${e.type === "PERSON" ? ` <a data-dossier="${e.id}" style="cursor:pointer;font-size:11px">dossier</a>` : ""}${e.aliases.length ? `<div class="meta">also: ${e.aliases.slice(0, 4).map(esc).join(", ")}</div>` : ""}</td><td>${D.typeTag(e.type)}</td><td>${e.n_claims}</td><td>${sp ? D.fmtDay(sp[0]) : "–"}</td><td>${sp ? D.fmtDay(sp[1]) : "–"}</td><td class="meta">${at.map(esc).join(" · ")}</td><td>${D.anchorOf(e) ? "pinned" : D.sceneOf(e) ? "scene" : ""}</td></tr>`;
      }).join("")}</table>`;
  }
  function fileBody() {
    const s = fileSection;
    if (s === "overview") {
      const facts = B.passages.filter((p) => p.section.startsWith("Case Files") && p.text.includes(":")).slice(0, 8);
      const key = ofType("PERSON").slice(0, 9);
      return `<h1>${esc(B.case.title)}</h1><table class="t" style="max-width:820px">${facts.map((p) => { const i = p.text.indexOf(":"); return `<tr><td class="meta" style="width:230px">${esc(p.text.slice(0, i))}</td><td>${esc(p.text.slice(i + 1))}</td></tr>`; }).join("")}</table>
        <h2>Key people</h2><div class="people">${key.map((e) => `<div class="person" data-ent="${e.id}">${e.photos[0] ? `<img src="case/photos/${encodeURIComponent(e.photos[0])}">` : '<div class="ph">?</div>'}<div><b>${esc(e.name)}</b><div class="meta">${e.n_claims} claims${e.photos.length ? " · " + e.photos.length + " photos" : ""}</div><div class="meta">${(D.claimsOf.get(e.id) || []).filter((c) => c.s === e.id && !c.o).slice(0, 2).map((c) => esc(c.literal)).join(" · ")}</div></div></div>`).join("")}</div>
        <h2>The incident</h2><table class="t">${B.events.filter((v) => v.kind === "action_point" || v.kind === "discovery").map((v) => `<tr class="click" data-event="${v.id}"><td style="width:150px">${v.time ? fmt(v.time.start) : "undated"}</td><td><span class="kind" style="background:${D.css("--k-" + v.kind)}"></span><b>${esc(v.title)}</b> ${v.demo ? demoTag : ""}<div class="meta">${esc(v.summary || "")}</div></td><td>${v.claims.length} claims</td></tr>`).join("")}</table>`;
    }
    if (s === "people") return "<h1>People</h1>" + entityTable(ofType("PERSON"));
    if (s === "groups") return "<h1>Agencies and groups</h1>" + entityTable(ofType("GROUP"));
    if (s === "places") return "<h1>Places</h1>" + entityTable(ofType("LOCATION"));
    if (s === "objects") return "<h1>Objects and weapons</h1>" + entityTable(ofType("WEAPON", "OBJECT").sort((a, b) => (b.type === "WEAPON") - (a.type === "WEAPON") || b.n_claims - a.n_claims));
    if (s === "vehicles") return "<h1>Vehicles</h1>" + entityTable(ofType("VEHICLE"));
    if (s === "events") return `<h1>Events</h1><table class="t"><tr><th>When</th><th>Event</th><th>Kind</th><th>Claims</th></tr>${B.events.map((v) => `<tr class="click" data-event="${v.id}"><td style="white-space:nowrap">${v.time ? fmt(v.time.start) + (v.t1 - v.t0 > 1.5 * DAY ? " – " + fmt(v.time.end) : "") : "undated"}</td><td><b>${esc(v.title)}</b> ${v.demo ? demoTag : ""}<div class="meta">${esc(v.summary || "")}</div></td><td><span class="kind" style="background:${D.css("--k-" + v.kind)}"></span>${v.kind.replace("_", " ")}</td><td>${v.claims.length}</td></tr>`).join("")}</table>`;
    if (s === "documents") {
      const n = (id) => B.passages.filter((p) => (p.evidence || []).includes(id)), cl = (id) => n(id).reduce((a, p) => a + (p.n_claims || 0), 0);
      return `<h1>Documents and sources</h1><div class="lead">Every item the case rests on. Originals are kept unmodified; the hash proves it. Add official documents on the Intake page.</div>
        <table class="t" style="margin-top:12px"><tr><th>ID</th><th>Item</th><th>Kind</th><th>Passages citing it</th><th>Claims</th><th>SHA-256</th><th></th></tr>${B.evidence.map((e) => {
          const href = e.path ? "case/" + e.path : /^https?:/.test(e.url || "") ? e.url : null;
          return `<tr><td>${e.id}</td><td><b>${esc(e.title)}</b>${e.id === "DEMO" ? " " + demoTag : ""}${e.doc_type ? `<div class="meta">${esc(e.doc_type.replace(/_/g, " "))} · ${esc(e.author || "")} · ${esc(e.date || "")}</div>` : ""}${e.state ? ` <span class="pill ${e.state === "in graph" ? "done" : "wait"}">${e.state}</span>` : ""}</td><td>${esc(e.kind)}</td><td>${n(e.id).length}</td><td>${cl(e.id)}</td><td class="mono">${e.sha256 ? e.sha256.slice(0, 16) + "…" : "–"}</td><td>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">open</a>` : ""}${e.text_path ? ` · <a href="case/${esc(e.text_path)}" target="_blank">OCR</a>` : ""}</td></tr>`;
        }).join("")}</table>`;
    }
    if (s === "photos") return `<h1>Photographs</h1><div class="photos" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr));padding:10px 0">${B.photos.map((p) => `<div class="photo" data-photo="${esc(p.file)}"><img loading="lazy" src="case/photos/${encodeURIComponent(p.file)}" style="height:150px"><div class="c">${esc(p.caption)}<div class="d">${p.date || "undated"}${p.entities.length ? " · " + p.entities.map((id) => esc(D.E.get(id).name)).join(", ") : ""}</div></div></div>`).join("")}</div>`;
    if (s === "scenes") return `<h1>3D scenes</h1><table class="t"><tr><th>Scene</th><th>Stands for</th><th>Pipeline</th><th>Splat</th><th>Pins</th><th></th></tr>${D.SCENES.map((sc) => `<tr><td><b>${esc(sc.title)}</b><div class="meta">${esc(sc.note)}</div></td><td>${esc(sc.location)}</td><td>${esc(sc.pipeline || "")}</td><td>${kb(sc.splat_bytes)}<div class="mono meta">${sc.splat_sha256.slice(0, 16)}…</div></td><td>${sc.anchors.length}</td><td><a data-scene="${esc(sc.id)}" style="cursor:pointer">open</a></td></tr>`).join("")}</table>`;
    if (s === "reviewlog") {
      const dec = B.claims.filter((c) => c.review).sort((a, b) => b.review.at.localeCompare(a.review.at));
      return `<h1>Review record</h1><div class="lead">Every human decision on a claim. ${pendingN()} claims are still waiting.</div><table class="t" style="margin-top:12px"><tr><th>When</th><th>Decision</th><th>Reviewer</th><th>Claim</th><th>Confidence</th><th>Note</th></tr>${dec.map((c) => `<tr class="click" data-claim="${c.id}"><td>${esc(c.review.at)}</td><td><span class="st ${c.review.decision}">${c.review.decision}</span></td><td>${esc(c.review.reviewer || "–")}</td><td>${esc(D.E.get(c.s).name)} — ${esc(c.p.toLowerCase().replace(/_/g, " "))} → ${esc(c.o ? D.E.get(c.o).name : c.literal)}<div class="meta">“${esc(c.quote)}”</div></td><td>${c.conf.toFixed(2)}</td><td>${esc(c.review.note || "")}</td></tr>`).join("") || '<tr><td colspan="6" class="meta">No decisions recorded yet.</td></tr>'}</table>`;
    }
    return "";
  }
  function renderFile() {
    $("#page-file").innerHTML = `<div id="file-nav"><div class="panel-title">Case file</div>${SECTIONS.map(([id, label, n]) => `<div class="row${id === fileSection ? " on" : ""}" data-sec="${id}">${label}<b>${n()}</b></div>`).join("")}</div><div id="file-main"><div class="wrap">${fileBody()}</div></div>`;
    $("#page-file").onclick = (e) => {
      const q = (a) => e.target.closest(`[data-${a}]`)?.dataset[a];
      if (q("dossier")) return window.__openDossier(q("dossier"));
      if (e.target.tagName === "A" && !q("scene")) return;
      if (q("sec")) { fileSection = q("sec"); fileFilter = ""; return renderFile(); }
      if (q("ent")) return openEntity(q("ent"));
      if (q("event")) return openEvent(q("event"));
      if (q("scene")) return nav("image");
      if (q("claim")) { nav("investigate"); return D.select({ type: "claim", id: q("claim") }); }
      if (q("photo")) { nav("investigate"); document.querySelector(".tabs [data-tab=photos]").click(); return D.select({ type: "photo", id: q("photo") }); }
    };
    const f = $("#page-file .ffilter");
    if (f) f.oninput = () => { fileFilter = f.value; const pos = f.selectionStart; renderFile(); const g = $("#page-file .ffilter"); g.focus(); g.setSelectionRange(pos, pos); };
  }

  // ---------- scene from photos (image pipeline) ----------
  async function renderImage() {
    const sc = D.SCENES.find((x) => (x.pipeline || "").startsWith("image")), page = $("#page-image");
    if (!sc) { page.innerHTML = '<div class="wrap"><h1>Scene from photos</h1><div class="lead">No scene is attached to this case yet. Attach a splat with <span class="mono">python -m crimetext scene</span>.</div></div>'; return; }
    if (!$("#img-side")) page.innerHTML = '<div id="img-side"></div><div id="scene-host-b" class="scene-host"></div>';
    $("#scene-host-b").appendChild($("#scene"));
    if (!window.SceneView) await import("./scene.js");
    window.SceneView.open(sc, D.sceneHooks).then(() => window.SceneView.setActive(new Set(B.entities.map((e) => e.id)), null));
    const st = await (await fetch("api/image_pipeline?scene=" + encodeURIComponent(sc.id))).json();
    $("#img-side").innerHTML = `<h1 style="font-size:18px;margin:0">${esc(sc.title)}</h1>
      <div class="banner">${esc(sc.note)} ${demoTag}</div>
      <div class="kv">Stands for <b>${esc(sc.location)}</b></div><div class="kv">Splat <b>${kb(sc.splat_bytes)}</b> · <span class="mono">sha256 ${sc.splat_sha256.slice(0, 16)}…</span></div>
      <div class="kv">Units <b>${esc(sc.units)}</b>: no scale bar was used, so no distances.</div><div class="kv">Pins <b>${sc.anchors.length}</b> · viewpoints <b>${sc.label_data?.summary?.registered_images ?? "?"}</b> of ${sc.label_data?.summary?.total_images ?? "?"} photos registered</div>
      <div class="btns"><button id="img-investigate">Open in investigation</button></div>

      <h3>Find in scene (SAM + CLIP)</h3>
      <div class="meta">${sc.live_query ? "Live CLIP matching is on for this scene." : "This scene carries the pipeline's stored results. Free-text CLIP matching needs the pipeline's region index (region_lookup.json), which is produced when the pipeline runs on the photos."}</div>
      <table class="t" style="margin-top:6px"><tr><th>Query</th><th>Sim.</th><th>SIFT</th><th>Checked</th></tr>${(sc.queries || []).map((q) => `<tr class="click" data-query="${esc(q.query)}"><td>${esc(q.query)}</td><td>${q.similarity.toFixed(3)}</td><td>${q.sift_support}</td><td><span class="pill ${q.ok ? "done" : "wait"}">${q.ok ? "plausible" : esc(q.verdict.split("—")[0].trim())}</span></td></tr>`).join("")}</table>

      <h3>Source photographs (${st.photos.length})</h3>
      <div class="meta">Add overlapping walk-around photographs of the room. The pipeline needs at least ${st.min_photos}; isolated close-ups do not register.</div>
      <div class="drop" id="sp-drop" style="margin-top:8px"><b>Drop files here or click to choose</b></div><input type="file" id="sp-file" accept="image/*" multiple hidden>
      <div class="btns"><button id="sp-add">Add photographs</button></div><div class="msg" id="sp-msg"></div>

      <h3>Build the splat from the photographs</h3>
      ${st.requirements.map((r) => `<div class="req ${r.ok ? "ok" : "no"}"><i>${r.ok ? "✓" : "✕"}</i><div>${esc(r.name)}<div class="d">${esc(r.detail)}${r.warn ? " · " + esc(r.warn) : ""}</div></div></div>`).join("")}
      <ol class="why" style="margin-top:8px">${st.stages.map((x) => `<li>${esc(x.name)} <span class="mono">${esc(x.tool)}</span></li>`).join("")}</ol>
      <div class="btns"><button id="pipe-run" ${st.ready && !st.running ? "" : "disabled"}>${st.running ? "Running…" : "Run image pipeline"}</button></div>
      <div class="msg ${st.ready ? "" : "err"}" id="pipe-msg">${st.ready ? "" : "Cannot run on this machine yet: " + [...st.requirements.filter((r) => !r.ok).map((r) => r.name), ...(st.photos.length < st.min_photos ? [`${st.min_photos - st.photos.length} more photographs`] : [])].join("; ") + "."}</div>
      <div class="meta mono" style="margin-top:6px">${esc(st.command)}</div>
      ${st.log_tail ? `<pre class="log">${esc(st.log_tail)}</pre>` : ""}`;
    dropzone($("#sp-drop"), $("#sp-file"));
    $("#img-side").onclick = (e) => { const q = e.target.closest("[data-query]")?.dataset.query; if (q) window.SceneView.query(q); };
    $("#img-investigate").onclick = () => { nav("investigate"); D.openScene(sc.id); };
    $("#sp-add").onclick = async () => {
      const files = [...$("#sp-file").files], m = $("#sp-msg"); if (!files.length) return setMsg(m, "Choose photographs first.");
      for (const [i, f] of files.entries()) { m.textContent = `Storing ${i + 1} of ${files.length}…`; const out = await post("api/upload?" + new URLSearchParams({ kind: "scene_photo", scene: sc.id, name: f.name }), f, true); if (out.error) return setMsg(m, out.error); }
      setMsg(m, "Stored. Reloading…", true); setTimeout(() => location.reload(), 600);
    };
    $("#pipe-run").onclick = async () => { const out = await post("api/image_pipeline/run", { scene: sc.id }); if (out.error) return setMsg($("#pipe-msg"), out.error); renderImage(); };
  }

  // ---------- scene from video (crimesplat-video connector) ----------
  let videoTimer = null;
  async function renderVideo() {
    clearTimeout(videoTimer);
    const v = await (await fetch("api/video")).json();
    const vs = D.SCENES.filter((x) => (x.pipeline || "").startsWith("video"));
    $("#page-video").innerHTML = `<div class="wrap"><h1>Scene from video</h1>
      <div class="lead">Body-camera, phone walk-through or drone footage of a place becomes a 3D scene of the case. The work is done by the video pipeline in <span class="mono">${esc(v.repo)}</span>; this page stores the footage, starts the pipeline on it and imports the result.</div>
      <h2>Video pipeline on this machine</h2>
      ${v.requirements.map((r) => `<div class="req ${r.ok ? "ok" : "no"}"><i>${r.ok ? "✓" : "✕"}</i><div>${esc(r.name)}<div class="d">${esc(r.detail)}</div></div></div>`).join("")}
      <h2>Add footage</h2><div class="cards"><div class="card"><div class="drop" id="vd-drop"><b>Drop files here or click to choose</b></div><input type="file" id="vd-file" accept="video/*" hidden>
        <p>Use the camera's original file. Slow movement, 1080p or better, some floor in view. A single fixed camera cannot be reconstructed.</p><div class="btns"><button id="vd-add">Store footage</button></div><div class="msg" id="vd-msg"></div></div>
        <div class="card"><h3>What the pipeline does</h3><ol class="why">${v.stages.map((x) => `<li>${esc(x)}</li>`).join("")}</ol><p>Compute profile for this machine: <b>${esc(v.profile)}</b>.</p></div></div>
      <h2>Footage on file (${v.files.length})</h2>
      ${v.files.length ? `<table class="t"><tr><th>File</th><th>Size</th><th>Footage type</th><th>Place it shows</th><th>State</th><th></th></tr>${v.files.map((f, i) => `<tr><td>${esc(f.file)}</td><td>${kb(f.bytes)}</td>
        <td>${f.scene || f.state === "running" ? esc(f.footage || "") : `<select data-ft="${i}">${v.footage_types.map((t) => `<option${t === (f.footage || "handheld") ? " selected" : ""}>${t}</option>`).join("")}</select>`}</td>
        <td>${f.scene || f.state === "running" ? esc(f.location || "") : `<input data-loc="${i}" placeholder="Kitchen of the Short residence" value="${esc(f.location || "")}" style="width:240px">`}</td>
        <td><span class="pill ${f.scene ? "done" : "wait"}">${esc(f.state)}</span></td>
        <td>${f.scene ? `<a data-open="${esc(f.scene)}" style="cursor:pointer">open scene</a>` : f.state === "running" ? "" : `<button data-run="${i}" ${v.ready ? "" : "disabled"}>${f.state === "failed" ? "Retry" : "Reconstruct"}</button>`}</td></tr>
        ${f.log_tail ? `<tr><td colspan="6"><pre class="log">${esc(f.log_tail)}</pre></td></tr>` : ""}`).join("")}</table>` : '<div class="lead">None yet.</div>'}
      <div class="msg" id="vr-msg"></div>
      <h2>Scenes from video in this case (${vs.length})</h2>
      ${vs.length ? `<table class="t"><tr><th>Scene</th><th>Shows</th><th>Units</th><th>Held-out PSNR</th><th>Pins</th><th></th></tr>${vs.map((sc) => `<tr><td><b>${esc(sc.title)}</b><div class="meta">${esc(sc.note)}</div></td><td>${esc(sc.location)}</td><td>${esc(sc.units)}</td><td>${sc.quality?.psnr_holdout ?? "–"}</td><td>${sc.anchors.length}</td><td><a data-open="${esc(sc.id)}" style="cursor:pointer">open</a></td></tr>`).join("")}</table>` : '<div class="lead">None yet.</div>'}</div>`;
    dropzone($("#vd-drop"), $("#vd-file"));
    $("#vd-add").onclick = async () => {
      const f = $("#vd-file").files[0], m = $("#vd-msg"); if (!f) return setMsg(m, "Choose a file first.");
      m.textContent = "Storing…"; const out = await post("api/upload?" + new URLSearchParams({ kind: "video", name: f.name }), f, true);
      if (out.error) return setMsg(m, out.error); renderVideo();
    };
    $("#page-video").onclick = async (e) => {
      const open = e.target.dataset.open, run = e.target.dataset.run;
      if (open) { if (!D.SCENES.some((x) => x.id === open)) return location.reload(); nav("investigate"); return D.openScene(open); }
      if (run == null) return;
      const f = v.files[+run];
      const out = await post("api/video/run", { file: f.file, footage: $(`[data-ft="${run}"]`).value, location: $(`[data-loc="${run}"]`).value });
      if (out.error) return setMsg($("#vr-msg"), out.error);
      renderVideo();
    };
    if (v.files.some((f) => f.state === "running") && $("#page-video").classList.contains("on")) videoTimer = setTimeout(renderVideo, 5000);
    if (v.files.some((f) => f.scene && !D.SCENES.some((x) => x.id === f.scene))) setMsg($("#vr-msg"), "A new scene was imported. Reload the page to load it into the workspace.", true);
  }

  window.addEventListener("hashchange", () => nav(location.hash.slice(1), true));
  nav((location.hash || "#home").slice(1), true);
});
