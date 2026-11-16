/* Analysis: the comparisons an investigator otherwise does by memory and on paper.
   Computed from the claims on every visit, so it follows review decisions. */
window.addEventListener("desk-ready", async () => {
  const D = window.__desk, B = D.B, E = D.E, esc = D.esc, $ = (s) => document.querySelector(s);
  const DAY = 864e5, day = (t) => D.fmtDay(new Date(t));
  const who = () => { try { return localStorage.getItem("reviewer") || ""; } catch (e) { return ""; } };
  // dismissed comparison items are a per-browser convenience, not part of the case record
  let dismissed = []; try { dismissed = JSON.parse(localStorage.getItem("dismissed:" + B.case.id) || "[]"); } catch (e) { /* storage unavailable */ }

  // claims that count: not rejected by a reviewer, not demo links
  const live = () => B.claims.filter((c) => !c.demo && D.status(c) !== "rejected");
  const name = (id) => E.get(id).name;
  const objOf = (c) => (c.o ? name(c.o) : c.literal);
  const factKey = (c) => `${c.s}|${c.p}|${c.o || "lit:" + String(c.literal).toLowerCase()}`;
  const group = (list, key) => { const m = new Map(); list.forEach((x) => { const k = key(x); if (k != null) (m.get(k) || m.set(k, []).get(k)).push(x); }); return m; };
  const ACC = new Set(["KILLED", "SHOT", "ATTACKED", "ABDUCTED", "THREATENED", "SUSPECTED_OF", "ARRESTED", "CHARGED_WITH"]);
  const cards = (cl) => cl.map((c) => D.claimCard(c)).join("");
  const byTime = (a, b) => (a.t0 ?? Infinity) - (b.t0 ?? Infinity);

  // ---------- points to compare ----------
  function comparisons() {
    const cl = live(), out = [];
    const add = (type, title, why, claims) => out.push({ id: type + ":" + claims.map((c) => c.key).sort().join(",").slice(0, 120), type, title, why, claims });
    // 1. a person both suspected and cleared: show the whole status history
    for (const [s, g] of group(cl.filter((c) => ["SUSPECTED_OF", "ARRESTED", "CHARGED_WITH", "CLEARED", "RELEASED"].includes(c.p)), (c) => c.s)) {
      const neg = g.filter((c) => ["CLEARED", "RELEASED"].includes(c.p)), pos = g.filter((c) => !["CLEARED", "RELEASED"].includes(c.p));
      if (neg.length && pos.length) add("status", `${name(s)}: suspected or arrested, and cleared or released`, "The file records both. Read them in date order to see which stands now.", g.sort(byTime));
    }
    // 2. the same thing found in more than one place
    for (const [s, g] of group(cl.filter((c) => c.p === "FOUND_AT" && c.o), (c) => c.s)) {
      const places = new Set(g.map((c) => c.o));
      if (places.size > 1) add("place", `${name(s)}: found at ${places.size} different places`, "These may be the same place under different names, a nested place, or a real conflict.", g.sort(byTime));
    }
    // 3. stated as fact in one passage, only alleged or speculated in another
    for (const [, g] of group(cl, factKey)) {
      const strong = g.filter((c) => c.certainty === "stated"), weak = g.filter((c) => ["alleged", "speculated"].includes(c.certainty));
      if (strong.length && weak.length) add("certainty", `${name(g[0].s)} — ${D.predLabel(g[0])} → ${objOf(g[0])}: fact in one passage, allegation in another`, "The same thing is worded with different strength in different places.", g);
    }
    // 4. the same fact placed on different dates
    const DATED = new Set(["FOUND", "FOUND_AT", "KILLED", "SHOT", "ABDUCTED", "ARRESTED", "CHARGED_WITH", "CLEARED", "IDENTIFIED_AS", "RELEASED"]);
    for (const [, g] of group(cl.filter((c) => DATED.has(c.p) && c.time && c.t1 - c.t0 < 1.5 * DAY), factKey)) {
      const days = new Set(g.map((c) => c.time.start.slice(0, 10)));
      if (days.size > 1 && new Set(g.map((c) => c.pid)).size > 1) add("date", `${name(g[0].s)} — ${D.predLabel(g[0])} → ${objOf(g[0])}: ${days.size} different dates`, "One may be the event and another the day it was reported. Check the wording.", g.sort(byTime));
    }
    // 5. two different descriptions of the same unnamed or named person
    for (const [s, g] of group(cl.filter((c) => !c.o && ["HAS_ATTRIBUTE", "WORE"].includes(c.p) && E.get(c.s).type === "PERSON"), (c) => c.s)) {
      const srcs = new Set(g.map((c) => c.by || c.pid));
      if (g.length > 1 && srcs.size > 1 && /unidentified|unknown|man |woman|suspect|person/i.test(name(s))) add("description", `${name(s)}: ${g.length} descriptions from ${srcs.size} sources`, "Compare the descriptions. Differences between sources matter for identification.", g);
    }
    const gone = new Set(dismissed);
    return out.map((x) => Object.assign(x, { dismissed: gone.has(x.id) }));
  }

  // ---------- corroboration ----------
  function corroboration() {
    const rows = [...group(live(), factKey).values()].map((g) => ({ g, passages: new Set(g.map((c) => c.pid)).size,
      sources: new Set(g.flatMap((c) => c.evidence.filter((e) => e !== "E001").concat(c.by ? ["by:" + c.by] : []))).size }));
    return { multi: rows.filter((r) => r.passages > 1).sort((a, b) => b.passages - a.passages).slice(0, 60),
      lone: rows.filter((r) => r.passages === 1 && ACC.has(r.g[0].p)).sort((a, b) => a.g[0].conf - b.g[0].conf) };
  }

  // ---------- leads and gaps ----------
  function leads() {
    const cl = live(), of = (id) => cl.filter((c) => c.s === id || c.o === id || c.by === id);
    const people = B.entities.filter((e) => e.type === "PERSON" && !e.demo);
    const vague = /unidentified|unknown|unnamed|anyone|people who|several|multiple|no person|person of interest|offender|killer/i;
    const spoke = people.filter((e) => !vague.test(e.name) && cl.some((c) => c.by === e.id || (c.s === e.id && ["SAW", "HEARD", "SAID", "REPORTED", "DESCRIBED"].includes(c.p))))
      .filter((e) => !cl.some((c) => c.o === e.id && ["INTERVIEWED", "CONTACTED"].includes(c.p)))
      .map((e) => ({ e, n: cl.filter((c) => c.by === e.id || (c.s === e.id && ["SAW", "HEARD", "SAID", "REPORTED", "DESCRIBED"].includes(c.p))).length })).sort((a, b) => b.n - a.n);
    const unknown = B.entities.filter((e) => ["PERSON", "VEHICLE"].includes(e.type) && !e.demo && /unidentified|unknown|unnamed/i.test(e.name) && of(e.id).length)
      .map((e) => ({ e, n: of(e.id).length })).sort((a, b) => b.n - a.n);
    const things = B.entities.filter((e) => ["OBJECT", "WEAPON", "VEHICLE", "DOCUMENT"].includes(e.type) && !e.demo)
      .filter((e) => cl.some((c) => (c.o === e.id && ["FOUND", "COLLECTED", "TOOK"].includes(c.p)) || (c.s === e.id && c.p === "FOUND_AT")))
      .filter((e) => !cl.some((c) => c.o === e.id && c.p === "EXAMINED") && !cl.some((c) => c.s === e.id && c.p === "IDENTIFIED_AS"))
      .map((e) => ({ e, n: of(e.id).length })).sort((a, b) => b.n - a.n);
    const win = (B.case.incident_window || []).map((d) => new Date(d + "T12:00").getTime());
    const gaps = [];
    if (win.length === 2) for (const e of people.slice().sort((a, b) => b.n_claims - a.n_claims).slice(0, 8)) {
      const ts = of(e.id).filter((c) => c.time && c.t1 - c.t0 < 3 * DAY && c.t0 > win[0] - 20 * DAY && c.t0 < win[1] + 5 * DAY).map((c) => c.t0).sort((a, b) => a - b);
      for (let i = 1; i < ts.length; i++) if (ts[i] - ts[i - 1] > 4 * DAY) gaps.push({ e, from: ts[i - 1], to: ts[i], days: Math.round((ts[i] - ts[i - 1]) / DAY) });
    }
    return { spoke, unknown, things, gaps: gaps.sort((a, b) => b.days - a.days) };
  }

  // ---------- connection between two entities ----------
  function path(a, b) {
    const adj = new Map();
    // generic collectives ("investigators", "police") touch everything and would make every chain trivial
    const hub = (id) => id !== a && id !== b && /^(the )?(investigators?|authorities|police|law enforcement|officers|detectives|officials|fbi|prosecutors)$/i.test(name(id));
    live().filter((c) => c.o && !hub(c.s) && !hub(c.o)).forEach((c) => { (adj.get(c.s) || adj.set(c.s, []).get(c.s)).push([c.o, c]); (adj.get(c.o) || adj.set(c.o, []).get(c.o)).push([c.s, c]); });
    const prev = new Map([[a, null]]), q = [a];
    while (q.length) { const x = q.shift(); if (x === b) break; for (const [y, c] of adj.get(x) || []) if (!prev.has(y)) { prev.set(y, [x, c]); q.push(y); } }
    if (!prev.has(b)) return null;
    const hops = []; for (let x = b; prev.get(x); x = prev.get(x)[0]) hops.unshift({ from: prev.get(x)[0], to: x, claim: prev.get(x)[1] });
    return hops;
  }

  // ---------- pages ----------
  let aTab = "compare", conn = { a: "", b: "" }, dossierId = null, showDismissed = false;
  const entByName = (s) => B.entities.find((e) => e.name.toLowerCase() === s.trim().toLowerCase()) || B.entities.find((e) => [e.name, ...e.aliases].some((n) => n.toLowerCase().includes(s.trim().toLowerCase())) && s.trim().length > 2);

  function renderAnalysis() {
    const cmp = comparisons(), cor = corroboration(), ld = leads(), open = cmp.filter((x) => !x.dismissed);
    const tabs = [["compare", "Points to compare", open.length], ["corroboration", "Corroboration", cor.lone.length], ["leads", "Leads and gaps", ld.spoke.length + ld.unknown.length + ld.things.length],
      ["connect", "Connection finder", ""], ["dossier", "Person dossier", ""], ["brief", "Case brief", ""]];
    let body = "";
    if (aTab === "compare") {
      const TYPE = { status: "Status over time", place: "Place", certainty: "Strength of wording", date: "Date", description: "Description" };
      const list = cmp.filter((x) => showDismissed || !x.dismissed);
      body = `<h1>Points to compare</h1><div class="lead">Places where the file says two things about the same subject. The tool does not decide which is right, and a difference is not a lie: it is a place to read both passages side by side.</div>
        <div class="btns noprint" style="margin:12px 0"><button data-toggle-dis>${showDismissed ? "Hide" : "Show"} dismissed (${cmp.length - open.length})</button></div>
        ${list.map((x) => `<div class="item" style="${x.dismissed ? "opacity:.5" : ""}"><div class="h"><span class="pill wait">${TYPE[x.type]}</span><b>${esc(x.title)}</b><span class="spacer"></span>
          <button data-dismiss="${esc(x.id)}">${x.dismissed ? "Restore" : "Dismiss"}</button></div><div class="meta" style="margin-bottom:8px">${esc(x.why)}</div><div class="two">${cards(x.claims.slice(0, 8))}</div>${x.claims.length > 8 ? `<div class="meta">and ${x.claims.length - 8} more</div>` : ""}</div>`).join("") || '<div class="lead">Nothing to compare.</div>'}`;
    } else if (aTab === "corroboration") {
      body = `<h1>Corroboration</h1><div class="lead">How many separate passages say the same thing. Passages of one web page are not independent witnesses, so read this as “repeated in the file”, not “proven”.</div>
        <h2>Accusations that rest on a single passage (${cor.lone.length})</h2><div class="lead">Killing, shooting, abduction, suspicion, arrest or charge, stated once. These deserve a second source before anyone acts on them.</div><div class="two" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px">${cards(cor.lone.map((r) => r.g[0]))}</div>
        <h2>Said in more than one passage (${cor.multi.length})</h2><table class="t"><tr><th>Fact</th><th>Passages</th><th>Other sources named</th></tr>${cor.multi.map((r) => `<tr class="click" data-claim="${r.g[0].id}"><td><b>${esc(name(r.g[0].s))}</b> — ${esc(D.predLabel(r.g[0]))} → <b>${esc(objOf(r.g[0]))}</b></td><td>${r.passages}</td><td>${r.sources}</td></tr>`).join("")}</table>`;
    } else if (aTab === "leads") {
      const tbl = (rows, col) => `<table class="t"><tr><th>${col}</th><th>Claims</th></tr>${rows.slice(0, 60).map((r) => `<tr><td class="click" data-ent="${r.e.id}" style="cursor:pointer"><b>${esc(r.e.name)}</b></td><td>${r.n}</td></tr>`).join("") || '<tr><td colspan="2" class="meta">None.</td></tr>'}</table>`;
      body = `<h1>Leads and gaps</h1><div class="lead">What the file does not record. Each list is “no record found in this file”, which is not the same as “not done”.</div>
        <h2>People who gave information, with no interview recorded (${ld.spoke.length})</h2>${tbl(ld.spoke, "Person")}
        <h2>People and vehicles still unidentified (${ld.unknown.length})</h2>${tbl(ld.unknown, "Unidentified")}
        <h2>Items found or collected, with no examination recorded (${ld.things.length})</h2>${tbl(ld.things, "Item")}
        <h2>Stretches with nothing recorded, around the incident (${ld.gaps.length})</h2><table class="t"><tr><th>Person</th><th>From</th><th>To</th><th>Days</th></tr>${ld.gaps.slice(0, 40).map((g) => `<tr class="click" data-ent="${g.e.id}"><td><b>${esc(g.e.name)}</b></td><td>${day(g.from)}</td><td>${day(g.to)}</td><td>${g.days}</td></tr>`).join("") || '<tr><td colspan="4" class="meta">None.</td></tr>'}</table>`;
    } else if (aTab === "connect") {
      const A = conn.a && entByName(conn.a), Bq = conn.b && entByName(conn.b), hops = A && Bq ? path(A.id, Bq.id) : null;
      body = `<h1>Connection finder</h1><div class="lead">How two people, places or objects are linked through the claims in the file: the shortest chain, with the claim behind each step.</div>
        <datalist id="ent-list">${B.entities.slice().sort((a, b) => b.n_claims - a.n_claims).slice(0, 300).map((e) => `<option value="${esc(e.name)}">`).join("")}</datalist>
        <div class="btns noprint" style="margin:14px 0"><input id="cn-a" list="ent-list" placeholder="From…" value="${esc(conn.a)}" style="width:280px"><input id="cn-b" list="ent-list" placeholder="To…" value="${esc(conn.b)}" style="width:280px"><button id="cn-go">Find connection</button></div>
        ${conn.a && !A ? `<div class="msg err">No entity matches “${esc(conn.a)}”.</div>` : ""}${conn.b && !Bq ? `<div class="msg err">No entity matches “${esc(conn.b)}”.</div>` : ""}
        ${A && Bq ? (hops ? `<div class="path">${D.typeTag(A.type)}<b>${esc(A.name)}</b>${hops.map((h) => `<span class="hop">— ${esc(D.predLabel(h.claim))} —</span><b>${esc(name(h.to))}</b>`).join("")}</div><div class="meta">${hops.length} step${hops.length === 1 ? "" : "s"}</div><h2>The claim behind each step</h2>${cards(hops.map((h) => h.claim))}` : '<div class="lead">The file does not link these two.</div>') : ""}`;
    } else if (aTab === "dossier") {
      body = dossier();
    } else if (aTab === "brief") {
      const inc = B.events.filter((v) => !v.demo && ["action_point", "discovery"].includes(v.kind) && v.time);
      const facts = B.passages.filter((p) => p.section.startsWith("Case Files") && p.text.includes(":")).slice(0, 8);
      const dec = B.claims.filter((c) => c.review).length, pend = B.claims.filter((c) => D.status(c) === "pending").length;
      body = `<div class="btns noprint" style="float:right"><button data-print>Print or save as PDF</button></div><h1>Case brief: ${esc(B.case.title)}</h1><div class="meta">Generated ${new Date().toLocaleString()}${who() ? " by " + esc(who()) : ""} from ${B.stats.claims} claims in ${B.stats.evidence} evidence items. Machine-extracted; ${dec} claims reviewed by a person, ${pend} awaiting review.</div>
        <h2>The case</h2><table class="t">${facts.map((p) => { const i = p.text.indexOf(":"); return `<tr><td class="meta" style="width:230px">${esc(p.text.slice(0, i))}</td><td>${esc(p.text.slice(i + 1))}</td></tr>`; }).join("")}</table>
        <h2>The incident</h2><table class="t">${inc.map((v) => `<tr><td style="width:120px">${day(v.t0)}</td><td><b>${esc(v.title)}</b><div class="meta">${esc(v.summary || "")}</div></td></tr>`).join("")}</table>
        <h2>Key people</h2><table class="t">${B.entities.filter((e) => e.type === "PERSON" && !e.demo).sort((a, b) => b.n_claims - a.n_claims).slice(0, 10).map((e) => `<tr><td style="width:240px"><b>${esc(e.name)}</b></td><td class="meta">${(D.claimsOf.get(e.id) || []).filter((c) => c.s === e.id && !c.o).slice(0, 4).map((c) => esc(c.literal)).join(" · ")}</td><td>${e.n_claims} claims</td></tr>`).join("")}</table>
        <h2>Open points to compare (${open.length})</h2>${open.slice(0, 15).map((x) => `<div>• ${esc(x.title)}</div>`).join("") || '<div class="meta">None.</div>'}
        <h2>Leads</h2><div>${ld.spoke.length} people gave information with no interview recorded · ${ld.unknown.length} people or vehicles unidentified · ${ld.things.length} items with no examination recorded</div>`;
    }
    $("#page-analysis").innerHTML = `<div class="side-nav"><div class="panel-title">Analysis</div>${tabs.map(([id, label, n]) => `<div class="row${id === aTab ? " on" : ""}" data-atab="${id}">${label}<b>${n}</b></div>`).join("")}</div><div class="side-main"><div class="wrap">${body}</div></div>`;
    const go = $("#cn-go"); if (go) go.onclick = () => { conn = { a: $("#cn-a").value, b: $("#cn-b").value }; renderAnalysis(); };
    const pick = $("#dos-pick"); if (pick) pick.onchange = () => { dossierId = pick.value; renderAnalysis(); };
  }
  function dossier() {
    const people = B.entities.filter((e) => e.type === "PERSON" && !e.demo).sort((a, b) => b.n_claims - a.n_claims);
    const e = E.get(dossierId) || people[0]; dossierId = e.id;
    const cl = live().filter((c) => c.s === e.id || c.o === e.id || c.by === e.id).sort(byTime);
    const is = (...p) => (c) => p.includes(c.p);
    const sec = (title, list, empty) => `<h2>${title} (${list.length})</h2>${list.length ? cards(list.slice(0, 40)) : `<div class="meta">${empty || "Nothing recorded."}</div>`}`;
    return `<div class="dossier"><div class="btns noprint" style="float:right"><select id="dos-pick">${people.slice(0, 150).map((p) => `<option value="${p.id}"${p.id === e.id ? " selected" : ""}>${esc(p.name)} (${p.n_claims})</option>`).join("")}</select><button data-print>Print</button><button data-ent="${e.id}">Open in investigation</button></div>
      <h1>${esc(e.name)}</h1><div class="meta">${e.aliases.length ? "Also: " + e.aliases.map(esc).join(", ") + " · " : ""}${cl.length} claims${cl.length && cl[0].t0 ? " · first mentioned " + day(cl[0].t0) : ""}</div>
      ${e.photos.length ? `<div class="thumbs" style="margin-top:10px">${e.photos.map((f) => `<img src="case/photos/${encodeURIComponent(f)}">`).join("")}</div>` : ""}
      <div class="cols"><div>${sec("Described as", cl.filter((c) => c.s === e.id && !c.o && ["HAS_ATTRIBUTE", "WORE", "IN_STATE", "HAD"].includes(c.p)))}
        ${sec("Family, work, associates", cl.filter(is("FAMILY_OF", "KNEW", "WORKED_AT", "MEMBER_OF", "OWNED", "LIVED_AT")))}
        ${sec("What this person said", cl.filter((c) => c.by === e.id || (c.s === e.id && ["SAID", "REPORTED", "DESCRIBED", "SAW", "HEARD"].includes(c.p))), "No statement by this person is in the file.")}</div>
      <div>${sec("Movements and sightings", cl.filter((c) => (c.s === e.id && ["LOCATED_AT", "TRAVELED_TO", "ENTERED", "LEFT", "FOUND_AT"].includes(c.p)) || (c.o === e.id && ["SAW", "FOUND"].includes(c.p))))}
        ${sec("Accusations and legal status", cl.filter((c) => (ACC.has(c.p) || ["CLEARED", "RELEASED"].includes(c.p))))}
        ${sec("Contact with investigators", cl.filter(is("INTERVIEWED", "CONTACTED", "SEARCHED")))}</div></div>
      </div>`;
  }
  window.__openDossier = (id) => { dossierId = id; aTab = "dossier"; window.__nav("analysis"); };

  // ---------- clicks ----------
  $("#page-analysis").addEventListener("click", (e) => {
    const q = (a) => e.target.closest(`[data-${a}]`)?.dataset[a], has = (a) => e.target.closest(`[data-${a}]`);
    if (q("atab")) { aTab = q("atab"); return renderAnalysis(); }
    if (has("toggle-dis")) { showDismissed = !showDismissed; return renderAnalysis(); }
    if (has("print")) { const p = e.target.closest(".page"); p.classList.add("printing"); window.print(); return p.classList.remove("printing"); }
    if (q("dismiss")) {
      const id = q("dismiss"); dismissed = dismissed.includes(id) ? dismissed.filter((x) => x !== id) : [...dismissed, id];
      try { localStorage.setItem("dismissed:" + B.case.id, JSON.stringify(dismissed)); } catch (err) { /* storage unavailable */ }
      return renderAnalysis();
    }
    if (q("claim")) { const c = D.C.get(q("claim")); window.__nav("investigate"); if (c.time) D.setTime((c.t0 + c.t1) / 2, true); return D.select({ type: "claim", id: c.id }); }
    if (q("ent")) { window.__nav("investigate"); return D.focusEntity(q("ent")); }
  });

  // a "Dossier" shortcut on top of the inspector when a person is selected
  window.__cwBar = (sel) => (sel.type === "entity" && E.get(sel.id).type === "PERSON" ? `<div class="cwbar"><button data-dossier-open="${sel.id}">Open dossier</button></div>` : "");
  $("#inspector").addEventListener("click", (e) => { const id = e.target.dataset?.dossierOpen; if (id) { e.stopPropagation(); window.__openDossier(id); } }, true);

  window.__renderAnalysis = renderAnalysis;
  window.__analysis = { comparisons, corroboration, leads, path };
  if ($("#page-analysis").classList.contains("on")) renderAnalysis();
});
