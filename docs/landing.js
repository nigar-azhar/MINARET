"use strict";
// MINARET landing page. Every example is real data from the released artifacts (landing.py).

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const mmss = (t) => { t = Math.max(0, Number(t) || 0); const m = Math.floor(t / 60), s = Math.floor(t % 60); return `${m}:${String(s).padStart(2, "0")}`; };
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const L = { data: null, ex: null, step: "listen", timers: [] };
const later = (fn, ms) => { const t = setTimeout(fn, calm ? 0 : ms); L.timers.push(t); return t; };
const clearTimers = () => { L.timers.forEach(clearTimeout); L.timers = []; };

// ------------------------------------------------------------------ text helpers
const tokens = (s) => String(s || "").split(/\s+/).filter(Boolean);
// Compare words as letters only: no vowel marks, Quranic signs, tatweel or punctuation, and one form
// of the letters Urdu and Arabic script write differently (ی/ي/ى, ک/ك, ہ/ه/ة/ۃ, alef variants).
const bare = (w) => w.normalize("NFC").replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]/g, "")
  .replace(/[«»:؛،۔.,!?؟"'()\[\]]/g, "").replace(/[یىي]/g, "ي").replace(/[کك]/g, "ك").replace(/[ہةۃھ]/g, "ه")
  .replace(/[أإآٱ]/g, "ا").replace(/ۓ/g, "ے");
function lcs(a, b, key = (w) => w) {  // word-level diff: [{op: "same"|"marks"|"del"|"ins", w, from}]
  const ka = a.map(key), kb = b.map(key);
  const n = a.length, m = b.length, dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = ka[i] === kb[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) {
    if (ka[i] === kb[j]) { out.push({ op: a[i] === b[j] ? "same" : "marks", w: b[j], from: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ op: "del", w: a[i++] });
    else out.push({ op: "ins", w: b[j++] });
  }
  while (i < n) out.push({ op: "del", w: a[i++] });
  while (j < m) out.push({ op: "ins", w: b[j++] });
  return out;
}
// Render words; Arabic inside «…» (or a whole Arabic-only segment) is set in the Quranic face.
function words(list, ex) {
  let inQuote = ex.language === "en";
  return list.map(({ w, cls }) => {
    const opens = w.includes("«"), closes = w.includes("»");
    if (opens) inQuote = true;
    const html = `<span class="${[cls, inQuote ? "ar" : ""].filter(Boolean).join(" ")}">${esc(w)}</span>`;
    if (closes) inQuote = ex.language === "en";
    return html;
  }).join(" ");
}
const plain = (text, ex) => words(tokens(text).map((w) => ({ w })), ex);
function diffView(from, to, ex, { insCls = "d-ins", showDel = true } = {}) {
  const d = lcs(tokens(from), tokens(to)).filter((x) => showDel || x.op !== "del");
  return words(d.map((x) => ({ w: x.w, cls: x.op === "same" ? "" : x.op === "del" ? "d-del" : insCls })), ex);
}
function quotationView(text, ex) {  // the quotation replaced from the corpus, highlighted as one span
  let inQuote = ex.language === "en";
  return words(tokens(text).map((w) => {
    if (w.includes("«")) inQuote = true;
    const item = { w, cls: inQuote ? "d-canon" : "" };
    if (w.includes("»")) inQuote = ex.language === "en";
    return item;
  }), ex);
}
const textBox = (html, ex, extra = "") => `<div class="seg-text ${ex.language === "ur" ? "ur" : "ar"} ${extra}" dir="rtl">${html}</div>`;
const quranLink = (ex) => `https://quran.com/${ex.ayah.surah}/${ex.ayah.ayah}`;

// ------------------------------------------------------------------ hero
function hero(ex) {
  const wave = $("#hero-wave");
  wave.innerHTML = Array.from({ length: 56 }, (_, i) => `<i style="height:${18 + Math.round(70 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * .43)))}%;animation-delay:${(i % 9) * -0.13}s"></i>`).join("");
  const line = $("#hero-line");
  line.className = "hero-line ur";
  line.innerHTML = words(tokens(ex.segment.text.v3).map((w) => ({ w, cls: "w" })), ex);
  $("#hero-caption").textContent = `${ex.recording.series_en} · ${ex.recording.speaker_en} · ${mmss(ex.segment.start)}`;
  const ws = $$(".w", line);
  if (calm) { ws.forEach((w) => w.classList.add("on")); wave.classList.add("settled"); return; }
  setTimeout(() => wave.classList.add("settled"), 2200);
  ws.forEach((w, i) => setTimeout(() => w.classList.add("on"), 2300 + i * 110));
}

// ------------------------------------------------------------------ static sections
function heardView(ex) {  // V0 as heard: misheard words vs words only missing their vowel marks
  const d = lcs(tokens(ex.segment.text.v0), tokens(ex.segment.text.v1), bare).filter((x) => x.op !== "ins");
  return words(d.map((x) => ({ w: x.op === "marks" ? x.from : x.w, cls: x.op === "del" ? "d-miss" : x.op === "marks" ? "d-bare" : "" })), ex);
}
const HEARD_LEGEND = `<div class="legend"><span class="lg-del">misheard</span><span class="lg-bare">vowel marks missing</span></div>`;
function problem(ex) {
  const heard = heardView(ex);
  const kg = ex.ayah.kg;
  $("#problem-compare").innerHTML = `
    <div class="panel bad"><h4>What speech recognition heard</h4>${textBox(heard, ex)}
      ${HEARD_LEGEND}<p class="ref">Raw ASR (V0), ${esc(ex.recording.id)} at ${mmss(ex.segment.start)}.</p></div>
    <div class="panel good"><h4>What the verse says</h4><div class="seg-text ar" dir="rtl">${esc(ex.ayah.e2?.text || "")}</div>
      ${kg.translation_en ? `<p class="en">${esc(kg.translation_en)}</p>` : ""}
      <p class="ref"><span class="pill">Surah ${esc(ex.ayah.surah_name)} ${ex.ayah.surah}:${ex.ayah.ayah}</span>
        <a href="${quranLink(ex)}" target="_blank" rel="noopener">quran.com</a></p></div>`;
}
function beforeAfter(ex) {
  $("#before-after").innerHTML = `
    <div class="panel bad"><h4>Heard (V0)</h4>${textBox(plain(ex.segment.text.v0, ex), ex)}</div>
    <div class="panel good"><h4>Reviewed (V3), with its source</h4>${textBox(plain(ex.segment.text.v3, ex), ex)}
      <p class="ref"><span class="pill">Ayah ${ex.ayah.surah}:${ex.ayah.ayah} · ${esc(ex.ayah.e2?.usage)} · ${esc(ex.ayah.e2?.extent)}</span>
        ${ex.ayah.kg.exact_match.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${u.includes("semantictafsir") ? "SemanticTafsir" : "Quran Ontology"}</a>`).join("")}
        <a href="${quranLink(ex)}" target="_blank" rel="noopener">quran.com</a></p></div>`;
}
function released(data) {
  const r = data.released, repo = data.repo_url;
  const path = (p) => repo ? `<a href="${esc(repo)}/tree/main/${p}" target="_blank" rel="noopener"><code>${p}</code></a>` : `<code>${p}</code>`;
  $("#released-cards").innerHTML = `
    <div class="card"><div class="big">${r.recordings}</div><h3>reviewed lectures</h3>
      <ul>${r.series.map((s) => `<li>${esc(s.title_en)} <span class="ur" dir="rtl">(${esc(s.title_ur)})</span>, ${esc(s.language)}, ${esc(s.speaker)}: ${s.recordings}</li>`).join("")}</ul>
      <p>V0 to V3 transcripts and E1/E2 entities for each. ${path("artifacts/recordings")}</p></div>
    <div class="card"><h3>Knowledge graph</h3><p>Lectures, segments, quotations, hadith, duas, topics and headings as RDF,
      linked to the Quran Ontology, SemanticTafsir and SemanticHadith, with the 16 competency questions. ${path("artifacts/kg")}</p></div>
    <div class="card"><h3>Question answering</h3><p>Lecture and series RAG indices, bilingual gold questions and
      human-graded answers. ${path("artifacts/rag")}</p></div>
    <div class="card"><h3>Pipeline and panel</h3><p>The <b>minaret</b> package runs every stage on new recordings with
      any OpenAI-compatible model; the reviewer panel simulates the review. ${path("minaret")} ${path("reviewer_panel")}</p></div>`;
}
function credits(data) {
  const p = data.paper;
  $("#paper-title").textContent = p.title;
  if (p.url) { const el = $("#paper-link"); el.innerHTML = `<a href="${esc(p.url)}" target="_blank" rel="noopener">Read the paper</a>`; el.classList.remove("hidden"); }
  $("#authors").innerHTML = p.authors.map((a) => `<li>${esc(a.name)}<a href="https://orcid.org/${esc(a.orcid)}" target="_blank" rel="noopener" title="ORCID ${esc(a.orcid)}">ORCID</a></li>`).join("");
  $("#affiliation").textContent = p.affiliation;
  if (data.repo_url) $$(".repo-link").forEach((a) => { a.href = data.repo_url; a.classList.remove("hidden"); });
}

// ------------------------------------------------------------------ stage
const STEP_TITLE = { listen: "The recording", asr: "V0 · raw transcript", correct: "V1 · after LLM correction",
  validate: "E1 · V2 · corpus-verified", review: "V3 · E2 · reviewed", graph: "Knowledge graph", ask: "Question answering" };
function stageTop(ex) {
  return `<div class="stage-top"><span class="stage-title">${STEP_TITLE[L.step]}</span>
    <span>${esc(ex.recording.id)} · ${mmss(ex.segment.start)}–${mmss(ex.segment.end)}</span></div>`;
}
const RENDER = {
  listen(ex) {
    return `<div class="audio-card"><button class="play" id="play" aria-label="Play these ten seconds">▶</button>
      <div class="meta"><b>${esc(ex.recording.series_en)}</b> <span class="ur" dir="rtl">${esc(ex.recording.series_ur)}</span><br>
        ${esc(ex.recording.title_en)} · ${esc(ex.recording.speaker_en)}<br>${mmss(ex.segment.start)}–${mmss(ex.segment.end)} of the lecture</div></div>
      <div class="wave" aria-hidden="true">${Array.from({ length: 40 }, (_, i) => `<i style="height:${15 + Math.round(75 * Math.abs(Math.sin(i * 2.1)))}%;animation-delay:${(i % 7) * -0.17}s"></i>`).join("")}</div>
      <p class="meta" id="play-note">Press play to hear the segment from the publisher's audio.</p>`;
  },
  asr(ex) {
    return `${textBox(heardView(ex), ex)}${HEARD_LEGEND}`;
  },
  correct(ex) {
    const d = lcs(tokens(ex.segment.text.v0), tokens(ex.segment.text.v1), bare);
    const html = words(d.map((x) => ({ w: x.w, cls: { same: "", marks: "d-marks", del: "d-del", ins: "d-ins" }[x.op] })), ex);
    return `${textBox(html, ex)}
      <div class="legend"><span class="lg-marks">vowel marks and punctuation added</span><span class="lg-ins">word changed or added</span><span class="lg-del">removed</span></div>`;
  },
  validate(ex) {
    return `<div class="scanner" id="scanner"><span>Scoring against 6,236 verses</span><span class="ids" id="scan-ids">1:1</span><span class="bar"><i id="scan-bar"></i></span></div>
      <div id="validate-rest" class="seq hidden">
        <div class="chips"><span class="chip">Ayah ${ex.ayah.surah}:${ex.ayah.ayah} · Surah ${esc(ex.ayah.surah_name)}</span>
          <span class="chip">${esc(ex.ayah.e1?.usage || "quotation")}</span><span class="chip">${esc(ex.ayah.e1?.extent || "")}</span></div>
        ${textBox(quotationView(ex.segment.text.v2, ex), ex)}
        <div class="legend"><span class="lg-canon">replaced with the canonical text</span></div></div>`;
  },
  review(ex) {
    return `<div class="seq">
      ${textBox(diffView(ex.segment.text.v2, ex.segment.text.v3, ex, { insCls: "d-rev" }), ex)}
      <div class="legend"><span class="lg-rev">corrected by the reviewer</span><span class="lg-del">removed by the reviewer</span></div>
      <div class="chips"><span class="chip">Segment reviewed</span><span class="chip">Ayah ${ex.ayah.surah}:${ex.ayah.ayah} · ${esc(ex.ayah.e2?.usage)} · ${esc(ex.ayah.e2?.extent)} ✓</span></div>
      <div class="chips"><span class="chip muted">If in doubt: Flag</span><span class="chip muted">→ Need Review</span><span class="chip muted">→ super reviewer decides</span></div></div>`;
  },
  graph(ex) {
    const topic = ex.topics[0], heading = ex.headings[0], lang = ex.language;
    const name = (t, a, b) => t ? (lang === "ur" ? (t[b] || t[a] || t.name) : (t[a] || t.name || t[b])) : null;
    const clip = (s, n = 34) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");
    // Position on the outer group, animation on the inner one: a CSS transform in the animation
    // would otherwise replace the SVG transform attribute and stack every node at the origin.
    const N = (id, x, y, w, title, sub, cls = "", i = 0) => `<g transform="translate(${x - w / 2},${y - 22})"><g class="node ${cls}" style="animation-delay:${i * .18}s">
      <rect width="${w}" height="44" rx="12"></rect><text x="12" y="19">${esc(clip(title, Math.round(w / 7.2)))}</text><text class="sub" x="12" y="35">${esc(clip(sub, Math.round(w / 6.5)))}</text></g></g>`;
    const E = (x1, y1, x2, y2, label, hot, i) => `<path class="edge ${hot ? "hot" : ""}" style="animation-delay:${i * .18}s" d="M${x1} ${y1} L${x2} ${y2}"></path>
      ${label ? `<text class="elabel" x="${(x1 + x2) / 2 + 6}" y="${(y1 + y2) / 2 - 4}">${label}</text>` : ""}`;
    const v = ex.ayah;
    return `<svg class="graph" viewBox="0 0 560 400" role="img" aria-label="Knowledge-graph nodes for this segment">
      ${E(280, 52, 110, 52, "", false, 1)}${E(280, 52, 450, 52, "", false, 1)}${E(280, 74, 280, 128, "", false, 2)}
      ${topic ? E(110, 150, 190, 150, "", false, 3) : ""}${heading ? E(450, 150, 370, 150, "", false, 3) : ""}
      ${E(280, 172, 280, 218, "occursIn", true, 4)}${E(280, 262, 280, 308, "refersTo", true, 5)}
      ${E(230, 352, 120, 352, "exactMatch", true, 6)}${E(330, 352, 440, 352, "exactMatch", true, 6)}
      ${N("series", 110, 52, 190, ex.recording.series_en, "Series · " + ex.recording.speaker_en, "", 0)}
      ${N("lecture", 280, 52, 150, ex.recording.title_en, "Lecture " + (ex.recording.kg_id || ""), "core", 0)}
      ${N("speaker", 450, 52, 170, ex.recording.speaker_en, "Speaker", "", 1)}
      ${topic ? N("topic", 110, 150, 190, name(topic, "name_en", "name_ur"), "Topic", "", 2) : ""}
      ${N("segment", 280, 150, 180, "Segment group", mmss(ex.segment.start) + "–" + mmss(ex.segment.end), "core", 2)}
      ${heading ? N("heading", 450, 150, 170, name(heading, "title_en", "title_ur"), "Heading", "", 3) : ""}
      ${N("occ", 280, 240, 200, "Verse occurrence", `${v.e2?.usage || ""} · ${v.e2?.extent || ""}`, "core", 4)}
      ${N("verse", 280, 330, 180, `Quran ${v.surah}:${v.ayah}`, "Surah " + v.surah_name, "core", 5)}
      ${N("qo", 110, 352, 170, "Quran Ontology", `quran${v.surah}-${v.ayah}`, "ext", 6)}
      ${N("st", 450, 352, 170, "SemanticTafsir", `V${String(v.surah).padStart(3, "0")}_${String(v.ayah).padStart(3, "0")}`, "ext", 6)}
    </svg>`;
  },
  ask(ex) {
    const a = ex.rag.answer, dirQ = a.language === "urdu" ? "rtl" : "auto", cls = a.language === "urdu" ? "ur" : "";
    const cite = (t) => esc(t.length > 700 ? t.slice(0, 690) + " …" : t)
      .replace(/[\[(]?(?:chunk_id=)?([\w-]+_chunk_\d+)[\])]?/g, (_, id) => `<span class="cite">${id}</span>`)
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\*([^*\s][^*]*)\*/g, "<i>$1</i>");
    const c = a.chunks[0];
    const refusal = ex.rag.refusal;
    return `<div class="seq">
      <div class="bubble q ${cls}" dir="${dirQ}">${esc(a.question)}</div>
      ${c ? `<div class="chunk ${cls}" dir="${dirQ}"><span class="cid">retrieved: ${esc(c.id)} · ${mmss(c.start)}–${mmss(c.end)}</span><br>${esc(c.text)}</div>` : ""}
      <div class="answer ${cls}" dir="${dirQ}">${cite(a.answer)}</div>
      <div class="verdict">✓ Human-graded in RQ5: correct and grounded · ${esc(a.model)}</div>
      ${refusal ? `<div class="bubble q" dir="auto">${esc(refusal.question)}</div>` : ""}
    </div>${refusal ? `<div class="answer" dir="auto">${esc(refusal.answer)}</div><div class="verdict">✓ Correctly refused: the lecture does not say</div>` : ""}`;
  },
};
function renderStage() {
  clearTimers();
  const ex = L.ex, stage = $("#stage");
  stage.className = "stage" + (calm ? "" : " anim");
  stage.innerHTML = stageTop(ex) + `<div class="stage-body">${RENDER[L.step](ex)}</div>`;
  if (L.step === "listen") wirePlay(ex);
  if (L.step === "validate") runScanner(ex);
}
function runScanner(ex) {
  const ids = $("#scan-ids"), bar = $("#scan-bar"), rest = $("#validate-rest"), sc = $("#scanner");
  const done = () => { ids.textContent = `${ex.ayah.surah}:${ex.ayah.ayah} ✓`; sc.classList.add("locked"); bar.style.width = "100%"; rest.classList.remove("hidden"); };
  if (calm) return done();
  requestAnimationFrame(() => { bar.style.width = "100%"; });
  const iv = setInterval(() => { ids.textContent = `${1 + Math.floor(Math.random() * 114)}:${1 + Math.floor(Math.random() * 60)}`; }, 55);
  L.timers.push(later(() => { clearInterval(iv); done(); }, 1500));
  L.timers.push(iv);  // cleared by clearTimeout as well
}
function wirePlay(ex) {
  const btn = $("#play"), clip = $("#clip"), note = $("#play-note");
  if (!ex.recording.audio_url) { btn.disabled = true; note.textContent = "No audio link for this recording."; return; }
  btn.onclick = () => {
    if (!clip.paused) { clip.pause(); return; }
    clip.src = `${ex.recording.audio_url}#t=${ex.segment.start},${ex.segment.end}`;
    clip.ontimeupdate = () => { if (clip.currentTime >= ex.segment.end) clip.pause(); };
    clip.onplay = () => { btn.textContent = "❚❚"; $$(".stage .wave").forEach((w) => w.classList.remove("settled")); };
    clip.onpause = () => { btn.textContent = "▶"; };
    clip.onerror = () => { note.textContent = "The publisher's audio could not be loaded here."; };
    clip.play().catch(() => { note.textContent = "The publisher's audio could not be played here."; });
  };
  $$(".stage .wave").forEach((w) => w.classList.add("settled"));
}
function stepNotes(ex) {
  $$(".note").forEach((n) => {
    const k = n.dataset.note;
    n.textContent = k === "meta" ? `${ex.recording.series_en}, ${ex.recording.speaker_en}: "${ex.recording.title_en}".` : (ex.notes[k] || "");
  });
}

