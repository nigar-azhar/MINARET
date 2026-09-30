"""
Shared KG infrastructure: namespaces, canonical-entity lookups (QuranVerse/Hadith/Dua), the
SemanticHadith block parser, the topic-dedup machinery (including the cross-series registry),
and serialization/output helpers. `build.py` drives one KGBuilder per series from that series'
JSON config (artifacts/kg/series/<SERIES>.json).

Naming note: `KGBuilder.E3` is the list of *topic-level proposals* (merge / concept-mapping
candidates plus their review status) written to <SERIES>_topic_proposals.json. It is unrelated
to the per-recording entity set, which in this release is always e2.json.
"""
import csv
import difflib
import json
import os
import re
from pathlib import Path

from rdflib import Graph, Namespace, Literal, RDF, XSD
from rdflib.namespace import SKOS

MIN = Namespace("http://minaret-eval.org/ontology#")
HADITH = Namespace("http://www.semantichadith.com/ontology/")
QUR = Namespace("http://quranontology.com/Resource/")
TAFSIR = Namespace("http://www.semantictafsir.com/ontology/")

HADITH_REF_PREFIX = {"SB": "Sahih al-Bukhari", "JT": "Jami' at-Tirmidhi", "SM": "Sahih Muslim",
                      "IM": "Ibn Majah", "SD": "Sunan Abu Dawud", "SN": "Sunan an-Nasa'i"}
# Different series' E2 data spell collection prefixes differently (e.g. Hajj uses "AD" and
# "IbnMajah" where TQ2005 would have used "SD"/"IM"). Normalize to the SemanticHadith KG's own
# prefixes before lookup. Prefixes not listed here and not already a HADITH_REF_PREFIX key are
# genuinely uncovered collections (e.g. "Ahmad" / Musnad Ahmad).
HADITH_PREFIX_ALIASES = {"AD": "SD", "IBNMAJAH": "IM", "TIRMIDHI": "JT", "BUKHARI": "SB",
                          "MUSLIM": "SM", "NASAI": "SN", "ABUDAWUD": "SD"}

TAU = 0.6  # lexical-similarity threshold for topic merge/registry candidates


def uri_safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(s))


def slugify(name):
    """Human-readable id from a topic's English name: 'Prayer and Discipline (Salah)'
    -> 'Prayer_and_Discipline_Salah'. Case preserved for readability; punctuation
    dropped, not transliterated -- collisions (rare) get a numeric suffix by the
    caller if they ever occur."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return re.sub(r"_+", "_", s)


def duration_to_seconds(s):
    if not s:
        return None
    parts = [int(p) for p in str(s).split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    return h * 3600 + m * 60 + sec


def parse_ayah_numbers(raw):
    """'1' -> [1]; '1-7' -> [1,2,3,4,5,6,7]"""
    raw = str(raw)
    if "-" in raw:
        a, b = raw.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(raw)]


def expand_ayat_ranges(ayat_list):
    """Split a range citation ('ayah_number': '1-7', source JSON field name unchanged) into one
    entry per single ayah, each keeping the same start/end/text/usage/extent -- so
    VerseOccurrence.refersTo stays singular rather than multi-valued."""
    out = []
    for a in ayat_list:
        for n in parse_ayah_numbers(a["ayah_number"]):
            entry = dict(a)
            entry["ayah_number"] = str(n)
            out.append(entry)
    return out


def load_quran_csv(path):
    idx = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            idx[(int(row["sura"]), int(row["aya"]))] = row
    return idx


def load_duas_csv(path):
    idx = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            idx[row["duaId"]] = row
    return idx


def our_ref_to_kg_id(ref):
    """'SB_723' -> 'SB-HD0723'; 'AD_1721' -> 'SD-HD1721' (alias); 'Ahmad_4142' -> None
    (collection not in the SemanticHadith KG)."""
    m = re.match(r"^([A-Za-z]+)_(\d+)$", ref)
    if not m:
        return None
    prefix, num = m.group(1), m.group(2)
    prefix = HADITH_PREFIX_ALIASES.get(prefix.upper(), prefix)
    if prefix not in HADITH_REF_PREFIX:
        return None
    return f"{prefix}-HD{int(num):04d}"


def unescape_turtle_string(s):
    """Undo Turtle string escaping so rdflib doesn't double-escape on re-serialization."""
    return (s.replace("\\\\", "\x00").replace('\\"', '"').replace("\\n", "\n")
             .replace("\\t", "\t").replace("\\r", "\r").replace("\x00", "\\"))


