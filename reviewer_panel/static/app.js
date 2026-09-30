"use strict";
// MINARET reviewer panel -- single-page UI over the local JSON API (server.py).

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (t) => { t = Math.max(0, Number(t) || 0); const m = Math.floor(t / 60); return `${m}:${(t - m * 60).toFixed(1).padStart(4, "0")}`; };

const TYPES = ["ayat", "hadith", "dua", "topics", "headings"];
const TYPE_LABEL = { ayat: "Ayah", hadith: "Hadith", dua: "Dua", topics: "Topic", headings: "Heading" };
const USAGES = ["quotation", "translation", "explicit paraphrase"];
const EXTENTS = ["complete", "partial"];

const SPANNING = new Set(["topics", "headings"]);  // entities with a start-end span over many segments
const PAGE = 60;  // segments per page: long lectures have 1,500+ segments
const app = { status: null, recordings: [], key: null, payload: null, open: {}, lastAnchor: null, playUntil: null, page: 0, sel: null, selEnt: null, span: null, keepSel: false };

// Topic and heading fields come in English and Urdu; show the lecture's language first.
const lang = () => (app.payload?.language === "en" ? "en" : app.payload?.language === "ur" ? "ur" : "en");
const other = () => (lang() === "en" ? "ur" : "en");
const pick = (f, base) => f[`${base}_${lang()}`] || f[`${base}_${other()}`] || f[base] || "";

// ------------------------------------------------------------------ API
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) { const err = new Error(data.error || `HTTP ${res.status}`); err.kind = data.kind; throw err; }
  return data;
}
function toast(msg, bad = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : "");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.add("hidden"), bad ? 7000 : 3000);
}
async function guarded(fn) { try { return await fn(); } catch (e) { toast(e.message, true); } }

// ------------------------------------------------------------------ environment
async function loadStatus() {
  app.status = await api("/api/status");
  const s = app.status, pills = [];
  for (const [stage, v] of Object.entries(s.llm)) pills.push(`<span class="pill ${v.reachable ? (v.warning ? "no" : "ok") : "no"}" title="${esc(v.message)}">LLM ${stage.replace("_", " ")}</span>`);
  const corp = Object.values(s.corpora).filter(Boolean).length;
  pills.push(`<span class="pill ${corp === 5 ? "ok" : "no"}" title="${esc(Object.entries(s.corpora).map(([k, v]) => `${k}: ${v ? "present" : "missing"}`).join("\n"))}">corpora ${corp}/5</span>`);
  $("#env").innerHTML = pills.join("") + `<button class="ghost small" id="btn-env" title="Re-check">↻</button>`;
  $("#btn-env").onclick = () => guarded(loadStatus);
  $("#runs-dir").textContent = s.runs_dir;
}

async function loadRecordings() {
  app.recordings = await api("/api/recordings");
  const sel = $("#rec-select"); const prev = sel.value;
  const groups = {};
  for (const r of app.recordings) (groups[`${r.source} / ${r.series}`] ||= []).push(r);
  sel.innerHTML = Object.entries(groups).map(([g, rs]) => `<optgroup label="${esc(g)}">${rs.map((r) =>
    `<option value="${esc(`${r.source}|${r.series}|${r.recording}`)}" ${r.reviewable ? "" : "disabled"}>${esc(r.recording)} — ${r.files.join(" ")}</option>`).join("")}</optgroup>`).join("");
  if (prev) sel.value = prev;
}
const selectedKey = () => { const [source, series, recording] = ($("#rec-select").value || "").split("|"); return source ? { source, series, recording } : null; };

// ------------------------------------------------------------------ session
async function openSession(reset = false) {
  const key = selectedKey(); if (!key) return;
  if (reset && !confirm("Discard this review and start again from V2/E1?")) return;
  app.key = key; app.open = {}; app.page = 0; app.lastAnchor = null; app.sel = null; app.selEnt = null; app.span = null;
  setPayload(await api("/api/session/open", { ...key, reset }));
  const rec = app.recordings.find((r) => r.source === key.source && r.series === key.series && r.recording === key.recording);
  $("#replay-controls").classList.toggle("hidden", !rec?.has_reference);
  const a = app.payload.audio, audio = $("#audio");
  if (a.kind !== "none") { audio.src = a.url; $("#audio-note").textContent = a.kind === "url" ? "streaming from the publisher's URL" : "local file"; }
  else { audio.removeAttribute("src"); $("#audio-note").textContent = "no audio source recorded for this recording"; }
}
async function act(action, role = "first_level") {
  const payload = await api("/api/session/action", { ...app.key, action, role });
  setPayload(payload); return payload.result;
}
function setPayload(p) {
  app.payload = p;
  $("#empty-review").classList.toggle("hidden", true);
  $("#review").classList.remove("hidden");
  render(); renderSuper();
}

// ------------------------------------------------------------------ helpers over state
const segs = () => app.payload.state.segments;
const ents = () => app.payload.state.entities;
const flagsFor = (kind, uid) => app.payload.state.flags.filter((f) => f.target.kind === kind && f.target.uid === uid);
function anchorIndex(t) {  // index of the segment in which time t starts
  const s = segs(); let lo = 0, hi = s.length - 1, idx = 0;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (s[mid].data.start <= t + 1e-6) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
  return idx;
}
// Ayat, hadith and dua attach to the segment they start in; headings mark the segment they start in
// (drawn as a section divider); topics and headings are shown on every segment their span covers.
function attachEntities() {
  const s = segs(), map = new Map(s.map((x) => [x.uid, []])), heads = new Map();
  for (const e of [...ents()].sort((a, b) => a.order - b.order)) {
    const uid = s[anchorIndex(Number(e.fields.start) || 0)]?.uid;
    if (!uid) continue;
    if (e.type === "headings") (heads.get(uid) || heads.set(uid, []).get(uid)).push(e);
    else if (!SPANNING.has(e.type)) map.get(uid).push(e);
  }
  map.heads = heads;
  return map;
}
const spanOf = (e) => [Number(e.fields.start) || 0, Number(e.fields.end ?? e.fields.start) || 0];
function covers(e, seg) {
  const [a, b] = spanOf(e), lo = Math.min(seg.data.start, seg.data.end), hi = Math.max(seg.data.start, seg.data.end);
  return a < hi && b > lo || (a === b && a >= lo && a <= hi);
}
const covering = (seg) => ents().filter((e) => SPANNING.has(e.type) && covers(e, seg))
  .sort((x, y) => (x.type === y.type ? spanOf(x)[0] - spanOf(y)[0] : x.type === "headings" ? -1 : 1));
function entLabel(e) {
  const f = e.fields;
  if (e.type === "ayat") return `${f.surah_number ?? "?"}:${f.ayah_number ?? "?"}`;
  if (e.type === "hadith" || e.type === "dua") return f.reference || "(no reference)";
  if (e.type === "topics") return pick(f, "name") || "(unnamed topic)";
  return pick(f, "title") || "(untitled heading)";
}

