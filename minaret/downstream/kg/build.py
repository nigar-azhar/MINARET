"""Build one series' KG instance data (ABox) from its reviewed V3 transcripts + E2 entity sets.

Input per series:
  - artifacts/kg/series/<SERIES>.json  -- series/speaker/recording metadata plus every recorded
    human decision on the builder's topic proposals (reviewed_merges, reviewed_concepts,
    topic_related, hub_related, manual_concept_matches).
  - <recordings_root>/<recordings_dir>/<recording_id>/{v3.json, e2.json}

Output per series (under --out, default artifacts/kg):
  instances/<SERIES>.ttl, series/<SERIES>_topic_proposals.json, series/<SERIES>_topics.md,
  series/<SERIES>_build_log.txt, and the shared topic_registry.json.

Series are built in the order given; the topic registry carries topics forward so later series
see cross-series merge candidates against earlier ones. Cross-series proposals only affect the
proposals file -- a merge is only ever applied when both topics are in the same series' run.

E2 topic handling: the released e2.json files already carry the reviewed topic curation (splits,
renames onto a canonical cross-series topic, exclusions, and Urdu names/descriptions). A topic
with `renamed_from` gets that original name as a skos:altLabel, exactly as the rename did at
curation time.
"""
from __future__ import annotations

import json
from pathlib import Path

from rdflib import Literal, XSD
from rdflib.namespace import SKOS

from minaret.downstream.kg.common import (
    HADITH, MIN, RDF, KGBuilder, duration_to_seconds, expand_ayat_ranges, extent_type_node,
    our_ref_to_kg_id, slugify, timestamp_overlap, uri_safe, usage_type_node,
)
from minaret.downstream.kg.hadith_blocks import extract_blocks