def parse_hadith_block(block):
    """Extract fields from one SemanticHadith Turtle individual block. fullHadithText is
    predicate-scoped (only the string list following the ':fullHadithText' keyword) -- earlier
    this grabbed every xsd:string literal in the whole block regardless of predicate, which
    wrongly pulled in e.g. the Arabic hadithType grade label ("مرفوع@ar") as if it were hadith
    text, alongside the real Arabic text, under the same @ar tag."""
    if not block:
        return None
    out = {"fullHadithText": []}
    m_field = re.search(r':fullHadithText\s+(.*?)(?:;|\.\s*\n\n)', block, re.DOTALL)
    field_text = m_field.group(1) if m_field else ""
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\^\^xsd:string', field_text):
        val = unescape_turtle_string(m.group(1))
        lang = None
        for tag in ("@en", "@ur", "@ar"):
            if val.endswith(tag):
                lang = tag[1:]
                val = val[: -len(tag)]
                break
        val = val.strip()
        if val and val != "0":
            out["fullHadithText"].append({"lang": lang, "text": val})
    m = re.search(r':hadithReferenceNo\s+"(\d+)"', block)
    if m:
        out["hadithReferenceNo"] = m.group(1)
    m = re.search(r':hadithURL\s+"([^"]+)"', block)
    if m:
        out["hadithURL"] = m.group(1)
    return out


def load_hadith_blocks(raw_blocks):
    """raw_blocks: {kg_id: raw Turtle block or None}, from hadith_blocks.extract_blocks()."""
    return {k: parse_hadith_block(v) for k, v in raw_blocks.items()}


def timestamp_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# minaret:hasUsageType / minaret:hasExtentType point at the controlled-vocabulary individuals
# declared in minaret_kg_schema.ttl (minaret:CitationUsage / minaret:CitationExtent), not a
# string -- matching how SemanticHadith models its own HadithType classification. Confirmed
# exhaustive by checking every ayat/hadith/dua "usage"/"extent" value across every series' E1+E2
# data: exactly {quotation, translation, explicit paraphrase} and {complete, partial} -- no bare
# "paraphrase" ever appears in the source data at all, only "explicit paraphrase", which is the
# same Paraphrase value/wording, not a distinct 4th type.
USAGE_TYPE_MAP = {"quotation": "Quotation", "translation": "Translation",
                   "paraphrase": "Paraphrase", "explicit paraphrase": "Paraphrase"}
EXTENT_TYPE_MAP = {"complete": "CompleteCitation", "partial": "PartialCitation"}


def usage_type_node(value):
    name = USAGE_TYPE_MAP.get(value.strip().lower())
    if name is None:
        raise ValueError(f"Unrecognized citation usage type: {value!r} -- not one of "
                          f"{sorted(set(USAGE_TYPE_MAP))}. Add it to USAGE_TYPE_MAP in "
                          "kg_common.py (and minaret:CitationUsage in the schema) if genuine.")
    return MIN[name]


def extent_type_node(value):
    name = EXTENT_TYPE_MAP.get(value.strip().lower())
    if name is None:
        raise ValueError(f"Unrecognized citation extent type: {value!r} -- not one of "
                          f"{sorted(set(EXTENT_TYPE_MAP))}. Add it to EXTENT_TYPE_MAP in "
                          "kg_common.py (and minaret:CitationExtent in the schema) if genuine.")
    return MIN[name]


def load_topic_registry(path):
    if Path(path).exists():
        return json.loads(Path(path).read_text())
    return []  # list of {"slug","name_en","description_en","series":[...]}