// ------------------------------------------------------------------ wiring
function setExample(id) {
  L.ex = L.data.examples.find((e) => e.id === id) || L.data.examples[0];
  $$(".toggle button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.example === L.ex.id)));
  stepNotes(L.ex); problem(L.ex); beforeAfter(L.ex); renderStage();
}
function observe() {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) {
      const s = e.target.dataset.step;
      $$(".step").forEach((x) => x.classList.toggle("active", x === e.target));
      if (s !== L.step) { L.step = s; renderStage(); }
    }
  }, { rootMargin: "-45% 0px -50% 0px" });
  $$(".step").forEach((s) => io.observe(s));
  const rv = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); rv.unobserve(e.target); } }), { threshold: .12 });
  $$(".reveal").forEach((s) => rv.observe(s));
}
(async () => {
  const src = document.querySelector('meta[name="minaret-data"]').content;
  try { L.data = await (await fetch(src)).json(); }
  catch (e) { document.querySelector(".lede").insertAdjacentHTML("afterend", `<p class="lede">Could not load the examples (${esc(e.message)}).</p>`); return; }
  document.body.classList.add(`mode-${L.data.mode}`);
  $$(".toggle button").forEach((b) => b.onclick = () => setExample(b.dataset.example));
  hero(L.data.examples[0]); released(L.data); credits(L.data);
  $$(".step")[0].classList.add("active");
  setExample("ur"); observe();
})();
