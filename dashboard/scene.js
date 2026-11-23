/* 3D scene view: a Gaussian splat with pins that tie case entities to points in the room, the
   image pipeline's source viewpoints, and its text query. One instance, moved between pages. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { SparkRenderer, SplatMesh } from "./vendor/spark.module.min.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let host, renderer, camera, controls, scene3, splat, meta, views = [], extent = 1, hooks = {};
let pins = [], placing = null, viewIdx = -1, fly = null, base = "";
const raycaster = new THREE.Raycaster();

// camera_poses.json: camera-to-world, gsplat.js convention (+Z forward). three.js looks down -Z:
// R_three = R_gsplat * diag(-1, 1, -1)  (INTEGRATION.md section 5.2)
function viewPose(v) {
  const m = v.rotation_matrix_row_major;
  const R = new THREE.Matrix4().set(-m[0], m[1], -m[2], 0, -m[3], m[4], -m[5], 0, -m[6], m[7], -m[8], 0, 0, 0, 0, 1);
  return { p: new THREE.Vector3(...v.position), q: new THREE.Quaternion().setFromRotationMatrix(R) };
}

async function open(sceneMeta, h) {
  hooks = h; host = document.querySelector("#scene");
  if (meta?.id === sceneMeta.id) { resize(); return; }
  if (renderer) { renderer.setAnimationLoop(null); splat?.dispose?.(); renderer.dispose(); splat = null; views = []; viewIdx = -1; }
  meta = sceneMeta; base = `case/scenes/${encodeURIComponent(meta.id)}/`;
  host.innerHTML = `<canvas></canvas><div id="pins"></div>
    <div id="scene-bar"><b>${esc(meta.title)}</b>
      <span class="${/demo purposes/.test(meta.location) ? "demo-tag" : "pill"}" title="${esc(meta.note)}">${/demo purposes/.test(meta.location) ? "stands for" : "shows"} ${esc(meta.location)}</span>
      <span class="meta">${esc(meta.units)}${meta.units === "unitless" ? " · no measurements" : ""}</span><span class="spacer"></span>
      <input id="sq" placeholder="Find in scene: blood spatter, shoe…" list="sq-list"><datalist id="sq-list">${(meta.queries || []).map((q) => `<option value="${esc(q.query)}">`).join("")}</datalist>
      <button id="sq-go">Search</button><button id="sv-reset">reset view</button></div>
    <div id="scene-result" class="hidden"></div>
    <div id="scene-views"></div><div id="scene-msg">Loading splat (${(meta.splat_bytes / 1e6).toFixed(0)} MB)…</div>`;
  const canvas = host.querySelector("canvas");
  renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  scene3 = new THREE.Scene(); scene3.background = new THREE.Color(0x101216);
  camera = new THREE.PerspectiveCamera(60, 1, 0.01, 500);
  camera.up.set(meta.up === "x" ? 1 : 0, meta.up === "y" || !meta.up ? 1 : 0, meta.up === "z" ? 1 : 0);
  scene3.add(new SparkRenderer({ renderer }));
  controls = new OrbitControls(camera, canvas); controls.enableDamping = true;
  controls.addEventListener("start", () => { fly = null; });

  if (meta.views) views = (await (await fetch(base + meta.views)).json()).cameras || [];
  const centres = views.map((v) => new THREE.Vector3(...v.position));
  if (centres.length) extent = Math.max(new THREE.Box3().setFromPoints(centres).getSize(new THREE.Vector3()).length(), 0.5);
  const vb = host.querySelector("#scene-views");
  vb.innerHTML = `<span class="meta" style="white-space:nowrap">source viewpoints (${views.length}):</span>` + views.map((v, i) => (i % Math.ceil(views.length / 40) ? "" : `<button data-i="${i}">${esc(v.t != null ? v.t.toFixed(1) + " s" : v.image.replace(/\.\w+$/, ""))}</button>`)).join("");
  vb.onclick = (e) => { const i = e.target.dataset?.i; if (i != null) snap(+i); };

  splat = new SplatMesh({ url: base + meta.splat, raycastable: true });
  scene3.add(splat);
  resetView(); resize();
  renderer.setAnimationLoop(loop);
  canvas.addEventListener("click", onClick);
  host.querySelector("#sv-reset").onclick = resetView;
  host.querySelector("#sq-go").onclick = () => query(host.querySelector("#sq").value);
  host.querySelector("#sq").onkeydown = (e) => { if (e.key === "Enter") query(e.target.value); e.stopPropagation(); };
  new ResizeObserver(resize).observe(host);
  setPins(meta.anchors || []);
  try { await splat.initialized; msg(""); } catch (e) { msg("Could not load the splat: " + e.message); }
}
function msg(t) { const m = host.querySelector("#scene-msg"); m.textContent = t; m.classList.toggle("hidden", !t); }
function resize() {
  if (!renderer) return;
  const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}
function resetView() { if (views.length) snap(0, true); else { camera.position.set(0, -3, 1.5); controls.target.set(0, 0, 0); } }
// stand exactly where a source photograph was taken, so the render can be compared with that photo
function snap(i, quiet) {
  if (!views.length) return;
  viewIdx = ((i % views.length) + views.length) % views.length;
  const v = views[viewIdx], { p, q } = viewPose(v);
  fly = null; camera.position.copy(p); camera.quaternion.copy(q);
  camera.fov = v.fov_y_deg || 60; camera.updateProjectionMatrix();   // match the source frame's field of view
  controls.target.copy(p).addScaledVector(new THREE.Vector3(0, 0, -1).applyQuaternion(q), extent * 0.35);
  host.querySelectorAll("#scene-views button").forEach((b) => b.classList.toggle("on", +b.dataset.i === viewIdx));
  if (!quiet) showView(v.image);
}
function labelsFor(image) { return meta.label_data?.images?.find((x) => x.filename === image); }
function showView(image) {
  const L = labelsFor(image), box = host.querySelector("#scene-result");
  const photo = (meta.photos || []).includes(image) ? `<img src="${base}photos/${encodeURIComponent(image)}" data-cap="${esc(image)}">` : `<div class="meta">The source photograph is not in this scene folder. Add the photos in “Scene from photos” to compare.</div>`;
  box.innerHTML = `<b>Viewpoint of ${esc(image)}</b>${photo}
    ${L ? `<div class="meta">SAM regions in this photo: ${L.region_count}. Top CLIP labels:</div>` + L.top_labels.map((t) => `<div class="r" data-q="${esc(t.label)}">${esc(t.label)} <span class="meta">similarity ${t.similarity.toFixed(4)}</span></div>`).join("") : ""}
    <div class="btns"><button data-close>Close</button></div>`;
  box.classList.remove("hidden"); wireResult(box);
}
function wireResult(box) {
  box.onclick = (e) => {
    if (e.target.dataset.close != null) return box.classList.add("hidden");
    if (e.target.tagName === "IMG") return hooks.lightbox?.(e.target.src, e.target.dataset.cap || "");
    const r = e.target.closest(".r"); if (!r) return;
    if (r.dataset.q) return query(r.dataset.q);
    if (r.dataset.view) { const i = views.findIndex((v) => v.image === r.dataset.view); if (i >= 0) snap(i, true); box.querySelectorAll(".r").forEach((x) => x.classList.toggle("on", x === r)); }
  };
}
// text query: the image pipeline's SAM + CLIP matcher (live when its index is present, else its stored results)
async function query(text) {
  if (!text.trim()) return;
  host.querySelector("#sq").value = text;
  const box = host.querySelector("#scene-result"); box.classList.remove("hidden"); box.innerHTML = "Searching…";
  const res = await (await fetch(`api/scene_query?scene=${encodeURIComponent(meta.id)}&text=${encodeURIComponent(text)}`)).json();
  const top = res.results?.[0];
  box.innerHTML = `<b>“${esc(text)}”</b> <span class="pill ${res.mode === "live CLIP" ? "done" : "wait"}">${esc(res.mode || "")}</span>
    ${res.mode_reason ? `<div class="meta">Stored results only: ${esc(res.mode_reason)}.</div>` : ""}
    ${!res.matched ? `<div class="msg err">${esc(res.message || res.error || "No match.")}</div>` : ""}
    ${top?.render ? `<img src="${base}${esc(top.render)}" data-cap="Pipeline render for “${esc(top.matched_query)}”">` : ""}
    ${top?.verdict ? `<div class="msg ${top.ok ? "good" : "err"}">Checked by hand in the pipeline's notes: ${esc(top.verdict)}</div>` : ""}
    ${(res.results || []).map((r, i) => `<div class="r${i ? "" : " on"}" data-view="${esc(r.viewpoint_id || "")}"><b>${esc(r.image)}</b> <span class="meta">similarity ${r.similarity.toFixed(4)}${r.sift_support != null ? " · " + r.sift_support + " SIFT points" : ""}${r.localized ? " · go to viewpoint" : " · not localised in 3D"}</span></div>`).join("")}
    ${res.caveat ? `<div class="meta" style="margin-top:8px">${esc(res.caveat)}</div>` : ""}
    <div class="btns"><button data-close>Close</button></div>`;
  wireResult(box);
  if (top?.viewpoint_id) { const i = views.findIndex((v) => v.image === top.viewpoint_id); if (i >= 0) snap(i, true); }
}
function onClick(ev) {
  if (!placing) return;
  const r = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
  const point = surfacePoint(raycaster);
  if (!point) return msg("No surface under the cursor there. Click on a reconstructed surface.");
  const done = placing; placing = null; host.classList.remove("placing"); msg("");
  hooks.onPlace?.(meta.id, done, point.toArray());
}
// The first Gaussian a ray meets is often a faint floater in front of the surface. The surface is
// where the hits along the ray are densest, so take the middle of the densest depth window.
function surfacePoint(rc) {
  const d = rc.intersectObject(splat, false).map((h) => h.distance).sort((a, b) => a - b);
  if (!d.length) return null;
  const win = extent * 0.04; let best = 0, bi = 0, j = 0;
  for (let i = 0; i < d.length; i++) { while (d[j] < d[i] - win) j++; if (i - j + 1 > best) { best = i - j + 1; bi = i; } }
  const dist = d[bi - Math.floor(best / 2)];
  return rc.ray.at(dist, new THREE.Vector3());
}
function probe(nx, ny) {     // debugging aid: hit distances for a normalised screen position
  raycaster.setFromCamera(new THREE.Vector2(nx, ny), camera);
  const d = raycaster.intersectObject(splat, false).map((h) => +h.distance.toFixed(3));
  return { n: d.length, first: d.slice(0, 6), last: d.slice(-3), picked: surfacePoint(raycaster)?.toArray().map((v) => +v.toFixed(3)), extent };
}
function startPlacing(entity) { placing = entity; host.classList.add("placing"); msg(`Click the surface where “${entity.name}” is. Esc cancels.`); }
function cancelPlacing() { if (placing) { placing = null; host.classList.remove("placing"); msg(""); } }

function setPins(anchors) {
  meta.anchors = anchors;
  const box = host.querySelector("#pins"); box.innerHTML = "";
  pins = anchors.map((a) => {
    const ent = hooks.resolve?.(a.entity);
    const el = document.createElement("div");
    el.className = "pin" + (a.demo || ent?.demo ? " demo" : ""); el.innerHTML = `<i></i><span>${esc(ent?.name || a.entity)}</span>`;
    el.title = `${a.method}${a.placed_by ? " by " + a.placed_by : ""} · ${a.at}`;
    el.onclick = (e) => { e.stopPropagation(); ent && hooks.onPick?.(ent.id); };
    box.appendChild(el);
    return { a, ent, el, v: new THREE.Vector3(...a.xyz) };
  });
  paint();
}
let active = new Set(), selected = null;
function setActive(ids, sel) { active = ids; selected = sel; paint(); }
function paint() { pins.forEach((p) => { p.el.classList.toggle("on", !!p.ent && active.has(p.ent.id)); p.el.classList.toggle("sel", !!p.ent && p.ent.id === selected); }); }
function flyTo(entityId) {
  const p = pins.find((x) => x.ent?.id === entityId); if (!p) return false;
  const dir = camera.position.clone().sub(controls.target).normalize();
  fly = { target: p.v.clone(), pos: p.v.clone().addScaledVector(dir, extent * 0.3), t: 0 };
  return true;
}
function loop() {
  if (fly) {
    fly.t = Math.min(1, fly.t + 0.04);
    controls.target.lerp(fly.target, 0.12); camera.position.lerp(fly.pos, 0.12);
    if (fly.t >= 1) fly = null;
  }
  controls.update(); renderer.render(scene3, camera);
  const w = host.clientWidth, h = host.clientHeight, v = new THREE.Vector3();
  for (const p of pins) {
    v.copy(p.v).project(camera);
    const show = v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05;
    p.el.style.display = show ? "" : "none";
    if (show) p.el.style.transform = `translate(${(v.x * 0.5 + 0.5) * w}px, ${(-v.y * 0.5 + 0.5) * h}px)`;
  }
}
window.SceneView = { open, setPins, setActive, flyTo, startPlacing, cancelPlacing, snap, query, resize,
  get meta() { return meta; }, get ready() { return !!splat; }, probe, debug: () => ({ camera, controls, views, splat }) };
window.dispatchEvent(new Event("sceneview-ready"));
