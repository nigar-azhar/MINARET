"""The MINARET landing page: the reviewer panel's home screen (/) and a standalone copy.

Every example on the page is read from the released artifacts: one segment's V0-V3 text, its
entity in E2, the knowledge-graph nodes it produced and a graded RAG answer from RQ5. The panel
serves them at /api/landing; the standalone copy (for GitHub Pages or any static host) ships them
as landing.json:

    python -m reviewer_panel.landing --out docs
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Optional

from minaret.config import REPO_ROOT

STATIC = Path(__file__).resolve().parent / "static"
ARTIFACTS = REPO_ROOT / "artifacts"
EVALUATION = REPO_ROOT / "evaluation"

PAPER = {
    "title": "MINARET: From Multilingual Audios to Knowledge Graphs via LLM-Assisted Semantic Enrichment",
    "url": None,  # set once the paper is public; the page shows the link only when this is set
    "authors": [
        {"name": "Nigar Azhar Butt", "orcid": "0009-0009-7560-1023"},
        {"name": "Amna Binte Kamran", "orcid": "0009-0003-1397-4912"},
        {"name": "Amna Basharat", "orcid": "0000-0002-5744-6498"},
    ],
    "affiliation": "FAST National University of Computer and Emerging Sciences, Islamabad, Pakistan",
}
REPO_URL: Optional[str] = "https://github.com/nigar-azhar/MINARET"

# The two walkthrough segments. `notes` describe what each stage did to this segment; each was
# checked against the files named here.
EXAMPLES = [
    {
        "id": "ur", "label": "Urdu lecture", "series_dir": "TQ2005", "recording": "TQ2005-P01-L001F",
        "v2_index": 85, "surah": 40, "ayah": 16, "surah_name": "Ghafir (al-Mu'min)",
        "rag": {"model": "gemma4e4b", "answer": "Q35"},
        "notes": {
            "asr": "Whisper hears the Arabic without its vowel marks and mishears two words: "
                   "القحار for القهار, and على الله run together as علاللہ.",
            "correct": "The correction model restores the Arabic, adds its diacritics and marks the quotation.",
            "validate": "The quotation is matched to Surah Ghafir 40:16 in the Quran corpus and replaced with "
                        "the canonical text.",
            "review": "The reviewer accepts the ayah as a complete quotation and corrects a pause mark and one "
                      "letter form in the quotation.",
        },
    },
    {
        "id": "en", "label": "English lecture", "series_dir": "HajjJourney2022Eng", "recording": "HajjJourney2022Eng-L04",
        "v2_index": 9, "surah": 2, "ayah": 197, "surah_name": "Al-Baqarah",
        "rag": {"model": "gemma4e4b", "answer": "Q5", "refusal": "Q8"},
        "notes": {
            "asr": "The lecturer recites Al-Baqarah 2:197 before explaining it in English. Whisper hears this "
                   "part of the recitation correctly.",
            "correct": "Here the correction model makes it worse: رَفَثَ becomes رَفَسَ and فُسُوقَ becomes فُتُوْقَ.",
            "validate": "Corpus validation matches the verse to Al-Baqarah 2:197 and puts back the canonical "
                        "wording, undoing the model's errors.",
            "review": "The reviewer moves الْحَجَّ back to the previous segment, where its sentence begins, and "
                      "accepts the ayah as a complete quotation.",
        },
    },
]


def _load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data["segments"] if isinstance(data, dict) and "segments" in data else data


def _overlap(a: dict, b: dict) -> float:
    return min(a["end"], b["end"]) - max(a["start"], b["start"])


def _series_config(series_dir: str) -> dict:
    for f in sorted((ARTIFACTS / "kg" / "series").glob("*.json")):
        if f.stem.endswith("_topic_proposals"):
            continue
        cfg = json.loads(f.read_text(encoding="utf-8"))
        if cfg.get("recordings_dir") == series_dir:
            return cfg
    raise FileNotFoundError(f"No series config for {series_dir}")


_verse_cache: dict[str, dict] = {}


def _verse_node(series_code: str, surah: int, ayah: int) -> dict:
    """The QuranVerse node from the released KG: its links and English translation."""
    key = f"{series_code}:{surah}:{ayah}"
    if key in _verse_cache:
        return _verse_cache[key]
    node = {"iri": f"http://minaret-eval.org/ontology#QuranVerse_{surah}_{ayah}",
            "exact_match": [f"http://quranontology.com/Resource/quran{surah}-{ayah}",
                            f"http://www.semantictafsir.com/ontology/V{surah:03d}_{ayah:03d}"],
            "translation_en": None}
    ttl = ARTIFACTS / "kg" / "instances" / f"{series_code}.ttl"
    try:
        import rdflib
        from rdflib.namespace import SKOS

        g = rdflib.Graph()
        g.parse(ttl)
        subject = rdflib.URIRef(node["iri"])
        matches = sorted(str(o) for o in g.objects(subject, SKOS.exactMatch))
        node["exact_match"] = matches or node["exact_match"]
        for p, o in g.predicate_objects(subject):
            if str(p).endswith("translationEn") and str(o).strip():
                node["translation_en"] = str(o)
    except Exception:  # noqa: BLE001 - rdflib missing or TTL absent: the fixed link pattern still holds
        pass
    _verse_cache[key] = node
    return node


def _rag(recording: str, spec: dict) -> dict:
    reviews = json.loads((EVALUATION / "rq5_rag" / "reviews" / f"{recording}__{spec['model']}.json")
                         .read_text(encoding="utf-8"))
    by_id = {r["question_id"]: r for r in reviews}
    chunks = json.loads((ARTIFACTS / "rag" / "index" / recording / "chunks.json").read_text(encoding="utf-8"))
    chunks = chunks["chunks"] if isinstance(chunks, dict) else chunks
    chunk_by_id = {c["chunk_id"]: c for c in chunks}

    def item(qid: str) -> dict:
        r = by_id[qid]
        cited = [chunk_by_id[c] for c in r["citation"]["cited_chunk_ids"] if c in chunk_by_id]
        return {"question": r["question"], "language": r["question_language"], "answer": r["generated_answer"],
                "model": r["generation_model"], "verdict": r["answer_verdict"],
                "chunks": [{"id": c["chunk_id"], "start": c["start"], "end": c["end"], "text": c["text"]} for c in cited]}

    out = {"answer": item(spec["answer"])}
    if spec.get("refusal"):
        out["refusal"] = item(spec["refusal"])
    return out


def build_example(spec: dict) -> dict:
    d = ARTIFACTS / "recordings" / spec["series_dir"] / spec["recording"]
    v = {k: _load(d / f"{k}.json") for k in ("v0", "v1", "v2", "v3")}
    s2 = v["v2"][spec["v2_index"]]
    seg = {"v0": max(v["v0"], key=lambda s: _overlap(s, s2)), "v1": v["v1"][spec["v2_index"]], "v2": s2,
           "v3": max(v["v3"], key=lambda s: _overlap(s, s2))}
    e1 = json.loads((d / "e1.json").read_text(encoding="utf-8"))
    e2 = json.loads((d / "e2.json").read_text(encoding="utf-8"))

    def the_ayah(entities):
        hits = [a for a in entities["ayat"] if str(a.get("surah_number")) == str(spec["surah"])
                and str(a.get("ayah_number")) == str(spec["ayah"]) and _overlap(a, s2) > 0]
        return hits[0] if hits else None

    ayah_e1, ayah_e2 = the_ayah(e1), the_ayah(e2)
    source = json.loads((d / "source.json").read_text(encoding="utf-8"))
    cfg = _series_config(spec["series_dir"])
    covering = lambda kind: [t for t in e2.get(kind, []) if t["start"] < s2["end"] and t["end"] > s2["start"]]  # noqa: E731
    return {
        "id": spec["id"], "label": spec["label"], "notes": spec["notes"], "language": cfg["language"]["code"],
        "recording": {"id": spec["recording"], "kg_id": source.get("kg_recording_id"),
                      "title_en": source.get("title_en"), "title_ur": source.get("title_ur"),
                      "series_en": cfg["series"]["title_en"], "series_ur": cfg["series"]["title_ur"],
                      "series_code": cfg["series_code"], "speaker_en": cfg["speaker"]["name_en"],
                      "speaker_ur": cfg["speaker"]["name_ur"], "audio_url": source.get("audio_url")},
        "segment": {"start": s2["start"], "end": s2["end"],
                    "text": {k: seg[k]["text"] for k in seg},
                    "time": {k: [seg[k]["start"], seg[k]["end"]] for k in seg}},
        "ayah": {"surah": spec["surah"], "ayah": spec["ayah"], "surah_name": spec["surah_name"],
                 "e1": {k: ayah_e1.get(k) for k in ("text", "usage", "extent")} if ayah_e1 else None,
                 "e2": {k: ayah_e2.get(k) for k in ("text", "usage", "extent", "start", "end")} if ayah_e2 else None,
                 "kg": _verse_node(cfg["series_code"], spec["surah"], spec["ayah"])},
        "topics": [{k: t.get(k) for k in ("name_en", "name_ur", "name", "start", "end")} for t in covering("topics")],
        "headings": [{k: t.get(k) for k in ("title_en", "title_ur", "start", "end")} for t in covering("headings")],
        "rag": _rag(spec["recording"], spec["rag"]),
    }


def _released() -> dict:
    series = []
    for f in sorted((ARTIFACTS / "kg" / "series").glob("*.json")):
        if f.stem.endswith("_topic_proposals"):
            continue
        cfg = json.loads(f.read_text(encoding="utf-8"))
        series.append({"title_en": cfg["series"]["title_en"], "title_ur": cfg["series"]["title_ur"],
                       "language": cfg["language"]["label"], "speaker": cfg["speaker"]["name_en"],
                       "recordings": len(cfg["recordings"])})
    return {"series": series, "recordings": sum(s["recordings"] for s in series)}


_built: Optional[dict] = None


def build(mode: str = "panel") -> dict:
    global _built
    if _built is None:
        _built = {"paper": PAPER, "repo_url": REPO_URL, "examples": [build_example(s) for s in EXAMPLES],
                  "released": _released()}
    return {**_built, "mode": mode}


def export(out: Path) -> None:
    """Write a self-contained copy of the landing page to `out` (e.g. docs/ for GitHub Pages)."""
    out.mkdir(parents=True, exist_ok=True)
    html = (STATIC / "landing.html").read_text(encoding="utf-8")
    html = html.replace('content="/api/landing"', 'content="landing.json"')
    (out / "index.html").write_text(html, encoding="utf-8")
    for name in ("landing.css", "landing.js", "minaret-mark.svg"):
        shutil.copyfile(STATIC / name, out / name)
    (out / "landing.json").write_text(json.dumps(build("static"), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Export the MINARET landing page as static files")
    p.add_argument("--out", type=Path, required=True, help="Output directory, e.g. docs")
    args = p.parse_args(argv)
    export(args.out)
    print(f"Landing page written to {args.out}/index.html")


if __name__ == "__main__":
    main()