// ------------------------------------------------------------------ render: review
function render() {
  const st = app.payload.state, map = attachEntities(), filter = $("#filter").value;
  const reviewed = st.segments.filter((s) => s.status !== "unreviewed").length;
  const pending = st.entities.filter((e) => e.status === "pending").length;
  const open = st.flags.filter((f) => f.status === "open").length, escl = st.flags.filter((f) => f.status === "escalated").length;
  $("#progress").innerHTML = `<b>${reviewed}</b>/${st.segments.length} segments reviewed · <b>${pending}</b> entities pending · <b>${open}</b> open flags · <b>${escl}</b> escalated`;
  $("#escalated-count").textContent = escl || "";
  const fin = st.finalized;
  $("#btn-finalize").classList.toggle("hidden", !!fin); $("#btn-reopen").classList.toggle("hidden", !fin);
  $("#blockers").textContent = fin ? "" : (app.payload.blockers.length ? `${app.payload.blockers.length} item(s) block finalizing` : "ready to finalize");
  const fbox = $("#finalized");
  fbox.classList.toggle("hidden", !fin); fbox.className = "notice" + (fin ? "" : " hidden");
  if (fin) fbox.innerHTML = `Finalized. V3 → <code>${esc(fin.v3)}</code><br>E2 → <code>${esc(fin.e2)}</code>`;
  renderReplay();

  const visible = [];
  st.segments.forEach((s, i) => {
    const es = map.get(s.uid) || [], fl = flagsFor("segment", s.uid), hs = map.heads.get(s.uid) || [];
    const entFlags = [...es, ...hs].flatMap((e) => flagsFor("entity", e.uid));
    if (filter === "unreviewed" && s.status !== "unreviewed" && ![...es, ...hs].some((e) => e.status === "pending")) return;
    if (filter === "entities" && !es.length && !hs.length) return;
    if (filter === "flags" && !fl.length && !entFlags.length) return;
    visible.push([s, i, es, fl]);
  });
  const pages = Math.max(1, Math.ceil(visible.length / PAGE));
  if (app.lastAnchor != null) {  // follow the replay: show the page holding the last action
    let at = 0;
    visible.forEach(([s], n) => { if (s.data.start <= app.lastAnchor + 1e-6) at = n; });
    app.page = Math.floor(at / PAGE);
  }
  app.page = Math.min(Math.max(0, app.page), pages - 1);
  const slice = visible.slice(app.page * PAGE, (app.page + 1) * PAGE);
  $("#pager").innerHTML = visible.length > PAGE ? `<button class="small ghost" data-page="-1" ${app.page ? "" : "disabled"}>‹</button>
    <span class="muted">${app.page * PAGE + 1}–${app.page * PAGE + slice.length} of ${visible.length}</span>
    <button class="small ghost" data-page="1" ${app.page < pages - 1 ? "" : "disabled"}>›</button>` : "";
  const spanEnt = app.span && ents().find((e) => e.uid === app.span);
  if (app.span && !spanEnt) app.span = null;
  $("#span-note").innerHTML = spanEnt ? `Showing the span of <b dir="auto">${esc(entLabel(spanEnt))}</b>
    (${fmt(spanOf(spanEnt)[0])}–${fmt(spanOf(spanEnt)[1])}, ${segs().filter((x) => covers(spanEnt, x)).length} segments)
    <button class="small ghost" data-a="span-clear">✕</button>` : "";
  let html = "";
  if (slice.length) {  // the page starts inside a section whose heading is on an earlier page
    const first = slice[0][0], own = map.heads.get(first.uid) || [];
    const cont = ents().filter((e) => e.type === "headings" && covers(e, first) && !own.includes(e) && spanOf(e)[0] < first.data.start);
    html += cont.map((h) => headingHTML(h, true)).join("");
  }
  for (const r of slice) html += (map.heads.get(r[0].uid) || []).map((h) => headingHTML(h)).join("") + rowHTML(...r, spanEnt);
  $("#rows").innerHTML = html || `<div class="empty">Nothing matches this filter.</div>`;
  if (app.lastAnchor != null) highlightAnchor(app.lastAnchor);
  renderSide(map);
}
function placeSide() {  // keep the entity panel just below the sticky audio/status bar
  const top = $(".topbar").offsetHeight + $("#review .sticky").offsetHeight + 8;
  document.documentElement.style.setProperty("--side-top", `${top}px`);
}
window.addEventListener("resize", () => { if (app.payload) placeSide(); });
function renderSide(map = attachEntities()) {
  placeSide();
  const box = $("#side"), fin = app.payload.state.finalized;
  const se = app.selEnt && ents().find((e) => e.uid === app.selEnt);
  if (se) {  // a heading picked from its section divider
    const s = segs()[anchorIndex(spanOf(se)[0])];
    box.innerHTML = `<div class="side-head"><b>${TYPE_LABEL[se.type]}</b>
        <span class="muted">${fmt(spanOf(se)[0])} – ${fmt(spanOf(se)[1])} · ${segs().filter((x) => covers(se, x)).length} segments</span></div>
      ${entHTML(se, s)}`;
    return;
  }
  app.selEnt = null;
  const i = segs().findIndex((x) => x.uid === app.sel);
  if (i < 0) { app.sel = null; box.innerHTML = `<div class="side-empty">Click a segment to see and review its entities, or a section heading to review the heading.</div>`; return; }
  const s = segs()[i], es = map.get(s.uid) || [], cov = covering(s);
  box.innerHTML = `<div class="side-head"><b>Segment ${i + 1}</b>
      <span class="time" data-play="${s.data.start}" data-end="${s.data.end}">▶ ${fmt(s.data.start)} – ${fmt(s.data.end)}</span></div>
    <div class="side-group">Starts here <span class="muted">(${es.length})</span></div>
    ${es.map((e) => entHTML(e, s)).join("") || `<div class="muted">No ayah, hadith or dua starts in this segment.</div>`}
    ${app.open[s.uid]?.kind === "ent-new" ? `<div class="ent">${entFormHTML(null, s)}</div>`
      : fin ? "" : `<div class="actions"><button class="small ghost" data-a="ent-new" data-uid="${s.uid}">+ Entity</button></div>`}
    <div class="side-group">Covering this segment <span class="muted">(${cov.length} topic/heading)</span></div>
    ${cov.map((e) => entHTML(e, s)).join("") || `<div class="muted">No topic or heading spans this segment.</div>`}`;
}
function select(uid) {
  app.sel = uid; app.selEnt = null;
  $$(".seg.selected, .heading-bar.selected").forEach((x) => x.classList.remove("selected"));
  $(`#seg-${uid}`)?.classList.add("selected");
  renderSide();
}
function selectEnt(uid) {
  app.selEnt = uid; app.sel = null;
  $$(".seg.selected, .heading-bar.selected").forEach((x) => x.classList.remove("selected"));
  $$(`[data-select-ent="${uid}"]`).forEach((x) => x.classList.add("selected"));
  renderSide();
}
function goToTime(t, pickSegment = true) {  // show the page containing time t (used when jumping from elsewhere)
  app.lastAnchor = t; app.keepSel = !pickSegment; render(); app.lastAnchor = null; app.keepSel = false;
}
function headingHTML(h, continued = false) {
  const [a, b] = spanOf(h), f = h.fields, second = f[`title_${other()}`];
  return `<div class="heading-bar ${h.status}${app.selEnt === h.uid ? " selected" : ""}" data-select-ent="${h.uid}">
    <span class="etype" style="color:var(--f-headings)">${continued ? "Heading (continued)" : "Heading"}</span>
    <span class="htitle" dir="auto">${esc(entLabel(h))}</span>${second ? `<span class="muted" dir="auto">${esc(second)}</span>` : ""}
    <span class="time" data-play="${a}" data-end="${b}">▶ ${fmt(a)} – ${fmt(b)}</span><span class="badge ${h.status}">${h.status}</span></div>`;
}
function rowHTML(s, i, es, fl, spanEnt) {
  const d = s.data, uid = s.uid, editing = app.open[uid];
  const inverted = d.end < d.start ? ` <span class="badge open" title="end precedes start">timestamps inverted</span>` : "";
  const segActions = app.payload.state.finalized ? "" : `<div class="actions">
      <button class="small" data-a="seg-accept" data-uid="${uid}">Accept</button>
      <button class="small ghost" data-a="seg-edit" data-uid="${uid}">Correct</button>
      <button class="small ghost" data-a="flag-form" data-kind="segment" data-uid="${uid}">Flag</button>
      <button class="small ghost" data-a="seg-merge" data-uid="${uid}" data-i="${i}" title="Merge with the next segment">Merge ↓</button>
      <button class="small ghost" data-a="seg-insert" data-uid="${uid}" title="Insert a segment after this one">Insert ↓</button>
      <button class="small ghost" data-a="seg-delete" data-uid="${uid}">Remove</button>
    </div>`;
  const counts = {};
  for (const e of es) counts[e.type] = (counts[e.type] || 0) + 1;
  const pending = es.some((e) => e.status === "pending");
  const chips = TYPES.filter((t) => counts[t]).map((t) =>
    `<span class="chip" style="--c:var(--f-${t})">${counts[t]} ${TYPE_LABEL[t].toLowerCase()}</span>`).join("");
  const segEditing = editing && editing.kind !== "ent-new";
  return `<div class="seg-row" data-row="${uid}" data-start="${d.start}">
    <div class="seg${app.sel === uid ? " selected" : ""}${spanEnt && covers(spanEnt, s) ? " in-span" : ""}" id="seg-${uid}" data-select="${uid}">
      <div class="seg-head"><span class="time" data-play="${d.start}" data-end="${d.end}">▶ ${fmt(d.start)} – ${fmt(d.end)}</span>
        <span class="badge ${s.status}">${s.status}</span>${inverted}
        ${chips ? `<span class="chips${pending ? " pending" : ""}" title="${pending ? "Entities awaiting review" : "Entities"}">${chips}</span>` : ""}</div>
      ${editing?.kind === "seg" ? segEditHTML(s) : `<div class="text" dir="auto">${esc(d.text)}</div>`}
      ${editing?.kind === "flag" ? flagFormHTML("segment", uid) : ""}
      ${fl.map(flagHTML).join("")}
      ${segEditing ? "" : segActions}
    </div>
  </div>`;
}
function segEditHTML(s) {
  const d = s.data, sug = app.open[s.uid]?.suggestion;
  return `<div class="form">
    <textarea rows="3" dir="auto" data-f="text">${esc(d.text)}</textarea>
    <div class="row"><label>Start (s)<input data-f="start" type="number" step="0.01" value="${d.start}"></label>
      <label>End (s)<input data-f="end" type="number" step="0.01" value="${d.end}"></label></div>
    ${sug ? `<div class="canon"><b>AI suggestion</b> (review before using)<div dir="auto">${esc(sug.suggestion)}</div>
      ${sug.fallback ? `<div class="muted">The model's output failed the correction checks; this is the original text. ${esc(sug.note)}</div>` : ""}
      <div class="actions"><button class="small" data-a="sug-use" data-uid="${s.uid}">Use suggestion</button>
      <button class="small ghost" data-a="sug-drop" data-uid="${s.uid}">Dismiss</button></div></div>` : ""}
    <div class="actions"><button class="small" data-a="seg-save" data-uid="${s.uid}">Save</button>
      <button class="small ghost" data-a="seg-split" data-uid="${s.uid}" title="Split at the text cursor">Split at cursor</button>
      <button class="small ghost" data-a="seg-ai" data-uid="${s.uid}">AI suggestion</button>
      <button class="small ghost" data-a="close" data-uid="${s.uid}">Cancel</button></div></div>`;
}
function entHTML(e, s) {
  const f = e.fields, open = app.open[e.uid], fl = flagsFor("entity", e.uid), fin = app.payload.state.finalized;
  const meta = [f.usage, f.extent].filter(Boolean).join(" · ");
  const val = e.fields.validation || e.e1?.validation;
  const valTxt = val ? ` · corpus ${esc(val.verdict || "")}${val.score != null ? ` ${Number(val.score).toFixed(2)}` : ""}` : "";
  const second = e.type === "topics" ? f[`name_${other()}`] : e.type === "headings" ? f[`title_${other()}`] : "";
  const body = e.type === "topics" ? pick(f, "description") : e.type === "headings" ? "" : (f.text || "");
  return `<div class="ent t-${e.type} ${e.status}" id="ent-${e.uid}">
    <div class="ent-head"><span class="etype" style="color:var(--f-${e.type})">${TYPE_LABEL[e.type]}</span>
      <span class="ref">${esc(entLabel(e))}</span>
      <span class="time" data-play="${f.start ?? 0}" data-end="${f.end ?? f.start ?? 0}">▶ ${fmt(f.start)}${f.end != null ? `–${fmt(f.end)}` : ""}</span>
      <span class="badge ${e.status}">${e.status}</span></div>
    ${open?.kind === "ent" ? entFormHTML(e, s) : `${second ? `<div class="muted second" dir="auto">${esc(second)}</div>` : ""}${body ? `<div class="text" dir="auto">${esc(body)}</div>` : ""}
      ${meta || valTxt ? `<div class="muted" style="font-size:12px">${esc(meta)}${valTxt}</div>` : ""}`}
    ${open?.canon ? canonHTML(open.canon) : ""}
    ${open?.kind === "flag" ? flagFormHTML("entity", e.uid) : ""}
    ${fl.map(flagHTML).join("")}
    ${fin || open?.kind ? "" : `<div class="actions">
      <button class="small" data-a="ent-accept" data-uid="${e.uid}">Accept</button>
      <button class="small ghost" data-a="ent-edit" data-uid="${e.uid}">Correct</button>
      <button class="small ghost" data-a="ent-reject" data-uid="${e.uid}">Reject</button>
      <button class="small ghost" data-a="flag-form" data-kind="entity" data-uid="${e.uid}">Flag</button>
      ${["ayat", "dua", "hadith"].includes(e.type) ? `<button class="small ghost" data-a="ent-canon" data-uid="${e.uid}">Canonical</button>` : ""}
      ${SPANNING.has(e.type) ? `<button class="small ghost" data-a="ent-span" data-uid="${e.uid}">${app.span === e.uid ? "Hide span" : "Show span"}</button>` : ""}
      ${e.type === "topics" ? `<button class="small ghost" data-a="ent-lecture" data-uid="${e.uid}">Lecture-level</button>
        <button class="small ghost" data-a="ent-group" data-uid="${e.uid}" data-seg="${s.uid}" title="Tie to this segment's span">Segment group</button>` : ""}
    </div>`}
  </div>`;
}
function canonHTML(c) {
  if (!c.found) return `<div class="canon muted">${esc(c.message || "No canonical entry found")}</div>`;
  return `<div class="canon">${c.text ? `<div dir="auto">${esc(c.text_indopak || c.text)}</div>` : ""}
    ${c.transliteration ? `<div class="muted">${esc(c.transliteration)}</div>` : ""}
    ${c.translation_en ? `<div>${esc(c.translation_en)}</div>` : ""}${c.translation_ur ? `<div dir="auto">${esc(c.translation_ur)}</div>` : ""}
    ${c.kg_id ? `<div class="muted">SemanticHadith ${esc(c.kg_id)}</div>` : ""}</div>`;
}
function fieldSpec(type, fields) {
  if (type === "ayat") return ["surah_number", "ayah_number", "text", "usage", "extent", "start", "end"];
  if (type === "hadith") return ["reference", "expanded_reference", "text", "usage", "start", "end"];
  if (type === "dua") return ["reference", "text", "usage", "extent", "start", "end"];
  const [a, b] = [lang(), other()];
  if (type === "topics") return (fields && "name" in fields && !("name_en" in fields)) ? ["name", "description", "start", "end"]
    : [`name_${a}`, `name_${b}`, `description_${a}`, `description_${b}`, "start", "end"];
  return [`title_${a}`, `title_${b}`, "start", "end"];
}
function entFormHTML(e, s) {
  const type = e ? e.type : (app.open[s.uid]?.type || "ayat");
  const f = e ? e.fields : { start: s.data.start, end: s.data.end, usage: "quotation", extent: "complete" };
  const input = (k) => {
    const v = f[k] ?? "";
    if (k === "usage") return `<label>usage<select data-f="usage">${USAGES.map((u) => `<option ${u === v ? "selected" : ""}>${u}</option>`).join("")}</select></label>`;
    if (k === "extent") return `<label>extent<select data-f="extent">${EXTENTS.map((u) => `<option ${u === v ? "selected" : ""}>${u}</option>`).join("")}</select></label>`;
    if (["text", "description", "description_en", "description_ur", "expanded_reference"].includes(k))
      return `<label style="flex-basis:100%">${k}<textarea rows="2" dir="auto" data-f="${k}">${esc(v)}</textarea></label>`;
    return `<label>${k}<input data-f="${k}" dir="auto" ${k === "start" || k === "end" ? 'type="number" step="0.01"' : ""} value="${esc(v)}"></label>`;
  };
  const owner = e ? e.uid : s.uid;
  return `<div class="form" data-form="${owner}">
    <div class="row"><label>type<select data-f="__type" data-a="type-change" data-uid="${owner}">${TYPES.map((t) => `<option value="${t}" ${t === type ? "selected" : ""}>${TYPE_LABEL[t]}</option>`).join("")}</select></label></div>
    <div class="row">${fieldSpec(type, f).map(input).join("")}</div>
    <div class="actions"><button class="small" data-a="${e ? "ent-save" : "ent-create"}" data-uid="${owner}">${e ? "Save" : "Add entity"}</button>
      <button class="small ghost" data-a="close" data-uid="${owner}">Cancel</button></div></div>`;
}
function flagFormHTML(kind, uid) {
  return `<div class="form" data-form="${uid}"><div class="row">
    <label>Issue<select data-f="issue">${app.status.flag_issues.map((x) => `<option>${esc(x)}</option>`).join("")}</select></label>
    <label class="grow">Note<input data-f="note" placeholder="What is wrong, where"></label></div>
    <div class="actions"><button class="small" data-a="flag-add" data-kind="${kind}" data-uid="${uid}">Add flag</button>
    <button class="small ghost" data-a="close" data-uid="${uid}">Cancel</button></div></div>`;
}
function flagHTML(f) {
  const res = f.resolution ? ` — resolved by ${f.resolution.role === "super" ? "super reviewer" : "reviewer"}${f.resolution.note ? `: ${esc(f.resolution.note)}` : ""}` : "";
  const canAct = !app.payload.state.finalized && f.status === "open";
  return `<div class="flag ${f.status}"><span class="badge ${f.status}">${f.status === "escalated" ? "need review" : f.status}</span>
    <b>${esc(f.issue)}</b>${f.span ? ` <span class="muted">[chars ${f.span[0]}–${f.span[1]}]</span>` : ""} ${esc(f.note)}${res}
    ${canAct ? `<div class="actions"><button class="small" data-a="flag-resolve" data-id="${f.id}">Resolved</button>
      <button class="small ghost" data-a="flag-escalate" data-id="${f.id}">Need Review</button></div>` : ""}
    ${f.status === "escalated" ? `<div class="muted">Waiting for the super reviewer.</div>` : ""}</div>`;
}