def save_topic_registry(registry, path):
    Path(path).write_text(json.dumps(registry, ensure_ascii=False, indent=2))


class KGBuilder:
    """One instance per series build run. Owns the rdflib Graph, canonical-entity
    caches, E3 list, and build log; shared across recordings within that series."""

    def __init__(self, series_code, *, quran_csv, duas_csv, raw_hadith_blocks, registry_path, out_dir):
        self.series_code = series_code
        self.registry_path = Path(registry_path)
        self.out_dir = Path(out_dir)
        self.g = Graph()
        self.g.bind("minaret", MIN)
        self.g.bind("hadith", HADITH)
        self.g.bind("qur", QUR)
        self.g.bind("tafsir", TAFSIR)
        self.g.bind("skos", SKOS)
        self.E3 = []
        self.BUILD_LOG = []
        self.ayah_cache = {}
        self.hadith_cache = {}
        self.dua_cache = {}
        self.topic_records = []  # {"node","name","description","recording"}
        self.quran_idx = load_quran_csv(quran_csv)
        self.log(f"Loaded quran.csv: {len(self.quran_idx)} ayat.")
        self.duas_idx = load_duas_csv(duas_csv)
        self.log(f"Loaded duas.csv: {len(self.duas_idx)} duas.")
        self.hadith_blocks = load_hadith_blocks(raw_hadith_blocks)
        self.log(f"Loaded {len([b for b in self.hadith_blocks.values() if b])} "
                 "resolved SemanticHadith blocks.")
        self.registry = load_topic_registry(self.registry_path)
        self.log(f"Loaded topic registry: {len(self.registry)} topics from prior series.")

    def log(self, msg):
        self.BUILD_LOG.append(msg)
        print(msg)

    # --- canonical entities, deduped within this run by their natural key -----------
    def get_ayah_node(self, surah, ayah):
        g = self.g
        key = (surah, ayah)
        if key in self.ayah_cache:
            return self.ayah_cache[key]
        node = MIN[f"QuranVerse_{surah}_{ayah}"]
        g.add((node, RDF.type, MIN.QuranVerse))
        g.add((node, MIN.surahNumber, Literal(surah, datatype=XSD.integer)))
        g.add((node, MIN.verseNumber, Literal(ayah, datatype=XSD.integer)))
        row = self.quran_idx.get(key)
        if row:
            g.add((node, MIN.juz, Literal(int(row["juz"]), datatype=XSD.integer)))
            g.add((node, MIN.textUthmani, Literal(row["text"])))
            g.add((node, MIN.textIndopak, Literal(row["text_indopak"])))
            g.add((node, MIN.textClean, Literal(row["textc"])))
            g.add((node, MIN.translationEn, Literal(row["en_sahih"])))
            g.add((node, MIN.translationUr, Literal(row["ur_farhat"])))
        else:
            self.log(f"WARNING: QuranVerse {surah}:{ayah} not found in quran.csv -- no canonical text.")
        g.add((node, SKOS.exactMatch, QUR[f"quran{surah}-{ayah}"]))
        # SemanticTafsir's Verse individuals (V{surah:03d}_{ayah:03d}) cover the complete Quran
        # (6,236 individuals, confirmed against the full SemanticTafsirKG.ttl dump) -- computed
        # the same way as the quranontology.com link above, no lookup needed. Checked and
        # deliberately NOT doing the analogous thing for Hadith or Topic/Theme: SemanticTafsir's
        # Hadith individuals use their own local numbering (no shared ID space with
        # SemanticHadith's KG despite reusing its class), and its 52 Theme individuals are a
        # narrow, partly data-quality-noisy tafsir-methodology vocabulary (asbab an-nuzul, naskh,
        # qiraat...) with no real overlap with MINARET's Topic vocabulary.
        g.add((node, SKOS.exactMatch, TAFSIR[f"V{surah:03d}_{ayah:03d}"]))
        self.ayah_cache[key] = node
        return node

    def get_hadith_node(self, reference, expanded_reference):
        g = self.g
        if reference in self.hadith_cache:
            return self.hadith_cache[reference]
        node = MIN[f"Hadith_{uri_safe(reference)}"]
        g.add((node, RDF.type, MIN.Hadith))
        g.add((node, MIN.reference, Literal(reference)))
        g.add((node, MIN.expandedReference, Literal(expanded_reference)))
        kg_id = our_ref_to_kg_id(reference)
        block = self.hadith_blocks.get(kg_id) if kg_id else None
        if block:
            g.add((node, SKOS.exactMatch, HADITH[kg_id]))
            for entry in block["fullHadithText"]:
                prop = {"en": MIN.translationEn, "ur": MIN.translationUr,
                        "ar": MIN.textUthmani}.get(entry["lang"])
                if prop:
                    g.add((node, prop, Literal(entry["text"])))
            # Deliberately not storing the hadith's authenticity/transmission-chain grade
            # (SemanticHadith's own HadithType, e.g. marfu) -- MINARET has no way to verify or
            # maintain that classification; a consumer who needs it follows skos:exactMatch to
            # the external SemanticHadith KG instead, which is authoritative for it.
        else:
            self.log(f"Hadith {reference}: no SemanticHadith match "
                     f"({'collection not in KG dump' if not kg_id else 'kg_id ' + kg_id + ' not found'}) "
                     "-- stays unresolved (reference + expandedReference only).")
        self.hadith_cache[reference] = node
        return node

    def get_dua_node(self, reference):
        g = self.g
        if reference in self.dua_cache:
            return self.dua_cache[reference]
        node = MIN[f"Dua_{uri_safe(reference)}"]
        g.add((node, RDF.type, MIN.Dua))
        g.add((node, MIN.reference, Literal(reference)))
        row = self.duas_idx.get(reference)
        if row:
            g.add((node, MIN.translationEn, Literal(row["dua_en"])))
            g.add((node, MIN.translationUr, Literal(row["dua_ur"])))
            g.add((node, MIN.transliteration, Literal(row["transliteration"])))
            if row.get("duaType_en"):
                g.add((node, MIN.duaTypeEn, Literal(row["duaType_en"])))
            if row.get("duaType_ur"):
                g.add((node, MIN.duaTypeUr, Literal(row["duaType_ur"])))
        else:
            self.log(f"WARNING: Dua {reference} not found in duas.csv -- storing occurrence text only.")
        self.dua_cache[reference] = node
        return node

    def get_topic_node(self, name_en, desc_en, name_ur, desc_ur, recording_id):
        """Human-readable, name-based id -- so the same exact topic name in a later
        series automatically resolves to the same node once graphs are combined,
        with no extra dedup step needed for exact matches."""
        g = self.g
        slug = slugify(name_en)
        node = MIN[f"Topic_{slug}"]
        is_new = (node, RDF.type, MIN.Topic) not in g
        if is_new:
            g.add((node, RDF.type, MIN.Topic))
            g.add((node, MIN.nameEn, Literal(name_en)))
            g.add((node, MIN.descriptionEn, Literal(desc_en)))
            if name_ur:
                g.add((node, MIN.nameUr, Literal(name_ur)))
            if desc_ur:
                g.add((node, MIN.descriptionUr, Literal(desc_ur)))
            self.topic_records.append({"node": node, "name": name_en, "description": desc_en,
                                        "recording": recording_id})
        return node

    # --- topic dedup: within-run + against the cross-series registry ----------------
    def run_topic_dedup(self, concept_keywords):
        self.log("Topic dedup uses difflib lexical similarity as a placeholder for the paper's "
                  f"BGE-M3 embedding approach (no embedding model available). tau={TAU} on "
                  "normalized-name ratio. All candidates logged to E3 as 'proposed'.")
        # within this run
        for i in range(len(self.topic_records)):
            for j in range(i + 1, len(self.topic_records)):
                a, b = self.topic_records[i], self.topic_records[j]
                if a["name"] == b["name"]:
                    continue  # same slug already, not a separate node
                ratio = difflib.SequenceMatcher(None, a["name"].lower(), b["name"].lower()).ratio()
                if ratio >= TAU:
                    self.E3.append({
                        "type": "topic_merge", "scope": "within_series",
                        "recordingId_a": a["recording"], "topicId_a": str(a["node"]), "name_a": a["name"],
                        "recordingId_b": b["recording"], "topicId_b": str(b["node"]), "name_b": b["name"],
                        "lexicalSimilarity": round(ratio, 3), "status": "proposed",
                    })
        # against topics already in the registry from OTHER series (skip entries that already
        # belong to this same series -- happens on a rebuild, and would otherwise re-flag this
        # series' own within-series candidates a second time as spurious "cross-series" ones)
        for rec in self.topic_records:
            for prior in self.registry:
                if prior["name_en"] == rec["name"] or self.series_code in prior.get("series", []):
                    continue
                ratio = difflib.SequenceMatcher(None, rec["name"].lower(),
                                                 prior["name_en"].lower()).ratio()
                if ratio >= TAU:
                    self.E3.append({
                        "type": "topic_merge", "scope": "cross_series",
                        "recordingId_a": rec["recording"], "topicId_a": str(rec["node"]), "name_a": rec["name"],
                        "recordingId_b": prior["series"][0] if prior.get("series") else "?",
                        "topicId_b": f"minaret:Topic_{prior['slug']}", "name_b": prior["name_en"],
                        "lexicalSimilarity": round(ratio, 3), "status": "proposed",
                    })

        concept_hits = 0
        for rec in self.topic_records:
            text = (rec["name"] + " " + rec["description"]).lower()
            for concept, kws in concept_keywords.items():
                hit = [kw for kw in kws if kw in text]
                if hit:
                    self.E3.append({
                        "type": "topic_concept_mapping",
                        "recordingId": rec["recording"], "topicId": str(rec["node"]), "name": rec["name"],
                        "matchType": "closeMatch", "targetConcept": concept,
                        "rationale": f"keyword heuristic matched on: {hit}", "status": "proposed",
                    })
                    concept_hits += 1

        n_merge = sum(1 for e in self.E3 if e["type"] == "topic_merge")
        self.log(f"Topic dedup: {len(self.topic_records)} topic instances, {n_merge} merge "
                 f"candidates flagged ({sum(1 for e in self.E3 if e['type']=='topic_merge' and e['scope']=='cross_series')} "
                 f"cross-series), {concept_hits} concept-mapping candidates flagged.")

    def apply_reviewed_decisions(self, reviewed_merges, reviewed_concepts):
        g = self.g
        node_by_name = {}
        for rec in self.topic_records:
            node_by_name.setdefault(rec["name"], rec["node"])

        def merge_topic_nodes(keep, drop, drop_name):
            for s, p, o in list(g.triples((None, None, drop))):
                g.remove((s, p, o))
                g.add((s, p, keep))
            for s, p, o in list(g.triples((drop, None, None))):
                g.remove((s, p, o))
            g.add((keep, SKOS.altLabel, Literal(drop_name)))

        for e in self.E3:
            if e["type"] == "topic_merge":
                decision = reviewed_merges.get(frozenset([e["name_a"], e["name_b"]]))
                if decision == "accept" and e["name_a"] in node_by_name and e["name_b"] in node_by_name:
                    keep, drop = node_by_name[e["name_a"]], node_by_name[e["name_b"]]
                    merge_topic_nodes(keep, drop, e["name_b"])
                    e["status"] = "accepted"
                    self.log(f"Topic merge ACCEPTED: '{e['name_b']}' merged into '{e['name_a']}'.")
                elif decision == "reject_but_related" and e["name_a"] in node_by_name and e["name_b"] in node_by_name:
                    a_node, b_node = node_by_name[e["name_a"]], node_by_name[e["name_b"]]
                    g.add((a_node, SKOS.related, b_node))
                    g.add((b_node, SKOS.related, a_node))
                    e["status"] = "rejected_but_related"
                    self.log(f"Topic merge REJECTED (kept separate): '{e['name_a']}' / '{e['name_b']}' "
                             "-- linked via skos:related.")
                elif decision:
                    e["status"] = decision
                else:
                    self.log(f"NOTE: no review decision for merge candidate "
                             f"'{e['name_a']}' / '{e['name_b']}' -- left as proposed.")
            elif e["type"] == "topic_concept_mapping":
                decision = reviewed_concepts.get((e["name"], e["targetConcept"]))
                concept_uri = HADITH[e["targetConcept"].split(":", 1)[1]]
                if decision == "accept" and e["name"] in node_by_name:
                    node = node_by_name[e["name"]]
                    pred = SKOS.exactMatch if e["matchType"] == "exactMatch" else SKOS.closeMatch
                    g.add((node, pred, concept_uri))
                    e["status"] = "accepted"
                    self.log(f"Topic concept mapping ACCEPTED: '{e['name']}' {e['matchType']} {e['targetConcept']}.")
                elif decision:
                    e["status"] = decision
                    self.log(f"Topic concept mapping {decision.upper()}: '{e['name']}' -> {e['targetConcept']}.")
                else:
                    self.log(f"NOTE: no review decision for concept mapping "
                             f"'{e['name']}' -> {e['targetConcept']} -- left as proposed.")

    def update_topic_registry(self):
        by_slug = {t["slug"]: t for t in self.registry}
        for rec in self.topic_records:
            slug = slugify(rec["name"])
            if slug in by_slug:
                if self.series_code not in by_slug[slug]["series"]:
                    by_slug[slug]["series"].append(self.series_code)
            else:
                entry = {"slug": slug, "name_en": rec["name"], "description_en": rec["description"],
                         "series": [self.series_code]}
                self.registry.append(entry)
                by_slug[slug] = entry
        save_topic_registry(self.registry, self.registry_path)
        self.log(f"Updated topic registry: {len(self.registry)} topics total across all series built so far.")

    # --- output -----------------------------------------------------------------
    @staticmethod
    def _shown(path):
        try:
            return os.path.relpath(path)
        except ValueError:
            return str(path)

    def write_outputs(self, ttl_path, proposals_path, topics_path, log_path):
        ttl_path, proposals_path = Path(ttl_path), Path(proposals_path)
        topics_path, log_path = Path(topics_path), Path(log_path)
        for p in (ttl_path, proposals_path, topics_path, log_path):
            p.parent.mkdir(parents=True, exist_ok=True)
        self.g.serialize(destination=str(ttl_path), format="turtle")
        self.log(f"Wrote {self._shown(ttl_path)} -- {len(self.g)} triples.")

        proposals_path.write_text(json.dumps(self.E3, ensure_ascii=False, indent=2))
        self.log(f"Wrote {self._shown(proposals_path)} -- {len(self.E3)} records.")

        with open(topics_path, "w") as f:
            f.write(f"# {self.series_code} topic dictionary\n\n")
            f.write("Every topic instance found, with its `E3` merge/mapping outcome shown inline.\n\n")
            f.write("| Recording | Topic | Merge candidate? | Concept mapping? |\n|---|---|---|---|\n")
            for rec in self.topic_records:
                merges = [e for e in self.E3 if e["type"] == "topic_merge"
                          and (e["topicId_a"] == str(rec["node"]) or e["topicId_b"] == str(rec["node"]))]
                concepts = [e for e in self.E3 if e["type"] == "topic_concept_mapping"
                            and e["topicId"] == str(rec["node"])]
                merge_str = "; ".join(
                    f"~{(e['name_b'] if e['topicId_a']==str(rec['node']) else e['name_a'])} "
                    f"({e['lexicalSimilarity']}, {e['status']})" for e in merges) or "-"
                concept_str = "; ".join(f"{e['targetConcept']} ({e['status']})" for e in concepts) or "-"
                f.write(f"| {rec['recording']} | {rec['name']} | {merge_str} | {concept_str} |\n")
        self.log(f"Wrote {self._shown(topics_path)}.")

        log_path.write_text("\n".join(self.BUILD_LOG))
        self.update_topic_registry()