def load_series_config(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _recording_dir(recordings_root: Path, cfg: dict, rec: dict) -> Path:
    return Path(recordings_root) / cfg["recordings_dir"] / rec["recording_id"]


def cited_hadith_kg_ids(configs: list[dict], recordings_root: Path) -> set[str]:
    ids = set()
    for cfg in configs:
        for rec in cfg["recordings"]:
            e2 = json.loads((_recording_dir(recordings_root, cfg, rec) / "e2.json").read_text(encoding="utf-8"))
            for h in e2.get("hadith", []):
                kg_id = our_ref_to_kg_id(h["reference"])
                if kg_id:
                    ids.add(kg_id)
    return ids


def build_series(cfg: dict, *, recordings_root: Path, out_dir: Path, quran_csv: Path, duas_csv: Path,
                 raw_hadith_blocks: dict, registry_path: Path) -> KGBuilder:
    code = cfg["series_code"]
    out_dir = Path(out_dir)
    b = KGBuilder(code, quran_csv=quran_csv, duas_csv=duas_csv, raw_hadith_blocks=raw_hadith_blocks,
                  registry_path=registry_path, out_dir=out_dir)
    g = b.g

    s = cfg["series"]
    series_node = MIN[f"AudioSeries_{code}"]
    g.add((series_node, RDF.type, MIN.AudioSeries))
    g.add((series_node, MIN.seriesCode, Literal(code)))
    g.add((series_node, MIN.titleEn, Literal(s["title_en"])))
    g.add((series_node, MIN.titleUr, Literal(s["title_ur"])))
    g.add((series_node, MIN.category, Literal(cfg["category"])))
    g.add((series_node, MIN.categoryId, Literal(int(s["category_id"]), datatype=XSD.integer)))
    g.add((series_node, MIN.seriesType, Literal(s["series_type"])))

    sp = cfg["speaker"]
    speaker_node = MIN[f"Speaker_{sp['code']}"]
    g.add((speaker_node, RDF.type, MIN.Speaker))
    g.add((speaker_node, MIN.speakerCode, Literal(sp["code"])))
    g.add((speaker_node, MIN.nameEn, Literal(sp["name_en"])))
    if sp.get("name_ur"):
        g.add((speaker_node, MIN.nameUr, Literal(sp["name_ur"])))

    lang = cfg["language"]
    lang_node = MIN[lang["label"]]
    g.add((lang_node, RDF.type, MIN.Language))
    g.add((lang_node, MIN.languageCode, Literal(lang["code"])))
    g.add((lang_node, MIN.label, Literal(lang["label"])))

    for rec in cfg["recordings"]:
        base = _recording_dir(recordings_root, cfg, rec)
        gold = json.loads((base / "v3.json").read_text(encoding="utf-8"))
        e2 = json.loads((base / "e2.json").read_text(encoding="utf-8"))
        if isinstance(gold, dict) and "segments" in gold:
            gold = gold["segments"]
        short_id = rec["kg_recording_id"]
        audio = rec["audio"]

        ayat_expanded = expand_ayat_ranges(e2.get("ayat", []))

        rec_node = MIN[f"Recording_{short_id}"]
        g.add((rec_node, RDF.type, MIN.Recording))
        g.add((rec_node, MIN.recordingId, Literal(short_id)))
        g.add((series_node, MIN.hasRecording, rec_node))
        g.add((rec_node, MIN.hasPrimarySpeaker, speaker_node))
        g.add((rec_node, MIN.hasPrimaryLanguage, lang_node))

        audio_node = MIN[f"Audio_{short_id}"]
        g.add((audio_node, RDF.type, MIN.Audio))
        g.add((audio_node, MIN.url, Literal(audio["audio_link"], datatype=XSD.anyURI)))
        g.add((audio_node, MIN.titleEn, Literal(audio["english_name"])))
        g.add((audio_node, MIN.titleUr, Literal(audio["urdu_name"])))
        dur = duration_to_seconds(audio.get("duration"))
        if dur is not None:
            g.add((audio_node, MIN.durationSeconds, Literal(dur, datatype=XSD.decimal)))
        if audio.get("upload_date"):
            g.add((audio_node, MIN.uploadDate, Literal(audio["upload_date"], datatype=XSD.date)))
        g.add((rec_node, MIN.hasAudio, audio_node))

        transcript_node = MIN[f"Transcript_{short_id}"]
        g.add((transcript_node, RDF.type, MIN.Transcript))
        g.add((rec_node, MIN.hasTranscript, transcript_node))

        seg_nodes = []
        prev_seg_node = None
        for i, seg in enumerate(gold):
            seg_node = MIN[f"Segment_{short_id}_{i:04d}"]
            g.add((seg_node, RDF.type, MIN.TranscriptSegment))
            g.add((seg_node, MIN.sequenceIndex, Literal(i, datatype=XSD.integer)))
            g.add((seg_node, MIN.startTime, Literal(seg["start"], datatype=XSD.decimal)))
            g.add((seg_node, MIN.endTime, Literal(seg["end"], datatype=XSD.decimal)))
            g.add((seg_node, MIN.text, Literal(seg["text"])))
            g.add((transcript_node, MIN.hasSegment, seg_node))
            if prev_seg_node is not None:
                g.add((prev_seg_node, MIN.precedesSegment, seg_node))
            prev_seg_node = seg_node
            seg_nodes.append((seg["start"], seg["end"], seg_node))

        def make_segment_group(start, end, seg_nodes=seg_nodes, short_id=short_id):
            overlapping = [n for (s_, e_, n) in seg_nodes if timestamp_overlap(start, end, s_, e_)]
            sg_node = MIN[f"SegmentGroup_{short_id}_{start}_{end}".replace(".", "_")]
            g.add((sg_node, RDF.type, MIN.SegmentGroup))
            g.add((sg_node, MIN.startTime, Literal(start, datatype=XSD.decimal)))
            g.add((sg_node, MIN.endTime, Literal(end, datatype=XSD.decimal)))
            for n in overlapping:
                g.add((sg_node, MIN.containsSegment, n))
            return sg_node

        for h in e2.get("headings", []):
            h_node = MIN[f"Heading_{short_id}_{h['start']}".replace(".", "_")]
            g.add((h_node, RDF.type, MIN.Heading))
            g.add((h_node, MIN.titleEn, Literal(h["title_en"])))
            g.add((h_node, MIN.titleUr, Literal(h["title_ur"])))
            g.add((h_node, MIN.startTime, Literal(h["start"], datatype=XSD.decimal)))
            g.add((h_node, MIN.endTime, Literal(h["end"], datatype=XSD.decimal)))
            g.add((rec_node, MIN.hasHeading, h_node))

        for i, a in enumerate(ayat_expanded):
            sg = make_segment_group(a["start"], a["end"])
            # Index prefix guarantees uniqueness: the same ayah can be cited twice at the same
            # timestamp with different usage/text (e.g. quotation immediately followed by its
            # translation in one detected span).
            occ = MIN[f"VerseOccurrence_{short_id}_{i:04d}_{a['start']}_{a['surah_number']}_{a['ayah_number']}".replace(".", "_")]
            g.add((occ, RDF.type, MIN.VerseOccurrence))
            g.add((occ, MIN.evidenceText, Literal(a["text"])))
            g.add((occ, MIN.startTime, Literal(a["start"], datatype=XSD.decimal)))
            g.add((occ, MIN.endTime, Literal(a["end"], datatype=XSD.decimal)))
            g.add((occ, MIN.hasUsageType, usage_type_node(a["usage"])))
            g.add((occ, MIN.hasExtentType, extent_type_node(a["extent"])))
            g.add((occ, MIN.occursIn, sg))
            g.add((occ, MIN.refersTo, b.get_ayah_node(int(a["surah_number"]), int(a["ayah_number"]))))

        for i, h in enumerate(e2.get("hadith", [])):
            sg = make_segment_group(h["start"], h["end"])
            occ = MIN[f"HadithOccurrence_{short_id}_{i:04d}_{h['start']}_{uri_safe(h['reference'])}".replace(".", "_")]
            g.add((occ, RDF.type, MIN.HadithOccurrence))
            g.add((occ, MIN.evidenceText, Literal(h["text"])))
            g.add((occ, MIN.startTime, Literal(h["start"], datatype=XSD.decimal)))
            g.add((occ, MIN.endTime, Literal(h["end"], datatype=XSD.decimal)))
            g.add((occ, MIN.hasUsageType, usage_type_node(h["usage"])))
            g.add((occ, MIN.occursIn, sg))
            g.add((occ, MIN.refersTo, b.get_hadith_node(h["reference"], h.get("expanded_reference") or h["reference"])))

        for i, d in enumerate(e2.get("dua", [])):
            sg = make_segment_group(d["start"], d["end"])
            occ = MIN[f"DuaOccurrence_{short_id}_{i:04d}_{d['start']}_{uri_safe(d['reference'])}".replace(".", "_")]
            g.add((occ, RDF.type, MIN.DuaOccurrence))
            g.add((occ, MIN.evidenceText, Literal(d["text"])))
            g.add((occ, MIN.startTime, Literal(d["start"], datatype=XSD.decimal)))
            g.add((occ, MIN.endTime, Literal(d["end"], datatype=XSD.decimal)))
            g.add((occ, MIN.hasUsageType, usage_type_node(d["usage"])))
            g.add((occ, MIN.hasExtentType, extent_type_node(d["extent"])))
            g.add((occ, MIN.occursIn, sg))
            g.add((occ, MIN.refersTo, b.get_dua_node(d["reference"])))

        for t in e2.get("topics", []):
            name_en = t.get("name_en") or t.get("name")
            desc_en = t.get("description_en") or t.get("description")
            sg = make_segment_group(t["start"], t["end"])
            t_node = b.get_topic_node(name_en, desc_en, t.get("name_ur"), t.get("description_ur"), short_id)
            if t.get("renamed_from"):
                g.add((t_node, SKOS.altLabel, Literal(t["renamed_from"])))
            g.add((sg, MIN.discussesTopic, t_node))

    reviewed_merges = {frozenset(m["topics"]): m["decision"] for m in cfg.get("reviewed_merges", [])}
    reviewed_concepts = {(c["topic"], c["concept"]): c["decision"] for c in cfg.get("reviewed_concepts", [])}
    b.run_topic_dedup(cfg.get("concept_keywords", {}))
    b.apply_reviewed_decisions(reviewed_merges, reviewed_concepts)
    _apply_manual_relations(b, cfg)

    b.write_outputs(out_dir / "instances" / f"{code}.ttl",
                    out_dir / "series" / f"{code}_topic_proposals.json",
                    out_dir / "series" / f"{code}_topics.md",
                    out_dir / "series" / f"{code}_build_log.txt")
    return b


def _apply_manual_relations(b: KGBuilder, cfg: dict) -> None:
    """Settled reviewer decisions that are asserted directly rather than proposed."""
    g = b.g
    node_by_name = {}
    for rec in b.topic_records:
        node_by_name.setdefault(rec["name"], rec["node"])

    for name_a, name_b in cfg.get("topic_related", []):
        if name_a in node_by_name and name_b in node_by_name:
            a, c = node_by_name[name_a], node_by_name[name_b]
            g.add((a, SKOS.related, c))
            g.add((c, SKOS.related, a))
            b.log(f"Topic relation ADDED: '{name_a}' skos:related '{name_b}'.")
        else:
            b.log(f"WARNING: could not add topic relation '{name_a}' <-> '{name_b}' -- "
                  "one or both names not found among this run's topics.")

    hub_cfg = cfg.get("hub_related")
    if hub_cfg:
        # The hub may live in another series' graph; its IRI is derived from its name.
        hub = MIN[f"Topic_{slugify(hub_cfg['hub'])}"]
        for name in hub_cfg["members"]:
            if name in node_by_name:
                g.add((node_by_name[name], SKOS.related, hub))
                g.add((hub, SKOS.related, node_by_name[name]))
                b.log(f"Topic relation ADDED (reviewer decision): '{name}' skos:related '{hub_cfg['hub']}'.")
            else:
                b.log(f"WARNING: could not relate '{name}' to hub -- not found among this run's topics.")

    for m in cfg.get("manual_concept_matches", []):
        if m["topic"] in node_by_name:
            pred = SKOS.exactMatch if m["match"] == "exactMatch" else SKOS.closeMatch
            g.add((node_by_name[m["topic"]], pred, HADITH[m["concept"].split(":", 1)[1]]))
            b.log(f"Topic concept mapping ADDED (reviewer decision): '{m['topic']}' {m['match']} {m['concept']}.")


def build_all(series_configs: list[Path], *, recordings_root: Path, out_dir: Path, quran_csv: Path,
              duas_csv: Path, hadith_dump: Path, cache_dir: Path | None = None,
              fresh_registry: bool = True) -> list[KGBuilder]:
    configs = [load_series_config(p) for p in series_configs]
    registry_path = Path(out_dir) / "topic_registry.json"
    if fresh_registry and registry_path.exists():
        registry_path.unlink()
    kg_ids = cited_hadith_kg_ids(configs, recordings_root)
    raw_blocks = extract_blocks(hadith_dump, kg_ids, cache_dir=cache_dir)
    return [build_series(cfg, recordings_root=recordings_root, out_dir=out_dir, quran_csv=quran_csv,
                         duas_csv=duas_csv, raw_hadith_blocks=raw_blocks, registry_path=registry_path)
            for cfg in configs]