// ------------------------------------------------------------------ render: super review
function renderSuper() {
  if (!app.payload) { $("#super-list").innerHTML = `<div class="empty">Open a recording first.</div>`; return; }
  const st = app.payload.state, esc_ = st.flags.filter((f) => f.status === "escalated");
  const done = st.flags.filter((f) => f.status === "resolved" && f.resolution?.role === "super");
  if (!esc_.length && !done.length) { $("#super-list").innerHTML = `<div class="empty">No items have been escalated for this recording.</div>`; return; }
  const item = (f) => {
    let ctx = "";
    if (f.target.kind === "segment") {
      const s = st.segments.find((x) => x.uid === f.target.uid);
      ctx = s ? `<div class="seg"><div class="seg-head"><span class="time" data-play="${s.data.start}" data-end="${s.data.end}">▶ ${fmt(s.data.start)} – ${fmt(s.data.end)}</span></div>
        ${app.open["sup-" + s.uid] ? `<div class="form"><textarea rows="3" dir="auto" data-sup-text="${s.uid}">${esc(s.data.text)}</textarea>
          <div class="actions"><button class="small" data-a="sup-seg-save" data-uid="${s.uid}">Save wording</button></div></div>`
          : `<div class="text" dir="auto">${esc(s.data.text)}</div><div class="actions"><button class="small ghost" data-a="sup-seg-edit" data-uid="${s.uid}">Change wording</button></div>`}</div>` : "";
    } else {
      const e = st.entities.find((x) => x.uid === f.target.uid);
      const s = e && st.segments.find((x) => x.data.start <= (e.fields.start ?? 0)) || st.segments[0];
      ctx = e ? entHTML(e, s) : "";
    }
    const decided = f.status === "resolved";
    return `<div class="card"><div>${flagHTML(f)}</div>${f.escalation_note ? `<div class="muted">Escalation note: ${esc(f.escalation_note)}</div>` : ""}
      ${ctx}${decided ? "" : `<div class="form"><label>Final decision<input data-decision="${f.id}" placeholder="e.g. paraphrase, no reference; wording kept"></label>
      <div class="actions"><button class="small" data-a="super-resolve" data-id="${f.id}">Record final decision</button></div></div>`}</div>`;
  };
  $("#super-list").innerHTML = `<div class="grid2">${esc_.map(item).join("")}</div>` +
    (done.length ? `<h3>Decided</h3><div class="grid2">${done.map(item).join("")}</div>` : "");
}

