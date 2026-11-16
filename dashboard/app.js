/* Case Desk: a timeline-driven view of a case's temporal scene graph.
   One selection model: the playhead time, the display mode and the selected item drive every pane. */
(async function () {
  const B = await (await fetch("case/build/bundle.json")).json();
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const T = (iso) => new Date(iso).getTime();
  const DAY = 864e5;
  const KINDS = ["action_point", "discovery", "investigation", "legal", "media", "background"];
  const KIND_LABEL = { action_point: "Action", discovery: "Discovery", investigation: "Investigation", legal: "Legal", media: "Media", background: "Background" };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const color = (type) => css("--" + type) || "#999";
  const fmtDay = d3.timeFormat("%d %b %Y"), fmtMin = d3.timeFormat("%d %b %Y, %H:%M");

  // ---------- index the bundle ----------
  const E = new Map(B.entities.map((e) => [e.id, e]));
  const C = new Map(B.claims.map((c) => [c.id, c]));
  const P = new Map(B.passages.map((p) => [p.id, p]));
  const V = new Map(B.events.map((v) => [v.id, v]));
  const EV = new Map(B.evidence.map((e) => [e.id, e]));
  B.claims.forEach((c) => { if (c.time) { c.t0 = T(c.time.start); c.t1 = T(c.time.end); } });
  B.events.forEach((v) => { if (v.time) { v.t0 = T(v.time.start); v.t1 = T(v.time.end); } });
  const TIMED = B.events.filter((v) => v.time), UNDATED = B.events.filter((v) => !v.time);
  const claimsOf = new Map();
  B.claims.forEach((c) => [c.s, c.o, c.by].forEach((id) => { if (id) (claimsOf.get(id) || claimsOf.set(id, []).get(id)).push(c); }));
  const passageClaims = new Map();
  B.claims.forEach((c) => (passageClaims.get(c.pid) || passageClaims.set(c.pid, []).get(c.pid)).push(c));
  const full = [d3.min(TIMED, (v) => v.t0) - 200 * DAY, d3.max(TIMED, (v) => v.t1) + 200 * DAY];
  const incident = (B.case.incident_window || []).length === 2
    ? [T(B.case.incident_window[0]) - 3 * DAY, T(B.case.incident_window[1]) + 3 * DAY] : full;

  // ---- human review: a claim is rejected, accepted, pending (below threshold) or auto (above it)
  let THRESH = B.review?.threshold ?? 0.7;
  const status = (c) => c.demo ? "demo" : c.review?.decision || (c.conf < THRESH ? "pending" : "auto");
  const confColor = (v) => d3.interpolateRgbBasis(["#f0625a", "#f0a63a", "#62c58c"])(Math.max(0, Math.min(1, (v - 0.2) / 0.7)));
  const normName = (s) => String(s).toLowerCase().replace(/[\u2018\u2019]/g, "'").trim();
  const byName = new Map(); B.entities.forEach((e) => [e.name, ...e.aliases].forEach((n) => byName.has(normName(n)) || byName.set(normName(n), e)));
  const SCENES = B.scenes || [];
  const sceneOf = (e) => SCENES.find((sc) => byName.get(normName(sc.location))?.id === e.id);
  const anchorOf = (e) => { for (const sc of SCENES) { const a = (sc.anchors || []).find((x) => byName.get(normName(x.entity))?.id === e.id); if (a) return { sc, a }; } return null; };

  const S = {
    t: T((B.case.incident_window || [TIMED[0].time.start.slice(0, 10)])[0] + "T12:00"),
    view: incident.slice(), mode: "event", sel: null, focus: null, pin: null,
    hiddenTypes: new Set(), solo: null, playing: null, confirmedOnly: false, hideDemo: false, view3d: false, rvFilter: "pending",
  };

  $("#case-title").textContent = B.case.title;
  $("#stats").textContent = `${B.stats.claims} grounded claims · ${B.stats.entities} entities · ${B.stats.events} events · ${B.stats.passages_with_claims}/${B.stats.passages} passages · ${B.stats.photos} photos${SCENES.length ? " · " + SCENES.length + " 3D scene" : ""}`;
  document.title = "Case Desk · " + B.case.title;

  // ---------- what is on stage ----------
  function activeEvents(t = S.t) {
    if (S.pin) return [V.get(S.pin)];
    const hit = TIMED.filter((v) => v.t0 <= t && t <= v.t1);
    if (!hit.length) return [];
    const min = d3.min(hit, (v) => v.t1 - v.t0);
    return hit.filter((v) => v.t1 - v.t0 <= Math.max(min * 3, 2 * DAY));
  }
  function stageClaims() {      // rejected claims never reach the stage; unreviewed ones can be hidden
    return rawStageClaims().filter((c) => { const st = status(c); return st !== "rejected" && !(S.confirmedOnly && st === "pending") && !(S.hideDemo && st === "demo"); });
  }
  function rawStageClaims() {
    if (S.mode === "focus" && S.focus) return claimsOf.get(S.focus) || [];
    if (S.mode === "cumulative") return B.claims.filter((c) => c.time && c.t0 <= S.t);
    const ids = new Set();
    activeEvents().filter((v) => !S.solo || S.solo === "all" || v.id === S.solo).forEach((v) => v.claims.forEach((id) => ids.add(id)));
    return [...ids].map((id) => C.get(id));
  }
  const certRank = { stated: 0, reported: 1, alleged: 2, speculated: 3 };
  const predLabel = (c) => (c.p === "OTHER" && c.p_text ? c.p_text : c.p.replace(/_/g, " ").toLowerCase());

  // ---------- scene graph ----------
  const svg = d3.select("#graph"), root = svg.append("g");
  svg.append("defs").append("marker").attr("id", "arrow").attr("viewBox", "0 -5 10 10").attr("refX", 10).attr("markerWidth", 7)
    .attr("markerHeight", 7).attr("orient", "auto").append("path").attr("d", "M0,-4L10,0L0,4").attr("fill", "#8d96a5");
  const gEdges = root.append("g"), gNodes = root.append("g");
  const zoom = d3.zoom().scaleExtent([0.15, 4]).on("zoom", (ev) => { root.attr("transform", ev.transform); if (ev.sourceEvent) userZoomed = true; });
  svg.call(zoom).on("dblclick.zoom", null);
  const pos = new Map();
  const sim = d3.forceSimulation().force("charge", d3.forceManyBody().strength(-520).distanceMax(520))
    .force("link", d3.forceLink().id((d) => d.id).distance((l) => 120 + 8 * Math.min(l.claims.length, 5)).strength(0.5))
    .force("collide", d3.forceCollide((d) => d.r + 26)).on("tick", tick).on("end", () => fit(true));
  let userZoomed = false;
  function fit(animate) {
    if (!NODES.length || userZoomed) return;
    const { width, height } = svg.node().getBoundingClientRect();
    if (!width || !height) return;                 // page hidden
    const x0 = d3.min(NODES, (d) => d.x) - 70, x1 = d3.max(NODES, (d) => d.x) + 70, y0 = d3.min(NODES, (d) => d.y) - 40, y1 = d3.max(NODES, (d) => d.y) + 60;
    const k = Math.min(1.4, 0.95 * Math.min(width / (x1 - x0), height / (y1 - y0)));
    const tr = d3.zoomIdentity.translate(width / 2 - k * (x0 + x1) / 2, height / 2 - k * (y0 + y1) / 2).scale(k);
    (animate ? svg.transition().duration(350) : svg).call(zoom.transform, tr);
  }
  let gNode = gNodes.selectAll("g"), gEdge = gEdges.selectAll("g"), NODES = [], LINKS = [];

  function buildGraph() {
    let claims = stageClaims();
    const types = new Set();
    claims.forEach((c) => { types.add(E.get(c.s).type); if (c.o) types.add(E.get(c.o).type); });
    claims = claims.filter((c) => !S.hiddenTypes.has(E.get(c.s).type) && !(c.o && S.hiddenTypes.has(E.get(c.o).type)));
    let note = "";
    if (S.mode === "cumulative") {                       // keep the graph readable: most-connected entities only
      const deg = d3.rollup(claims.flatMap((c) => [c.s, c.o].filter(Boolean)), (v) => v.length, (d) => d);
      const keep = new Set([...deg].sort((a, b) => b[1] - a[1]).slice(0, 70).map((d) => d[0]));
      if (deg.size > keep.size) note = `showing the 70 most connected of ${deg.size} entities`;
      claims = claims.filter((c) => keep.has(c.s) && (!c.o || keep.has(c.o)));
    }
    const nodes = new Map(), links = new Map();
    const node = (id) => nodes.get(id) || nodes.set(id, { id, e: E.get(id), attrs: [], deg: 0 }).get(id);
    for (const c of claims) {
      const s = node(c.s);
      if (!c.o) { s.attrs.push(c); continue; }
      const o = node(c.o); s.deg++; o.deg++;
      const k = c.s + ">" + c.o;
      (links.get(k) || links.set(k, { id: k, source: c.s, target: c.o, claims: [] }).get(k)).claims.push(c);
    }
    let { width, height } = svg.node().getBoundingClientRect();
    if (!width) { width = 900; height = 500; }
    NODES = [...nodes.values()].map((n) => {
      const p = pos.get(n.id) || { x: width / 2 + (Math.random() - 0.5) * 260, y: height / 2 + (Math.random() - 0.5) * 200 };
      pos.set(n.id, p);
      return Object.assign(p, n, { r: 9 + Math.min(12, Math.sqrt(n.deg + n.attrs.length) * 3) });
    });
    LINKS = [...links.values()].map((l) => {
      const preds = [...new Set(l.claims.map(predLabel))];
      return Object.assign(l, {
        label: preds.slice(0, 2).join(" · ") + (preds.length > 2 ? ` +${preds.length - 2}` : ""),
        cert: l.claims.map((c) => c.certainty).sort((a, b) => certRank[b] - certRank[a])[0],
        curved: links.has(l.target + ">" + l.source),
      });
    });

    gEdge = gEdges.selectAll("g.edge").data(LINKS, (d) => d.id).join((en) => {
      const g = en.append("g");
      g.append("path").attr("marker-end", "url(#arrow)");
      g.append("text").attr("dy", -3);
      g.on("click", (ev, d) => { ev.stopPropagation(); select({ type: "edge", id: d.id }); });
      return g;
    }).attr("class", (d) => "edge " + d.cert + (d.claims.some((c) => status(c) === "pending") ? " pending" : "") + (d.claims.every((c) => c.demo) ? " demo" : ""));
    gEdge.select("text").text((d) => d.label);

    gNode = gNodes.selectAll("g.node").data(NODES, (d) => d.id).join((en) => {
      const g = en.append("g").attr("class", (d) => "node" + (d.e.demo ? " demo" : ""));
      g.append("g").attr("class", "shape-wrap");
      g.append("text").attr("class", "name").attr("text-anchor", "middle");
      g.append("text").attr("class", "attr").attr("text-anchor", "middle");
      g.call(d3.drag().on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
        .on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = d.fy = null; }));
      g.on("click", (ev, d) => { ev.stopPropagation(); select({ type: "entity", id: d.id }); })
        .on("dblclick", (ev, d) => { ev.stopPropagation(); focusEntity(d.id); });
      return g;
    });
    gNode.each(function (d) {                       // things are circles, stuff (places) are rounded squares
      const w = d3.select(this).select(".shape-wrap"); w.selectAll("*").remove();
      (d.e.kind === "stuff"
        ? w.append("rect").attr("x", -d.r).attr("y", -d.r).attr("width", 2 * d.r).attr("height", 2 * d.r).attr("rx", 4)
        : w.append("circle").attr("r", d.r)).attr("class", "shape").attr("fill", color(d.e.type));
      const g = d3.select(this);
      g.select(".name").attr("y", d.r + 13).text(d.e.name.length > 30 ? d.e.name.slice(0, 29) + "…" : d.e.name);
      const a = [...new Set(d.attrs.map((c) => c.literal))];
      const line = a.slice(0, 2).map((x) => (x.length > 26 ? x.slice(0, 25) + "…" : x)).join(" · ") + (a.length > 2 ? ` +${a.length - 2}` : "");
      g.select(".attr").attr("y", d.r + 25).text(sceneOf(d.e) ? "▣ 3D scene attached" + (line ? " · " + line : "") : line);
    });
    sim.nodes(NODES); sim.force("link").links(LINKS);
    sim.force("x", d3.forceX(width / 2).strength(0.05)).force("y", d3.forceY(height / 2).strength(0.07));
    userZoomed = false; sim.alpha(0.6).alphaDecay(0.045).restart();
    clearTimeout(buildGraph.t); buildGraph.t = setTimeout(() => fit(true), 500);

    const empty = $("#empty");
    empty.classList.toggle("hidden", NODES.length > 0 || S.view3d);
    if (!NODES.length) {
      const nx = TIMED.find((v) => v.t0 > S.t), pv = [...TIMED].reverse().find((v) => v.t1 < S.t);
      empty.innerHTML = S.mode === "focus" ? "Select an entity to see every claim about it." :
        `No event is recorded at this time.<br><span class="meta">${pv ? "Previous: " + esc(pv.title) + " (" + fmtDay(pv.t0) + ")" : ""}${pv && nx ? " · " : ""}${nx ? "Next: " + esc(nx.title) + " (" + fmtDay(nx.t0) + ")" : ""}</span>`;
    }
    // type filter chips
    const f = d3.select("#filters"); f.selectAll("*").remove();
    f.append("span").attr("class", "lbl").text("Show");
    [...types].sort().forEach((t) => f.append("span").attr("class", "chip" + (S.hiddenTypes.has(t) ? " off" : ""))
      .html(`<span class="kind" style="background:${color(t)}"></span>${t.toLowerCase()}`)
      .on("click", () => { S.hiddenTypes.has(t) ? S.hiddenTypes.delete(t) : S.hiddenTypes.add(t); buildGraph(); }));
    if (B.stats.demo_claims) f.append("span").attr("class", "chip" + (S.hideDemo ? " on" : "")).attr("title", "Hand-written links between the 3D scene and the case. Not from the case file.")
      .text("hide demo links").on("click", () => { S.hideDemo = !S.hideDemo; buildGraph(); });
    f.append("span").attr("class", "chip" + (S.confirmedOnly ? " on" : "")).attr("title", "Hide claims that are below the confidence threshold and not yet accepted by a person")
      .text("reviewed or confident only").on("click", () => { S.confirmedOnly = !S.confirmedOnly; buildGraph(); });
    window.SceneView?.ready && window.SceneView.setActive(new Set(NODES.map((n) => n.id)), S.sel?.type === "entity" ? S.sel.id : null);
    f.append("span").attr("class", "meta").style("margin-left", "8px")
      .text(`${NODES.length} entities · ${claims.length} claims${note ? " · " + note : ""}`);
    paintSelection();
  }
  function tick() {
    gNode.attr("transform", (d) => `translate(${d.x},${d.y})`);
    gEdge.each(function (d) {
      const s = d.source, t = d.target, dx = t.x - s.x, dy = t.y - s.y, L = Math.hypot(dx, dy) || 1;
      const ux = dx / L, uy = dy / L, x1 = s.x + ux * (s.r + 2), y1 = s.y + uy * (s.r + 2), x2 = t.x - ux * (t.r + 4), y2 = t.y - uy * (t.r + 4);
      const b = d.curved ? 22 : 0, mx = (x1 + x2) / 2 - uy * b, my = (y1 + y2) / 2 + ux * b;
      const g = d3.select(this);
      g.select("path").attr("d", `M${x1},${y1}Q${mx},${my} ${x2},${y2}`);
      g.select("text").attr("x", (x1 + x2) / 2 - uy * b * 0.5).attr("y", (y1 + y2) / 2 + ux * b * 0.5);
    });
  }
  svg.on("click", () => select(null));
  function paintSelection() {
    const sel = S.sel; let nset = null, eset = null;
    if (sel?.type === "entity") { nset = new Set([sel.id]); eset = new Set(); LINKS.forEach((l) => { if (l.source.id === sel.id || l.target.id === sel.id) { eset.add(l.id); nset.add(l.source.id); nset.add(l.target.id); } }); }
    if (sel?.type === "edge") { const l = LINKS.find((x) => x.id === sel.id); if (l) { eset = new Set([l.id]); nset = new Set([l.source.id, l.target.id]); } }
    if (sel?.type === "claim") { const c = C.get(sel.id); nset = new Set([c.s, c.o].filter(Boolean)); eset = new Set([c.s + ">" + c.o]); }
    gNode.classed("dim", (d) => nset && !nset.has(d.id)).classed("sel", (d) => sel?.type === "entity" && d.id === sel.id);
    gEdge.classed("dim", (d) => eset && !eset.has(d.id)).classed("sel", (d) => eset?.has(d.id) && sel?.type !== "entity");
  }

  // ---------- inspector ----------
  const entLink = (id) => `<a data-ent="${id}">${esc(E.get(id).name)}</a>`;
  const typeTag = (t) => `<span class="tag" style="background:${color(t)}">${esc(t.toLowerCase())}</span>`;
  const whenText = (c) => !c.time ? "undated" : (c.time.precision === "minute" ? fmtMin(c.t0) : c.t1 - c.t0 < 1.5 * DAY ? fmtDay(c.t0) : `${fmtDay(c.t0)} – ${fmtDay(c.t1)}`);
  function claimCard(c, on) {
    const st = status(c);
    return `<div class="claim${on ? " on" : ""} ${st}" data-claim="${c.id}">
      <div class="triple">${entLink(c.s)} <span class="p">— ${esc(predLabel(c))} →</span> ${c.o ? entLink(c.o) : esc(c.literal)}</div>
      <div class="quote">“${esc(c.quote)}”</div>
      <div class="meta"><span class="conf" style="background:${confColor(c.conf)}" title="confidence">${c.conf.toFixed(2)}</span> <span class="st ${st}">${st === "auto" ? "not reviewed" : st === "demo" ? "for demo purposes" : st}</span> <span class="cert ${c.certainty}">${c.certainty}</span> ${esc(whenText(c))}${c.by ? ` · according to <b>${esc(E.get(c.by).name)}</b>` : ""} · ${c.pid}</div></div>`;
  }
  function markQuotes(text, quotes) {
    const n1 = (s) => s.toLowerCase().replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[–—]/g, "-").replace(/ /g, " ");
    const low = n1(text), spans = [];
    quotes.forEach((q) => { const i = low.indexOf(n1(q).replace(/\s+/g, " ").trim()); if (i >= 0) spans.push([i, i + q.trim().length]); });
    spans.sort((a, b) => a[0] - b[0]);
    let out = "", at = 0;
    for (const [a, b] of spans) { if (a < at) continue; out += esc(text.slice(at, a)) + "<mark>" + esc(text.slice(a, b)) + "</mark>"; at = b; }
    return out + esc(text.slice(at));
  }
  function sourceBlock(p, quotes) {
    const ev = (p.evidence || []).map((id) => EV.get(id)).filter(Boolean).map((e) => {
      const href = e.path ? "case/" + e.path : (/^https?:/.test(e.url || "") ? e.url : null);
      return `<div class="meta">${e.id} · ${esc(e.kind)} · ${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(e.title)}</a>` : esc(e.title)}${e.text_path ? ` · <a href="case/${esc(e.text_path)}" target="_blank">OCR text</a>` : ""}${e.sha256 ? ` · <span class="mono">sha256 ${e.sha256.slice(0, 12)}…</span>` : ""}</div>`;
    }).join("");
    return `<div class="src"><div class="meta"><b>${p.id}</b> · ${esc(p.section)}${p.subsection ? " › " + esc(p.subsection) : ""}${p.date_heading ? " · " + esc(p.date_heading) : ""}</div>
      <div style="margin:6px 0">${markQuotes(p.text, quotes)}</div>${ev}</div>`;
  }
  const photoThumbs = (files) => files.length ? `<div class="thumbs">${files.map((f) => `<img src="case/photos/${encodeURIComponent(f)}" data-photo="${esc(f)}" title="${esc(B.photos.find((p) => p.file === f)?.caption || f)}">`).join("")}</div>` : "";
  const byTime = (a, b) => (a.t0 ?? Infinity) - (b.t0 ?? Infinity) || a.pid.localeCompare(b.pid);

  function renderInspector() {
    const el = $("#inspector"), sel = S.sel;
    if (!sel) {
      const act = activeEvents().filter((v) => !S.solo || S.solo === "all" || v.id === S.solo);
      el.innerHTML = act.length ? act.map(eventHtml).join("") :
        `<div class="meta">Drag the playhead to a moment in the case. Click a node, an arrow, a clip or a passage to see the claims behind it and the exact words they come from.<br><br>Solid arrows are plain statements. Dashed arrows are reported. Dotted arrows are alleged or speculated.</div>`;
    } else if (sel.type === "entity") {
      const e = E.get(sel.id), all = (claimsOf.get(e.id) || []).slice().sort(byTime), on = new Set(stageClaims().map((c) => c.id));
      const attrs = all.filter((c) => c.s === e.id && !c.o);
      const now = all.filter((c) => on.has(c.id) && c.o);
      el.innerHTML = `<h2>${esc(e.name)}</h2>${e.demo ? '<div class="banner">Created for demo purposes. This entity is not in the case file. It was added by hand to show how the 3D scene connects to the graph.</div>' : ""}<div>${typeTag(e.type)}<span class="meta">${e.kind === "stuff" ? "place / setting" : "tracked instance"} · ${all.length} claims</span></div>
        ${e.aliases.length ? `<div class="meta" style="margin-top:6px">Also called: ${e.aliases.map(esc).join(", ")}</div>` : ""}
        <div class="btns"><button data-focus="${e.id}">Show every claim about this entity</button>${sceneButtons(e)}</div>
        ${e.photos.length ? "<h3>Photos</h3>" + photoThumbs(e.photos) : ""}
        ${attrs.length ? `<h3>Described as (${attrs.length})</h3>` + attrs.map((c) => claimCard(c)).join("") : ""}
        ${now.length ? `<h3>On stage now (${now.length})</h3>` + now.map((c) => claimCard(c)).join("") : ""}
        <h3>All claims over time (${all.length})</h3>${all.slice(0, 200).map((c) => claimCard(c)).join("")}`;
    } else if (sel.type === "edge") {
      const [s, o] = sel.id.split(">"), on = new Set(stageClaims().map((c) => c.id));
      const cl = B.claims.filter((c) => c.s === s && c.o === o).sort(byTime);
      const now = cl.filter((c) => on.has(c.id)), rest = cl.filter((c) => !on.has(c.id));
      el.innerHTML = `<h2>${esc(E.get(s).name)} → ${esc(E.get(o).name)}</h2><div class="meta">${cl.length} claims link these two</div>
        <h3>On stage now (${now.length})</h3>${now.map((c) => claimCard(c)).join("")}
        ${rest.length ? `<h3>At other times (${rest.length})</h3>` + rest.map((c) => claimCard(c)).join("") : ""}`;
    } else if (sel.type === "claim") {
      const c = C.get(sel.id), p = P.get(c.pid);
      el.innerHTML = `<h3 style="margin-top:0">Claim ${c.id}</h3>${claimCard(c, true)}
        <div class="kv">Time: <b>${esc(whenText(c))}</b>${c.time ? ` (${esc(c.time.precision)}, from the ${c.time.from === "claim" ? "passage wording “" + esc(c.time.text) + "”" : "date heading"})` : ""}</div>
        <div class="kv">Wording: <b>${c.certainty}</b>${c.by ? ` · attributed to ${entLink(c.by)}` : " · no named source in the passage"}</div>
        <h3>Review</h3>${reviewBlock(c)}
        <h3>Where this comes from</h3>${sourceBlock(p, [c.quote])}
        <h3>Other claims from the same passage</h3>${(passageClaims.get(c.pid) || []).filter((x) => x.id !== c.id).map((x) => claimCard(x)).join("") || '<div class="meta">none</div>'}
        ${c.events.length ? "<h3>Part of</h3>" + c.events.map((id) => `<div class="row" data-event="${id}"><span class="kind" style="background:${css("--k-" + V.get(id).kind)}"></span>${esc(V.get(id).title)}</div>`).join("") : ""}`;
    } else if (sel.type === "event") {
      el.innerHTML = eventHtml(V.get(sel.id));
    } else if (sel.type === "passage") {
      const p = P.get(sel.id), cl = passageClaims.get(p.id) || [];
      el.innerHTML = `<h3 style="margin-top:0">Passage</h3>${sourceBlock(p, cl.map((c) => c.quote))}<h3>Claims extracted (${cl.length})</h3>${cl.map((c) => claimCard(c)).join("") || '<div class="meta">No claim was extracted from this passage.</div>'}`;
    } else if (sel.type === "photo") {
      const ph = B.photos.find((x) => x.file === sel.id);
      el.innerHTML = `<img src="case/photos/${encodeURIComponent(ph.file)}" data-photo="${esc(ph.file)}" style="width:100%;cursor:zoom-in;border:1px solid var(--line)">
        <h2 style="margin-top:8px">${esc(ph.caption)}</h2><div class="meta">${ph.date ? "Dated " + fmtDay(T(ph.date + "T12:00")) + " (from file name)" : "No date in the file name"} · ${esc(ph.file)}</div>
        ${ph.date ? `<div style="margin-top:8px"><button data-goto="${T(ph.date + "T12:00")}">Go to this date</button></div>` : ""}
        <h3>Linked by caption</h3>${ph.entities.map((id) => `<div class="row" data-ent="${id}">${typeTag(E.get(id).type)}${esc(E.get(id).name)}</div>`).join("") || '<div class="meta">The caption names no known entity.</div>'}`;
    }
    el.scrollTop = 0;
  }
  const span = (v) => !v.time ? "undated section of the case file" : v.t1 - v.t0 < 1.5 * DAY ? fmtDay(v.t0) : fmtDay(v.t0) + " – " + fmtDay(v.t1);
  function sceneButtons(e) {
    if (!SCENES.length) return "";
    const sc = sceneOf(e), an = anchorOf(e);
    return (sc ? `<button data-scene="${esc(sc.id)}">Open 3D scene of this place</button>` : "") +
      (an ? `<button data-scene="${esc(an.sc.id)}" data-fly="${e.id}">Show pin in 3D scene</button><button data-unpin="${e.id}" data-scene2="${esc(an.sc.id)}">Remove pin</button>`
          : `<button data-pin="${e.id}">Pin in 3D scene…</button>`);
  }
  function reviewBlock(c) {
    const st = status(c), r = c.review;
    if (c.demo) return '<div class="banner">For demo purposes. This link was written by hand and does not come from the case file. It is not scored and cannot be reviewed.</div>';
    return `<div class="kv">Confidence <span class="conf" style="background:${confColor(c.conf)}">${c.conf.toFixed(2)}</span> · threshold ${THRESH.toFixed(2)} · <span class="st ${st}">${st === "auto" ? "above threshold, not reviewed" : st}</span></div>
      <ul class="why">${c.conf_why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
      ${r ? `<div class="meta">${esc(r.decision)} ${r.reviewer ? "by <b>" + esc(r.reviewer) + "</b> " : ""}on ${esc(r.at)}${r.note ? " · “" + esc(r.note) + "”" : ""}</div>` : ""}
      <input id="rv-note" placeholder="Note for the record (optional)" style="width:100%;margin-top:6px" value="${esc(r?.note || "")}">
      <div class="btns"><button class="ok" data-review="accepted" data-key="${c.id}">✓ Accept (A)</button><button class="no" data-review="rejected" data-key="${c.id}">✕ Reject (R)</button>${r ? `<button data-review="reset" data-key="${c.id}">Undo decision</button>` : ""}</div>`;
  }
  async function review(c, decision) {
    const note = document.querySelector("#rv-note")?.value || "";
    const res = await fetch("api/review", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: c.key, decision, note, reviewer: localStorage.getItem("reviewer") || "" }) });
    const out = await res.json(); if (out.error) return alert("Could not save: " + out.error);
    c.review = decision === "reset" ? null : out;
    const next = decision === "reset" ? null : queue().find((x) => x.id !== c.id && status(x) === "pending");
    buildReview(); lastKey = ""; setTime(S.t, true, false, true);
    select(next && S.rvFilter === "pending" ? { type: "claim", id: next.id } : { type: "claim", id: c.id });
  }
  const queue = () => B.claims.filter((c) => !c.demo && (S.rvFilter === "all" || status(c) === S.rvFilter)).sort((a, b) => a.conf - b.conf || a.id.localeCompare(b.id));
  function buildReview() {
    const n = (st) => B.claims.filter((c) => status(c) === st).length, q = queue();
    $("#review-n").textContent = n("pending") || "";
    $("#tab-review").innerHTML = `<div class="rv-bar">
        <select id="rv-filter">${["pending", "accepted", "rejected", "auto", "all"].map((f) => `<option value="${f}"${S.rvFilter === f ? " selected" : ""}>${f === "auto" ? "not reviewed, above threshold" : f} (${f === "all" ? B.claims.length : n(f)})</option>`).join("")}</select>
        <label class="meta">threshold <input id="rv-th" type="range" min="0.3" max="0.95" step="0.01" value="${THRESH}"> <b id="rv-thv">${THRESH.toFixed(2)}</b></label>
        <input id="rv-who" placeholder="Reviewer name" style="width:120px" value="${esc(localStorage.getItem("reviewer") || "")}">
        <div class="meta">Lowest confidence first. Open a claim to read its passage, then accept or reject. Rejected claims leave the graph; every decision is logged.</div></div>` +
      (q.slice(0, 250).map((c) => `<div class="rv-item${S.sel?.type === "claim" && S.sel.id === c.id ? " on" : ""}">${claimCard(c)}
        <div class="btns"><button class="ok" data-review="accepted" data-key="${c.id}">✓ Accept</button><button class="no" data-review="rejected" data-key="${c.id}">✕ Reject</button>${c.review ? `<button data-review="reset" data-key="${c.id}">Undo</button>` : ""}</div></div>`).join("")
        || '<div class="row sub">Nothing in this list.</div>');
    $("#rv-filter").onchange = (ev) => { S.rvFilter = ev.target.value; buildReview(); };
    $("#rv-th").oninput = (ev) => { THRESH = +ev.target.value; $("#rv-thv").textContent = THRESH.toFixed(2); };
    $("#rv-th").onchange = () => { buildReview(); lastKey = ""; setTime(S.t, true, false, true); };
    $("#rv-who").onchange = (ev) => localStorage.setItem("reviewer", ev.target.value.trim());
  }
  function eventHtml(v) {
    const cl = v.claims.map((id) => C.get(id));
    const photos = v.time ? B.photos.filter((p) => p.date && p.date >= v.time.start.slice(0, 10) && p.date <= v.time.end.slice(0, 10)).map((p) => p.file) : [];
    return `<h2>${esc(v.title)}</h2><div><span class="tag" style="background:${css("--k-" + v.kind)}">${KIND_LABEL[v.kind]}</span>
      <span class="meta">${span(v)} · ${cl.length} claims · ${v.pids.length} passages</span></div>
      ${v.summary ? `<p>${esc(v.summary)}</p>` : ""}${photos.length ? "<h3>Photos dated in this event</h3>" + photoThumbs(photos) : ""}
      <h3>Sequence of claims</h3><div class="seq">${cl.map((c) => claimCard(c)).join("")}</div>`;
  }
  $("#inspector").addEventListener("click", (ev) => {
    const q = (a) => ev.target.closest(`[data-${a}]`)?.dataset[a];
    if (q("review")) return review(C.get(q("key")), q("review"));
    if (q("scene")) return openScene(q("scene"), q("fly"));
    if (q("pin")) return placePin(q("pin"));
    if (q("unpin")) return savePin(q("scene2"), E.get(q("unpin")), null, true);
    if (q("photo") && ev.target.tagName === "IMG") return lightbox(q("photo"));
    if (q("focus")) return focusEntity(q("focus"));
    if (q("goto")) return setTime(+q("goto"));
    if (q("ent")) return select({ type: "entity", id: q("ent") });
    if (q("event")) return gotoEvent(V.get(q("event")));
    if (q("claim")) return select({ type: "claim", id: q("claim") });
  });
  function lightbox(file) {
    const lb = $("#lightbox"); lb.querySelector("img").src = "case/photos/" + encodeURIComponent(file);
    lb.querySelector(".cap").textContent = B.photos.find((p) => p.file === file)?.caption || file; lb.classList.remove("hidden");
  }
  $("#lightbox").onclick = () => $("#lightbox").classList.add("hidden");

  // ---------- left panes ----------
  function buildLeft() {
    const groups = d3.groups(B.events, (v) => v.time ? d3.timeFormat("%B %Y")(v.t0) : "Undated: profiles, theories, open questions");
    $("#tab-events").innerHTML = groups.map(([g, vs]) => `<div class="group-h">${g}</div>` + vs.map((v) =>
      `<div class="row" data-event="${v.id}"><div class="when">${span(v)} · ${v.claims.length} claims</div>
       <div class="ttl"><span class="kind" style="background:${css("--k-" + v.kind)}"></span>${esc(v.title)}</div></div>`).join("")).join("");
    let last = "";
    $("#tab-sources").innerHTML = `<div class="group-h">Evidence register (${B.evidence.length})</div>` +
      B.evidence.filter((e) => e.kind !== "link").map((e) => `<div class="passage none"><b>${e.id}</b> ${esc(e.title)} ${e.path ? `<a href="case/${esc(e.path)}" target="_blank" style="color:#8ec5ff">open</a>` : ""}</div>`).join("") +
      B.passages.filter((p) => p.n_claims || p.date_heading).map((p) => {
        const h = p.section + (p.date_heading ? " · " + p.date_heading : p.subsection ? " · " + p.subsection : "");
        const head = h !== last ? `<div class="group-h">${esc(h)}</div>` : ""; last = h;
        return head + `<div class="passage${p.n_claims ? "" : " none"}" data-passage="${p.id}"><span class="n">${p.n_claims || ""}</span>${esc(p.text)}</div>`;
      }).join("");
    $("#tab-photos").innerHTML = `<div class="photos">` + B.photos.map((p) =>
      `<div class="photo" data-photo="${esc(p.file)}"><img loading="lazy" src="case/photos/${encodeURIComponent(p.file)}"><div class="c">${esc(p.caption)}<div class="d">${p.date || "undated"}</div></div></div>`).join("") + `</div>`;
    $("#tab-entities").innerHTML = B.entities.slice().sort((a, b) => b.n_claims - a.n_claims).slice(0, 400).map((e) =>
      `<div class="row" data-ent="${e.id}">${typeTag(e.type)}${esc(e.name)} <span class="sub">${e.n_claims}</span></div>`).join("");
  }
  $("#left").addEventListener("click", (ev) => {
    const q = (a) => ev.target.closest(`[data-${a}]`)?.dataset[a];
    if (ev.target.tagName === "A" || ["INPUT", "SELECT", "LABEL"].includes(ev.target.tagName)) return;
    if (q("review")) review(C.get(q("key")), q("review"));
    else if (q("claim")) { const c = C.get(q("claim")); if (c.time) setTime((c.t0 + c.t1) / 2, true); select({ type: "claim", id: c.id }); }
    else if (q("event")) gotoEvent(V.get(q("event")));
    else if (q("passage")) { const p = P.get(q("passage")); if (p.time) setTime(T(p.time.start) + 12 * 36e5, true); select({ type: "passage", id: p.id }); }
    else if (q("photo")) select({ type: "photo", id: q("photo") });
    else if (q("ent")) select({ type: "entity", id: q("ent") });
  });
  document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
    document.querySelectorAll(".tabs button, #left .tab").forEach((x) => x.classList.remove("on"));
    b.classList.add("on"); $("#tab-" + b.dataset.tab).classList.add("on"); syncLeft(true);
  });
  function syncLeft(scroll) {
    const act = new Set(activeEvents().map((v) => v.id)), pids = new Set();
    act.forEach((id) => V.get(id).pids.forEach((p) => pids.add(p)));
    const day = new Date(S.t - new Date(S.t).getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
    const mark = (sel, attr, test) => { let first = null; document.querySelectorAll(sel).forEach((r) => { const on = test(r.dataset[attr]); r.classList.toggle("on", on); if (on && !first) first = r; }); return first; };
    const f1 = mark("#tab-events .row", "event", (id) => act.has(id) || (S.sel?.type === "event" && S.sel.id === id));
    const f2 = mark("#tab-sources .passage[data-passage]", "passage", (id) => pids.has(id));
    const f3 = mark("#tab-photos .photo", "photo", (f) => B.photos.find((p) => p.file === f)?.date === day || (S.sel?.type === "photo" && S.sel.id === f));
    if (scroll) [f1, f2, f3].forEach((f) => f && f.closest(".tab").classList.contains("on") && f.scrollIntoView({ block: "center" }));
  }

  // ---------- timeline ----------
  const LABEL = 118, ROW = 18, RULER = 22;
  const top8 = B.entities.slice().sort((a, b) => b.n_claims - a.n_claims).filter((e) => e.type !== "LOCATION" || e.n_claims > 20).slice(0, 8);
  const tsvg = d3.select("#tracks"), osvg = d3.select("#overview");
  let x = d3.scaleTime(), W = 0;
  function rows() {
    const ents = S.focus && !top8.some((e) => e.id === S.focus) ? [E.get(S.focus), ...top8] : top8;
    return [...KINDS.map((k) => ({ type: "kind", k, label: KIND_LABEL[k] })), { type: "density", label: "All claims" },
      ...ents.map((e) => ({ type: "ent", e, label: e.name })), { type: "photos", label: "Photos" }];
  }
  function drawTimeline() {
    W = $("#tracks-wrap").clientWidth;
    const R = rows(), H = RULER + R.length * ROW + 4;
    x = d3.scaleTime().domain(S.view.map((d) => new Date(d))).range([LABEL, W - 6]);
    tsvg.attr("height", H).selectAll("*").remove();
    const [v0, v1] = S.view, vis = (a, b) => b >= v0 && a <= v1;
    tsvg.append("g").attr("class", "axis").attr("transform", `translate(0,${RULER})`).call(d3.axisTop(x).ticks(Math.max(4, W / 110)).tickSize(4));
    R.forEach((r, i) => {
      const y = RULER + i * ROW, g = tsvg.append("g").attr("transform", `translate(0,${y})`);
      g.append("rect").attr("class", "tl-row" + (i % 2 ? " alt" : "")).attr("width", W).attr("height", ROW);
      g.append("text").attr("class", "tl-label").attr("x", 8).attr("y", 12.5).text(r.label.length > 17 ? r.label.slice(0, 16) + "…" : r.label)
        .style("cursor", r.type === "ent" ? "pointer" : null).on("pointerdown", (ev) => { if (r.type === "ent") { ev.stopPropagation(); select({ type: "entity", id: r.e.id }); } });
      const bar = (a, b, fill, cls, d) => {
        const xa = Math.max(LABEL, x(a)), xb = Math.min(W, Math.max(x(b), x(a) + 4));
        if (xb <= LABEL) return null;
        return g.append("rect").attr("x", xa).attr("y", 2).attr("width", Math.max(3, xb - xa)).attr("height", ROW - 4).attr("fill", fill).attr("class", cls || null).datum(d);
      };
      if (r.type === "kind") {
        const act = new Set(activeEvents().map((v) => v.id));
        TIMED.filter((v) => v.kind === r.k && vis(v.t0, v.t1)).forEach((v) => {
          const b = bar(v.t0, v.t1, css("--k-" + v.kind), "clip" + (act.has(v.id) ? " on" : ""), v);
          if (!b) return;
          b.on("pointerdown", (ev) => { ev.stopPropagation(); gotoEvent(v); }).append("title").text(v.title);
          const w = +b.attr("width");
          if (w > 54) g.append("text").attr("class", "clip-label").attr("x", +b.attr("x") + 4).attr("y", 12.5).text(v.title.slice(0, Math.floor(w / 6.2)));
        });
      } else if (r.type === "density") {
        const bins = d3.bin().domain([v0, v1]).thresholds(Math.floor((W - LABEL) / 5))(B.claims.filter((c) => c.time && c.t1 - c.t0 < 40 * DAY).map((c) => c.t0));
        const m = d3.max(bins, (b) => b.length) || 1;
        bins.forEach((b) => b.length && g.append("rect").attr("x", x(b.x0)).attr("width", Math.max(1, x(b.x1) - x(b.x0) - 1))
          .attr("y", ROW - 1 - (ROW - 3) * b.length / m).attr("height", (ROW - 3) * b.length / m).attr("fill", "#8b93a1"));
      } else if (r.type === "ent") {
        (claimsOf.get(r.e.id) || []).filter((c) => c.time && c.t1 - c.t0 < 400 * DAY && vis(c.t0, c.t1)).forEach((c) => bar(c.t0, c.t1, color(r.e.type), null, c)?.attr("opacity", 0.75));
      } else {
        B.photos.filter((p) => p.date).forEach((p) => { const t = T(p.date + "T12:00"); if (vis(t, t)) g.append("circle").attr("cx", x(t)).attr("cy", ROW / 2).attr("r", 4).attr("fill", "#e9d7b6").style("cursor", "pointer").on("pointerdown", (ev) => { ev.stopPropagation(); select({ type: "photo", id: p.file }); }).append("title").text(p.caption); });
      }
    });
    tsvg.append("g").attr("class", "playhead");
    drawPlayhead(); drawOverview();
  }
  function drawPlayhead() {
    const g = tsvg.select(".playhead"), px = x(S.t), H = +tsvg.attr("height");
    g.selectAll("*").remove();
    if (px < LABEL || px > W) return;
    g.append("line").attr("x1", px).attr("x2", px).attr("y1", 6).attr("y2", H);
    g.append("path").attr("d", `M${px - 7},0h14v8l-7,7l-7,-7z`);
  }
  function drawOverview() {
    const w = $("#overview").clientWidth, ox = d3.scaleTime().domain(full.map((d) => new Date(d))).range([LABEL, w - 6]);
    osvg.selectAll("*").remove();
    osvg.append("text").attr("class", "tl-label").attr("x", 8).attr("y", 17).text("Whole case");
    TIMED.forEach((v) => osvg.append("rect").attr("x", ox(v.t0)).attr("y", 6).attr("width", Math.max(1.5, ox(v.t1) - ox(v.t0))).attr("height", 14).attr("fill", css("--k-" + v.kind)).attr("opacity", 0.8));
    osvg.append("rect").attr("class", "ov-view").attr("x", ox(S.view[0])).attr("y", 2).attr("width", Math.max(6, ox(S.view[1]) - ox(S.view[0]))).attr("height", 22);
    osvg.append("line").attr("x1", ox(S.t)).attr("x2", ox(S.t)).attr("y1", 0).attr("y2", 26).attr("stroke", css("--play")).attr("stroke-width", 1.5);
    osvg.on("pointerdown", (ev) => {
      const move = (e) => { const c = ox.invert(d3.pointer(e, osvg.node())[0]).getTime(), half = (S.view[1] - S.view[0]) / 2; setView([c - half, c + half]); };
      move(ev); const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    });
  }
  function setView(v) {
    let span = Math.min(full[1] - full[0], Math.max(6 * 36e5, v[1] - v[0])), a = Math.max(full[0], Math.min(full[1] - span, v[0]));
    S.view = [a, a + span]; drawTimeline();
  }
  tsvg.on("pointerdown", (ev) => {
    const start = d3.pointer(ev, tsvg.node())[0]; if (start < LABEL) return;
    const pan = ev.shiftKey, v0 = S.view.slice(), k = (v0[1] - v0[0]) / (W - 6 - LABEL);
    const move = (e) => { const px = d3.pointer(e, tsvg.node())[0]; pan ? setView([v0[0] - (px - start) * k, v0[1] - (px - start) * k]) : setTime(x.invert(Math.max(LABEL, Math.min(W - 6, px))).getTime(), false, true); };
    move(ev); const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); syncLeft(true); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  });
  $("#tracks-wrap").addEventListener("wheel", (ev) => {
    if (!ev.ctrlKey && Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) return;
    ev.preventDefault();
    const c = x.invert(d3.pointer(ev, tsvg.node())[0]).getTime(), f = ev.deltaY > 0 ? 1.25 : 0.8;
    setView([c - (c - S.view[0]) * f, c + (S.view[1] - c) * f]);
  }, { passive: false });

  // ---------- the selection model ----------
  let lastKey = "";
  function setTime(t, keepSel, scrubbing, keepPin) {
    if (!keepPin) S.pin = null;
    S.t = Math.max(full[0], Math.min(full[1], t));
    if (S.t < S.view[0] || S.t > S.view[1]) { const half = (S.view[1] - S.view[0]) / 2; S.view = [S.t - half, S.t + half]; drawTimeline(); }
    const act = activeEvents();
    $("#clock").textContent = d3.timeFormat("%a %d %b %Y  %H:%M")(S.t);
    $("#now").textContent = S.pin && S.mode === "event" ? "Undated" : S.mode === "focus" && S.focus ? E.get(S.focus).name : S.mode === "cumulative" ? "Up to " + fmtDay(S.t) : fmtDay(S.t);
    const ne = d3.select("#now-events"); ne.selectAll("*").remove();
    // one event on stage at a time: the crime itself first, then discoveries, then the rest
    const rank = (v) => KINDS.indexOf(v.kind) * 1000 - v.claims.length;
    if (S.solo !== "all" && !act.some((v) => v.id === S.solo)) S.solo = act.length > 1 ? act.slice().sort((a, b) => rank(a) - rank(b))[0].id : null;
    if (S.mode === "event") {
      const pick = (id) => { S.solo = id; S.sel = id && id !== "all" ? { type: "event", id } : null; lastKey = ""; setTime(S.t, true, false, true); renderInspector(); };
      if (act.length > 1) ne.append("span").attr("class", "chip" + (S.solo === "all" ? " on" : "")).text(`all ${act.length} events`).on("click", () => pick("all"));
      act.forEach((v) => ne.append("span").attr("class", "chip" + (act.length === 1 || S.solo === v.id ? " on" : "")).attr("title", v.summary || v.title)
        .html(`<span class="kind" style="background:${css("--k-" + v.kind)}"></span>${esc(v.title)}`).on("click", () => pick(v.id)));
    }
    const key = S.mode + "|" + S.focus + "|" + S.pin + "|" + (S.mode === "event" ? act.map((v) => v.id).join() + S.solo : S.mode === "cumulative" ? Math.floor(S.t / DAY) : "");
    if (key !== lastKey) {
      lastKey = key;
      if (!keepSel && !scrubbing && S.sel?.type !== "entity") S.sel = null;
      buildGraph(); drawTimeline();
      if (!S.sel || S.sel.type === "entity") renderInspector();
      syncLeft(!scrubbing);
    } else { drawPlayhead(); drawOverview(); }
  }
  function select(sel) {
    S.sel = sel; paintSelection(); renderInspector(); syncLeft(false);
    document.querySelectorAll("#tab-review .rv-item").forEach((r) => r.classList.toggle("on", sel?.type === "claim" && r.querySelector("[data-claim]")?.dataset.claim === sel.id));
    window.SceneView?.ready && window.SceneView.setActive(new Set(NODES.map((n) => n.id)), sel?.type === "entity" ? sel.id : null);
  }
  function gotoEvent(v) {
    if (S.mode === "focus") setMode("event");
    S.solo = v.id; S.sel = { type: "event", id: v.id };
    if (!v.time) { S.pin = v.id; lastKey = ""; setTime(S.t, true, false, true); renderInspector(); syncLeft(false); return; }
    const span = S.view[1] - S.view[0];
    if (v.t1 - v.t0 > span) S.view = [v.t0 - (v.t1 - v.t0) * 0.2, v.t1 + (v.t1 - v.t0) * 0.2];
    lastKey = ""; setTime(Math.min(v.t0 + 12 * 36e5, (v.t0 + v.t1) / 2), true); renderInspector(); syncLeft(true);
  }
  function focusEntity(id) { S.focus = id; setMode("focus"); select({ type: "entity", id }); }
  function setMode(m) {
    S.mode = m; document.querySelectorAll("#mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
    lastKey = ""; setTime(S.t, true, false, true);
  }
  document.querySelectorAll("#mode button").forEach((b) => b.onclick = () => { if (b.dataset.mode === "focus" && !S.focus && S.sel?.type === "entity") S.focus = S.sel.id; setMode(b.dataset.mode); });
  const starts = [...new Set(TIMED.map((v) => v.t0))].sort((a, b) => a - b);
  const step = (dir) => {
    const cur = S.t - 12 * 36e5, t = dir > 0 ? starts.find((s) => s > cur + 1) : [...starts].reverse().find((s) => s < cur - 1);
    if (t == null) return false;
    const v = TIMED.filter((e) => e.t0 === t).sort((a, b) => (a.t1 - a.t0) - (b.t1 - b.t0))[0];
    S.sel = null; if (v.t1 - v.t0 > S.view[1] - S.view[0]) S.view = [v.t0 - DAY, v.t1 + DAY];
    lastKey = ""; setTime(Math.min(t + 12 * 36e5, (v.t0 + v.t1) / 2)); return true;
  };
  $("#prev").onclick = () => step(-1); $("#next").onclick = () => step(1);
  function play(on) {
    clearInterval(S.playing); S.playing = null; $("#play").textContent = "▶";
    if (!on) return;
    $("#play").textContent = "⏸"; S.playing = setInterval(() => { if (!step(1)) play(false); }, 2500 / +$("#speed").value);
  }
  $("#play").onclick = () => play(!S.playing); $("#speed").onchange = () => S.playing && play(true);
  $("#fit-all").onclick = () => setView(full.slice()); $("#fit-incident").onclick = () => setView(incident.slice());
  window.addEventListener("keydown", (ev) => {
    if (["INPUT", "SELECT"].includes(ev.target.tagName)) return;
    if (ev.key === " ") { ev.preventDefault(); play(!S.playing); } else if (ev.key === "]" || ev.key === "ArrowRight") step(1);
    else if (ev.key === "[" || ev.key === "ArrowLeft") step(-1); else if (ev.key === "Escape") { $("#lightbox").classList.add("hidden"); select(null); }
  });

  // ---------- 3D scene ----------
  let sceneLoading = null;
  const sceneHooks = {
    resolve: (name) => byName.get(normName(name)),
    onPick: (eid) => { if (!$("#page-investigate").classList.contains("on")) { window.__nav("investigate"); openScene(); } select({ type: "entity", id: eid }); },
    onPlace: (sceneId, ent, xyz) => savePin(sceneId, ent, xyz, false),
    lightbox: (src, cap) => { const lb = $("#lightbox"); lb.querySelector("img").src = src; lb.querySelector(".cap").textContent = cap; lb.classList.remove("hidden"); },
  };
  async function openScene(id, flyId) {
    const sc = SCENES.find((x) => x.id === id) || SCENES.find((x) => x.id === S.sceneId) || SCENES[0]; if (!sc) return;
    S.view3d = true; S.sceneId = sc.id;
    const pick = $("#scene-pick"); pick.value = sc.id; pick.classList.toggle("hidden", SCENES.length < 2);
    document.querySelectorAll("#viewsel button").forEach((b) => b.classList.toggle("on", b.dataset.view === "scene3d"));
    $("#graph").classList.add("hidden"); $("#legend").classList.add("hidden"); $("#empty").classList.add("hidden");
    $("#scene-host-a").classList.remove("hidden"); $("#scene-host-a").appendChild($("#scene"));
    if (!window.SceneView) { sceneLoading = sceneLoading || import("./scene.js"); await sceneLoading; }
    await window.SceneView.open(sc, sceneHooks);
    window.SceneView.setActive(new Set(NODES.map((n) => n.id)), S.sel?.type === "entity" ? S.sel.id : null);
    if (flyId) window.SceneView.flyTo(flyId);
  }
  function closeScene() {
    S.view3d = false; window.SceneView?.cancelPlacing();
    document.querySelectorAll("#viewsel button").forEach((b) => b.classList.toggle("on", b.dataset.view === "graph"));
    $("#scene-host-a").classList.add("hidden"); $("#graph").classList.remove("hidden"); $("#legend").classList.remove("hidden"); buildGraph();
  }
  async function placePin(eid) { await openScene(S.sceneId); window.SceneView.startPlacing(E.get(eid)); }
  async function savePin(sceneId, ent, xyz, remove) {
    const res = await fetch("api/anchor", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scene: sceneId, entity: ent.name, xyz, remove, placed_by: localStorage.getItem("reviewer") || "" }) });
    const out = await res.json(); if (out.error) return alert("Could not save the pin: " + out.error);
    const list = out.result || out, sc = SCENES.find((x) => x.id === sceneId); sc.anchors = list;
    if (window.SceneView?.meta?.id === sceneId) window.SceneView.setPins(list);
    select({ type: "entity", id: ent.id });
  }
  document.querySelectorAll("#viewsel button").forEach((b) => b.onclick = () => (b.dataset.view === "scene3d" ? openScene() : closeScene()));
  if (!SCENES.length) $("#viewsel").classList.add("hidden");
  $("#scene-pick").innerHTML = SCENES.map((sc) => `<option value="${esc(sc.id)}">${esc(sc.title)}</option>`).join("");
  $("#scene-pick").onchange = (ev) => openScene(ev.target.value);
  window.addEventListener("keydown", (ev) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(ev.target.tagName)) return;
    if (ev.key === "Escape") window.SceneView?.cancelPlacing();
    if (S.sel?.type !== "claim") return;
    if (ev.key === "a" || ev.key === "A") review(C.get(S.sel.id), "accepted");
    if (ev.key === "r" || ev.key === "R") review(C.get(S.sel.id), "rejected");
  });

  // ---------- search ----------
  const sr = $("#search-results");
  $("#search").addEventListener("input", (ev) => {
    const q = ev.target.value.trim().toLowerCase();
    if (q.length < 2) return sr.classList.add("hidden");
    const hits = B.entities.filter((e) => [e.name, ...e.aliases].some((n) => n.toLowerCase().includes(q))).sort((a, b) => b.n_claims - a.n_claims).slice(0, 14);
    sr.innerHTML = hits.map((e) => `<div data-ent="${e.id}">${typeTag(e.type)}${esc(e.name)} <span class="meta">${e.n_claims} claims</span></div>`).join("") || '<div class="meta">no match</div>';
    sr.classList.remove("hidden");
  });
  sr.addEventListener("click", (ev) => { const id = ev.target.closest("[data-ent]")?.dataset.ent; if (id) { sr.classList.add("hidden"); $("#search").value = ""; focusEntity(id); } });

  $("#legend").innerHTML = `<span>● tracked instance</span><span>■ place / setting</span><span><i></i>stated</span><span><i style="border-top-style:dashed"></i>reported</span><span><i style="border-top-style:dotted"></i>alleged / speculated</span><span>double-click a node for all its claims</span>`;
  window.addEventListener("resize", () => { drawTimeline(); buildGraph(); });
  buildLeft(); buildReview(); drawTimeline(); setTime(S.t);
  window.__desk = { S, B, E, C, V, P, EV, claimsOf, passageClaims, esc, fmtDay, typeTag, sceneHooks, gotoEvent, SCENES, anchorOf, sceneOf, color, css, openScene, closeScene, review, status, setTime, select, step, setMode, focusEntity, activeEvents, stageClaims };
  window.dispatchEvent(new Event("desk-ready"));
})();