// ------------------------------------------------------------------ replay
function renderReplay() {
  const r = app.payload.replay, on = !!r;
  ["#btn-step", "#btn-step10", "#btn-runall", "#btn-stop"].forEach((b) => $(b).classList.toggle("hidden", !on));
  $("#btn-replay").classList.toggle("hidden", on);
  $("#replay-progress").textContent = on ? `${r.next} / ${r.total} actions` : "";
  const up = $("#replay-upcoming");
  up.classList.toggle("hidden", !on);
  if (on) up.innerHTML = r.next >= r.total ? `<b>Replay complete.</b> Finalize to write V3/E2.`
    : `<b>Next:</b> ${r.upcoming.map(esc).join(" → ")}`;
}
async function replayStep(steps) {
  const p = await api("/api/replay/step", { ...app.key, steps });
  const last = p.applied[p.applied.length - 1];
  app.lastAnchor = last ? last.anchor : null;
  setPayload(p);
  if (last) toast(last.describe);
}
function highlightAnchor(t) {
  $$(".seg-row.hl").forEach((r) => r.classList.remove("hl"));
  const rows = $$(".seg-row"); let best = null;
  for (const r of rows) { if (Number(r.dataset.start) <= t + 1e-6) best = r; else break; }
  if (best) {
    best.classList.add("hl"); best.scrollIntoView({ block: "center" });
    if (!app.keepSel) { app.sel = best.dataset.row; app.selEnt = null; $(`#seg-${app.sel}`)?.classList.add("selected"); }
  }
}

// ------------------------------------------------------------------ audio
function play(start, end) {
  const a = $("#audio"); if (!a.src) { toast("No audio source for this recording", true); return; }
  a.currentTime = Math.max(0, start); app.playUntil = end > start ? end : null;
  a.play().catch((e) => toast(`Audio could not play: ${e.message}`, true));
}
$("#audio").addEventListener("timeupdate", () => {
  const a = $("#audio");
  if (app.playUntil != null && a.currentTime >= app.playUntil) { a.pause(); app.playUntil = null; }
  if (!app.payload) return;
  const t = a.currentTime, cur = segs().find((s) => s.data.start <= t && t < s.data.end);
  $$(".seg.playing").forEach((x) => x.classList.remove("playing"));
  if (cur) $(`#seg-${cur.uid}`)?.classList.add("playing");
});

// ------------------------------------------------------------------ event handling (delegated)
function readForm(uid) {
  const out = {};
  $$(`[data-form="${uid}"] [data-f]`).forEach((el) => { out[el.dataset.f] = el.value; });
  return out;
}
function entityFields(type, raw) {
  const f = {};
  for (const k of fieldSpec(type, raw)) {
    if (!(k in raw)) continue;
    f[k] = (k === "start" || k === "end") ? Number(raw[k]) : raw[k];
  }
  return f;
}
document.addEventListener("click", (ev) => {
  const pg = ev.target.closest("[data-page]");
  if (pg) { app.lastAnchor = null; app.page += Number(pg.dataset.page); render(); window.scrollTo(0, 0); return; }
  const playEl = ev.target.closest("[data-play]");
  if (playEl) { play(Number(playEl.dataset.play), Number(playEl.dataset.end)); return; }
  const btn = ev.target.closest("[data-a]");
  if (!btn) {
    const hEl = ev.target.closest("[data-select-ent]");
    if (hEl) { selectEnt(hEl.dataset.selectEnt); return; }
    const segEl = ev.target.closest("[data-select]");
    if (segEl && !ev.target.closest("textarea, input, select, .form")) select(segEl.dataset.select);
    return;
  }
  if (btn.tagName === "SELECT") return;
  const a = btn.dataset.a, uid = btn.dataset.uid, id = btn.dataset.id;
  guarded(async () => {
    switch (a) {
      case "seg-accept": await act({ op: "seg.accept", uid }); break;
      case "seg-edit": app.open[uid] = { kind: "seg" }; render(); break;
      case "close": delete app.open[uid]; render(); renderSuper(); break;
      case "seg-save": {
        const box = $(`#seg-${uid}`), text = $("[data-f=text]", box).value;
        const start = Number($("[data-f=start]", box).value), end = Number($("[data-f=end]", box).value);
        delete app.open[uid]; await act({ op: "seg.edit", uid, text, start, end }); break;
      }
      case "seg-split": {
        const ta = $(`#seg-${uid} [data-f=text]`); const at = ta.selectionStart;
        if (!at || at >= ta.value.length) { toast("Place the text cursor where the segment should split", true); return; }
        await act({ op: "seg.edit", uid, text: ta.value });
        delete app.open[uid]; await act({ op: "seg.split", uid, at }); break;
      }
      case "seg-ai": {
        const text = $(`#seg-${uid} [data-f=text]`).value; btn.disabled = true; btn.textContent = "Asking…";
        try { app.open[uid] = { kind: "seg", suggestion: await api("/api/ai/suggest", { text }) }; }
        finally { btn.disabled = false; }
        render(); break;
      }
      case "sug-use": { const s = app.open[uid].suggestion.suggestion; app.open[uid] = { kind: "seg" }; render(); $(`#seg-${uid} [data-f=text]`).value = s; break; }
      case "sug-drop": app.open[uid] = { kind: "seg" }; render(); break;
      case "seg-merge": {
        const i = Number(btn.dataset.i), next = segs()[i + 1];
        if (!next) { toast("No next segment to merge with", true); return; }
        await act({ op: "seg.merge", uids: [uid, next.uid] }); break;
      }
      case "seg-insert": {
        const s = segs().find((x) => x.uid === uid), i = segs().indexOf(s), nxt = segs()[i + 1];
        const r = await act({ op: "seg.insert", after_uid: uid, start: s.data.end, end: nxt ? nxt.data.start : s.data.end, text: "" });
        app.open[r.uid] = { kind: "seg" }; render(); $(`#seg-${r.uid}`)?.scrollIntoView({ block: "center" }); break;
      }
      case "seg-delete": if (confirm("Remove this segment?")) await act({ op: "seg.delete", uid }); break;
      case "ent-new": app.open[uid] = { kind: "ent-new", type: "ayat" }; render(); break;
      case "ent-create": {
        const raw = readForm(uid), type = raw.__type;
        delete app.open[uid]; await act({ op: "ent.add", type, fields: entityFields(type, raw) }); break;
      }
      case "ent-accept": await act({ op: "ent.accept", uid }); break;
      case "ent-reject": await act({ op: "ent.reject", uid }); break;
      case "ent-edit": app.open[uid] = { ...(app.open[uid] || {}), kind: "ent" }; render(); renderSuper(); break;
      case "ent-save": {
        const e = ents().find((x) => x.uid === uid), raw = readForm(uid), type = raw.__type;
        delete app.open[uid];
        if (type !== e.type) await act({ op: "ent.retype", uid, type });
        const role = $("#tab-super").classList.contains("active") ? "super" : "first_level";
        await act({ op: "ent.edit", uid, fields: entityFields(type, raw) }, role); break;
      }
      case "ent-canon": {
        const e = ents().find((x) => x.uid === uid); btn.disabled = true;
        const canon = await api("/api/lookup", { type: e.type, fields: e.fields });
        app.open[uid] = { ...(app.open[uid] || {}), canon }; render(); renderSuper(); break;
      }
      case "ent-span": {
        if (app.span === uid) { app.span = null; render(); break; }
        const e = ents().find((x) => x.uid === uid); app.span = uid;
        goToTime(spanOf(e)[0], false); break;
      }
      case "span-clear": app.span = null; render(); break;
      case "ent-lecture": await act({ op: "ent.scope", uid, scope: "lecture" }); break;
      case "ent-group": {
        const s = segs().find((x) => x.uid === btn.dataset.seg);
        await act({ op: "ent.scope", uid, scope: "segment", start: s.data.start, end: s.data.end }); break;
      }
      case "flag-form": app.open[uid] = { kind: "flag" }; render(); break;
      case "flag-add": {
        const raw = readForm(uid); let span = null;
        const ta = $(`#seg-${uid} [data-f=text]`);
        if (ta && ta.selectionEnd > ta.selectionStart) span = [ta.selectionStart, ta.selectionEnd];
        delete app.open[uid];
        await act({ op: "flag.add", target: { kind: btn.dataset.kind, uid }, issue: raw.issue, note: raw.note, span }); break;
      }
      case "flag-resolve": await act({ op: "flag.resolve", id, note: prompt("How was it resolved? (optional)") || "" }); break;
      case "flag-escalate": await act({ op: "flag.escalate", id, note: prompt("Note for the super reviewer (optional)") || "" }); break;
      case "super-resolve": {
        const note = $(`[data-decision="${id}"]`).value.trim();
        if (!note) { toast("Record the final decision first", true); return; }
        await act({ op: "flag.resolve", id, note }, "super"); break;
      }
      case "sup-seg-edit": app.open["sup-" + uid] = true; renderSuper(); break;
      case "sup-seg-save": {
        const text = $(`[data-sup-text="${uid}"]`).value; delete app.open["sup-" + uid];
        await act({ op: "seg.edit", uid, text }, "super"); break;
      }
    }
  });
});
document.addEventListener("change", (ev) => {
  const el = ev.target;
  if (el.dataset.a === "type-change") {
    const uid = el.dataset.uid;
    if (app.open[uid]?.kind === "ent-new") { app.open[uid].type = el.value; render(); }
    else {  // re-render the form with the new type's fields, keeping the current field values
      const e = ents().find((x) => x.uid === uid), cur = { ...e.fields, ...readForm(uid) };
      const box = $(`[data-form="${uid}"]`); const tmp = { ...e, type: el.value, fields: cur };
      box.outerHTML = entFormHTML(tmp, segs()[0]);
    }
  }
});

// ------------------------------------------------------------------ toolbar / tabs
$("#btn-open").onclick = () => guarded(() => openSession(false));
$("#btn-reset").onclick = () => guarded(() => openSession(true));
$("#filter").onchange = () => { app.page = 0; app.lastAnchor = null; if (app.payload) render(); };
$("#btn-finalize").onclick = () => guarded(async () => {
  const r = await api("/api/session/finalize", app.key);
  setPayload(r);
  if (!r.ok) { const box = $("#finalized"); box.className = "notice bad"; box.innerHTML = `<b>Cannot finalize yet:</b><br>${r.blockers.map(esc).join("<br>")}`; }
  else { toast("V3 and E2 written"); await loadRecordings(); }
});
$("#btn-reopen").onclick = () => guarded(async () => setPayload(await api("/api/session/reopen", app.key)));
$("#btn-replay").onclick = () => guarded(async () => {
  if (!confirm("Replay restarts this review from V2/E1 and reconstructs the actions that produced the released V3/E2. Continue?")) return;
  app.open = {}; app.lastAnchor = null; setPayload(await api("/api/replay/start", app.key));
});
$("#btn-step").onclick = () => guarded(() => replayStep(1));
$("#btn-step10").onclick = () => guarded(() => replayStep(10));
$("#btn-runall").onclick = () => guarded(() => replayStep(100000));
$("#btn-stop").onclick = () => guarded(async () => { app.lastAnchor = null; setPayload(await api("/api/replay/stop", app.key)); });
$("#audio").addEventListener("seeked", () => {  // keep the transcript page in step with manual seeking
  if (!app.payload || app.playUntil != null) return;
  const t = $("#audio").currentTime, first = $(".seg-row"), rows = $$(".seg-row");
  if (!rows.length) return;
  const lo = Number(first.dataset.start), hi = Number(rows[rows.length - 1].dataset.start);
  if (t < lo || t > hi + 60) goToTime(t);
});

function showTab(name) { const t = $(`.tab[data-tab="${name}"]`); if (t) t.click(); }
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
$$(".tab").forEach((t) => t.onclick = () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
  $$(".tabpanel").forEach((p) => p.classList.toggle("active", p.id === `tab-${t.dataset.tab}`));
  if (t.dataset.tab === "pipeline") { guarded(loadJobs); guarded(loadTargets); }
  if (t.dataset.tab === "ask") guarded(loadAsk);
  if (t.dataset.tab === "super") renderSuper();
  if (t.dataset.tab === "settings") guarded(loadSettings);
});

// ------------------------------------------------------------------ pipeline
$$("form[data-job]").forEach((form) => form.onsubmit = (ev) => {
  ev.preventDefault();
  const params = Object.fromEntries(new FormData(form).entries());
  if (params.target) { [params.series, params.recording] = params.target.split("|"); delete params.target; }
  guarded(async () => { const j = await api("/api/jobs", { kind: form.dataset.job, params }); toast(`${j.kind} started`); loadJobs(); });
});
// Correct, Extract, Build KG, Build RAG index: choose from what each stage can actually run on in runs/.
async function loadTargets() {
  const t = await api("/api/pipeline/targets"), kgSel = $("#kg-series"), ragSel = $("#rag-build-target");
  const recOptions = (sel, list, empty, doneNote) => {
    const prev = sel.value;
    sel.innerHTML = list.length ? list.map((r) => `<option value="${esc(`${r.series}|${r.recording}`)}">${esc(r.series)} / ${esc(r.recording)}${
      r.done ? ` (${doneNote})` : ""}</option>`).join("") : `<option value="">${empty}</option>`;
    if (list.some((r) => `${r.series}|${r.recording}` === prev)) sel.value = prev;
    sel.closest("form").querySelector("button").disabled = !list.length;
  };
  recOptions($("#correct-target"), t.correct, "No recording in runs/ has a V0 yet: run Transcribe first", "has a V1; running again replaces it");
  recOptions($("#extract-target"), t.extract, "No recording in runs/ has a V1 yet: run Correct first", "has E1/V2; running again replaces them");
  const prevKg = kgSel.value, prevRag = ragSel.value;
  const none = `<option value="">No finalized recording in runs/ yet: finalize a review first</option>`;
  kgSel.innerHTML = t.kg.length ? t.kg.map((k) => `<option value="${esc(k.series)}" ${k.build.length ? "" : "disabled"}>${esc(k.series)} (${
    k.build.length ? `${k.build.length} finalized recording${k.build.length === 1 ? "" : "s"}` : esc(k.reason)})</option>`).join("") : none;
  ragSel.innerHTML = t.rag.length ? t.rag.map((r) => `<option value="${esc(`${r.series}|${r.recording}`)}">${esc(r.series)} / ${esc(r.recording)}</option>`).join("") : none;
  if (prevKg && t.kg.some((k) => k.series === prevKg && k.build.length)) kgSel.value = prevKg;
  else { const first = t.kg.find((k) => k.build.length); if (first) kgSel.value = first.series; }
  if (prevRag && t.rag.some((r) => `${r.series}|${r.recording}` === prevRag)) ragSel.value = prevRag;
  app.kgTargets = t.kg; noteKg();
  $('form[data-job="kg"] button').disabled = !t.kg.some((k) => k.build.length);
  $('form[data-job="rag_index"] button').disabled = !t.rag.length;
}
function noteKg() {
  const k = app.kgTargets?.find((x) => x.series === $("#kg-series").value);
  $("#kg-series-note").innerHTML = !k || !k.build.length ? "Builds the series from its finalized recordings in runs/, using its series config."
    : `Builds <b>${k.build.map(esc).join(", ")}</b> with <code>${esc(k.config)}</code>.` +
      (k.not_in_config.length ? ` Not in the series config, so left out: ${k.not_in_config.map(esc).join(", ")}.` : "");
}
$("#kg-series").onchange = noteKg;
async function loadJobs() {
  const jobs = await api("/api/jobs");
  $("#jobs tbody").innerHTML = jobs.map((j) => `<tr><td>${esc(j.kind)}</td><td>${esc([j.params.series, j.params.recording].filter(Boolean).join(" / "))}</td>
    <td><span class="badge ${j.status === "completed" ? "accepted" : j.status === "failed" ? "rejected" : "open"}">${j.status}</span></td>
    <td>${esc(new Date(j.started).toLocaleTimeString())}</td><td>${esc(j.error || j.message)}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">No stages run yet.</td></tr>`;
  clearTimeout(loadJobs.t);
  if (jobs.some((j) => j.status === "running")) loadJobs.t = setTimeout(() => guarded(loadJobs), 3000);
  else if (jobs.length) { guarded(loadRecordings); guarded(loadTargets); }
}

// ------------------------------------------------------------------ ask
async function loadAsk() {
  app.rag = await api("/api/rag/targets");
  const idx = $("#rag-index"), prev = idx.value;
  idx.innerHTML = Object.keys(app.rag).map((k) => `<option>${k}</option>`).join("");
  if (prev && app.rag[prev]) idx.value = prev;
  fillRagTargets();
  const kg = await api("/api/kg/info");
  $("#kg-graph").innerHTML = kg.graphs.map((g) => `<option>${g}</option>`).join("") || `<option value="">no graph built yet</option>`;
  $("#kg-cq").innerHTML = `<option value="">— write your own —</option>` + kg.cqs.map((c) => `<option value="${esc(c.id)}">${esc(c.title)}</option>`).join("");
  app.cqs = Object.fromEntries(kg.cqs.map((c) => [c.id, c.query]));
}
function fillRagTargets() {
  const r = app.rag?.[$("#rag-index").value]; const list = r ? r[$("#rag-scope").value] : [];
  $("#rag-target").innerHTML = list.map((x) => `<option>${esc(x)}</option>`).join("");
}
$("#rag-index").onchange = fillRagTargets; $("#rag-scope").onchange = fillRagTargets;
$("#kg-cq").onchange = () => { const q = app.cqs?.[$("#kg-cq").value]; if (q) $("#kg-query").value = q; };
$("#btn-rag").onclick = () => guarded(async () => {
  const q = $("#rag-question").value.trim(); if (!q) return;
  $("#rag-out").innerHTML = `<p class="muted">Retrieving… (the first question loads the embedding and reranking models)</p>`;
  try {
    const r = await api("/api/rag/query", { index: $("#rag-index").value, scope: $("#rag-scope").value, target: $("#rag-target").value, question: q });
    const chunk = (c) => `<div class="chunk"><div class="muted">${esc(c.chunk_id)} · ${esc(c.lecture_id)} · ${fmt(c.start)}–${fmt(c.end)}${c.rerank_score != null ? ` · rerank ${c.rerank_score.toFixed(3)}` : c.score != null ? ` · sim ${c.score.toFixed(3)}` : ""}</div><div dir="auto">${esc(c.text)}</div></div>`;
    $("#rag-out").innerHTML = (r.answer_unavailable ? `<div class="warnbox">No answer generated: ${esc(r.answer_unavailable)} Retrieval still ran; the chunks the model would have received are below.</div>`
      : `<h4>Answer <small class="muted">${esc(r.generation_model)}</small></h4><div class="answer" dir="auto">${esc(r.generated_answer)}</div>`) +
      `<h4>Sent to the model <small class="muted">(${esc(r.rerank_status)})</small></h4>${r.chunks_sent_to_model.map(chunk).join("")}
      <details><summary class="muted">Initial retrieval (top ${r.initial_retrieved.length})</summary>${r.initial_retrieved.map(chunk).join("")}</details>`;
  } catch (e) { $("#rag-out").innerHTML = `<div class="error">${esc(e.message)}</div>`; }
});
$("#btn-kg").onclick = () => guarded(async () => {
  $("#kg-out").innerHTML = `<p class="muted">Running… (the first query loads the graph)</p>`;
  try {
    const r = await api("/api/kg/query", { graph: $("#kg-graph").value, query: $("#kg-query").value });
    $("#kg-out").innerHTML = r.type === "ASK" ? `<div class="answer">${r.answer}</div>`
      : `<p class="muted">${r.row_count} row(s)${r.row_count > r.rows.length ? `, first ${r.rows.length} shown` : ""}</p><div class="scroll"><table class="table"><thead><tr>${r.vars.map((v) => `<th>${esc(v)}</th>`).join("")}</tr></thead>
        <tbody>${r.rows.map((row) => `<tr>${row.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  } catch (e) { $("#kg-out").innerHTML = `<div class="error">${esc(e.message)}</div>`; }
});

// ------------------------------------------------------------------ settings
const STAGE_INFO = {
  correction: { title: "Transcript correction", sub: "V0 → V1", paper: "GPT-OSS-120B via OpenRouter (fallback Nemotron-3-Super-120B-A12B)" },
  extraction: { title: "Entity extraction", sub: "V1 → E1 candidates", paper: "Gemini 2.5 Flash" },
  rag_answer: { title: "RAG answers", sub: "question → answer", paper: "Gemma-4-E4B, Qwen3.5-9B, Llama-3.1-8B in LM Studio" },
};
const SERVERS = [["", "Choose a server…"], ["http://127.0.0.1:1234/v1", "LM Studio (local)"], ["http://127.0.0.1:11434/v1", "Ollama (local)"],
  ["https://openrouter.ai/api/v1", "OpenRouter"], ["https://api.openai.com/v1", "OpenAI"]];
const LANG_LABEL = { null: "Auto-detect", ur: "Urdu", en: "English", ar: "Arabic" };
async function loadSettings() { renderSettings(await api("/api/settings")); }
function renderSettings(v) {
  app.settings = v;
  $("#set-local").textContent = v.local_file; $("#set-config").textContent = v.config_file; $("#set-env").textContent = v.env_file;
  const F = v.fields;
  const changed = (k) => F[k].local ? ` <span class="badge edited" title="Default: ${esc(F[k].default ?? "auto")}">changed</span>` : "";
  const text = (k, label, attrs = "") => `<label>${label}${changed(k)}<input data-set="${k}" value="${esc(F[k].value ?? "")}" ${attrs}></label>`;
  const num = (k, label, step) => text(k, label, `type="number" step="${step}"`);
  const pathField = (k, label) => `<label>${label}${changed(k)} <span class="${F[k].exists ? "ok-t" : "bad-t"}">${F[k].exists ? "✓ found" : "✗ not found"}</span>
    <input data-set="${k}" value="${esc(F[k].value ?? "")}" spellcheck="false"></label>`;
  const stageCard = (stage) => {
    const i = STAGE_INFO[stage], key = v.keys[stage], pk = `llm.${stage}.prompt`;
    const prompts = [...new Set([...v.prompts, F[pk].value].filter(Boolean))];
    return `<div class="card" data-stage="${stage}"><h3>${i.title} <small>${i.sub}</small></h3>
      <p class="muted small">The paper used ${esc(i.paper)}.</p>
      <label>Server <select data-preset="${stage}">${SERVERS.map(([u, l]) => `<option value="${u}">${l}</option>`).join("")}</select></label>
      ${text(`llm.${stage}.base_url`, "Endpoint URL (OpenAI-compatible)", 'spellcheck="false"')}
      <label>Model${changed(`llm.${stage}.model`)}<input data-set="llm.${stage}.model" value="${esc(F[`llm.${stage}.model`].value ?? "")}" list="models-${stage}" spellcheck="false"></label>
      <datalist id="models-${stage}"></datalist>
      <label>API key <span class="muted">(${esc(key.env || "no variable set")}: ${key.set ? "set" : "not set"})</span>
        <input type="password" data-key="${stage}" autocomplete="off" placeholder="${key.set ? "leave blank to keep the current key" : "only if the server needs one"}"></label>
      ${key.set ? `<label class="check"><input type="checkbox" data-key-remove="${stage}"> Remove the saved key</label>` : ""}
      <label>Prompt${changed(pk)}<select data-set="${pk}">${prompts.map((p) => `<option ${p === F[pk].value ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></label>
      ${stage === "rag_answer" ? num("llm.rag_answer.max_tokens", "Max answer tokens", 1) : ""}
      <div class="row"><button type="button" class="small ghost" data-test="${stage}">Test connection</button><span class="muted small" data-test-out="${stage}"></span></div></div>`;
  };
  const lang = F["asr.language"];
  $("#settings-form").innerHTML = `<h3 class="set-h">Language models</h3><div class="grid3">${["correction", "extraction", "rag_answer"].map(stageCard).join("")}</div>
    <h3 class="set-h">Pipeline</h3><div class="grid3">
      <div class="card"><h3>Transcription <small>audio → V0</small></h3>
        <label>Lecture language${changed("asr.language")}<select data-set="asr.language">${lang.choices.map((c) =>
          `<option value="${c ?? ""}" ${c === lang.value ? "selected" : ""}>${LANG_LABEL[c]}</option>`).join("")}</select></label>
        <p class="muted small">The model is fixed to faster-whisper large-v3-turbo (int8), as in the paper. Auto-detect decides per recording.</p></div>
      <div class="card"><h3>Corpus validation <small>E1 / V2</small></h3>
        <div class="row">${num("validation.alpha", "α (lexical weight)", 0.01)}${num("validation.tau", "τ (accept threshold)", 0.01)}${num("validation.delta", "δ (margin)", 0.01)}</div>
        <p class="muted small">Defaults: α ${F["validation.alpha"].default}, τ ${F["validation.tau"].default} (the paper's threshold), δ ${F["validation.delta"].default}.</p></div>
      <div class="card"><h3>RAG retrieval <small>V3 → chunks</small></h3>
        <div class="row">${num("rag.target_seconds", "Chunk length (s)", 1)}${num("rag.top_k_initial", "Retrieve top-k", 1)}${num("rag.top_k_final", "Send to model", 1)}</div>
        <p class="muted small">Changing chunk length applies to indices built from now on.</p></div>
    </div>
    <h3 class="set-h">Corpora <small class="muted">(not redistributed; see artifacts/corpora/README.md)</small></h3>
    <div class="card"><div class="grid2">${pathField("corpora.quran_db", "Quran corpus (validation)")}${pathField("corpora.dua_db", "Dua corpus (validation)")}
      ${pathField("corpora.quran_csv", "quran.csv (KG)")}${pathField("corpora.duas_csv", "duas.csv (KG)")}${pathField("corpora.semantic_hadith_dump", "SemanticHadith dump (KG)")}</div></div>`;
  $("#btn-set-restore").disabled = !v.local_exists;
}
document.addEventListener("change", (ev) => {
  const pre = ev.target.closest("[data-preset]");
  if (pre && pre.value) { $(`[data-set="llm.${pre.dataset.preset}.base_url"]`).value = pre.value; pre.value = ""; }
});
document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-test]"); if (!t) return;
  const stage = t.dataset.test, out = $(`[data-test-out="${stage}"]`);
  out.textContent = "Checking…";
  guarded(async () => {
    const r = await api("/api/settings/test", { stage, base_url: $(`[data-set="llm.${stage}.base_url"]`).value,
      model: $(`[data-set="llm.${stage}.model"]`).value, key: $(`[data-key="${stage}"]`).value || undefined });
    out.innerHTML = r.ok ? `<span class="ok-t">✓ ${esc(r.warning || "connected")}</span>${r.models.length ? ` · ${r.models.length} models listed` : ""}`
      : `<span class="bad-t">✗ ${esc(r.message)}</span>`;
    $(`#models-${stage}`).innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
  });
});
$("#btn-set-save").onclick = () => guarded(async () => {
  const values = {}, keys = {};
  $$("[data-set]").forEach((el) => { values[el.dataset.set] = el.value; });
  $$("[data-key]").forEach((el) => { if (el.value.trim()) keys[el.dataset.key] = el.value.trim(); });
  $$("[data-key-remove]").forEach((el) => { if (el.checked) keys[el.dataset.keyRemove] = ""; });
  const r = await api("/api/settings", { values, keys });
  renderSettings(r); $("#set-msg").textContent = `Saved ${new Date().toLocaleTimeString()}`;
  await loadStatus();
});
$("#btn-set-restore").onclick = () => guarded(async () => {
  if (!confirm("Remove your local settings and go back to minaret.yaml? Saved API keys are kept.")) return;
  renderSettings(await api("/api/settings/restore", {})); $("#set-msg").textContent = "Defaults restored";
  await loadStatus();
});

// ------------------------------------------------------------------ boot
(async () => {
  if (location.hash) showTab(location.hash.slice(1));
  await guarded(loadStatus);
  await guarded(loadRecordings);
})();
