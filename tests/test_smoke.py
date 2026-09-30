"""Smoke tests. No network, no LLM server, no audio: LLM calls and embeddings are faked.

Tests needing optional dependencies (rdflib, the non-redistributed corpora) skip themselves when
those are absent. The full reproduction check is `python evaluation/run_all.py`; test_reproduction
asserts the headline paper numbers from it.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "artifacts"
SMALL = ("TQ2005", "TQ2005-P01-L001C")  # 12-segment recording, fast everywhere
CORPORA = [ART / "corpora" / f for f in ("quran.csv", "duas.csv", "SemanticHadithKG.rdf.zip")]


def _rec(series=SMALL[0], rec=SMALL[1]):
    return ART / "recordings" / series / rec


# ---------------------------------------------------------------- configuration

def test_config_resolves_endpoint_key_and_overrides(tmp_path, monkeypatch):
    from minaret import config
    (tmp_path / "minaret.yaml").write_text(
        "llm:\n  correction:\n    base_url: http://example.test/v1\n    model: m1\n"
        "    api_key_env: TEST_MINARET_KEY\n    prompt: p.txt\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TEST_MINARET_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("TEST_MINARET_KEY", raising=False)
    cfg = config.load(tmp_path / "minaret.yaml")
    ep = cfg.llm("correction")
    assert (ep.base_url, ep.model, ep.api_key) == ("http://example.test/v1", "m1", "from-dotenv")
    assert ep.prompt == (tmp_path / "p.txt").resolve()
    assert cfg.llm("correction", model="m2").model == "m2"
    with pytest.raises(ValueError):
        cfg.llm("extraction")  # not configured -> actionable error


def test_shipped_config_points_at_shipped_prompts():
    from minaret import config
    cfg = config.load(REPO / "minaret.yaml")
    for stage in config.LLM_STAGES:
        assert cfg.llm(stage).prompt.is_file(), stage


# ---------------------------------------------------------------- artifact layout

def test_every_recording_has_all_six_artifacts():
    recs = [d for s in (ART / "recordings").iterdir() for d in s.iterdir() if d.is_dir()]
    assert len(recs) == 18
    for d in recs:
        for name in ("v0", "v1", "v2", "v3", "e1", "e2"):
            assert (d / f"{name}.json").is_file(), d / name
        assert json.loads((d / "source.json").read_text())["audio_url"].startswith("http")


def test_released_v3_e2_pass_reviewed_input_validation():
    from minaret.pipeline.ingest_reviewed import load_v3, validate
    for d in (d for s in (ART / "recordings").iterdir() for d in s.iterdir() if d.is_dir()):
        validate(load_v3(d / "v3.json"), json.loads((d / "e2.json").read_text()))


def test_reviewed_input_rejects_broken_e2(tmp_path):
    from minaret.pipeline.ingest_reviewed import ReviewedInputError, ingest
    bad = json.loads((_rec() / "e2.json").read_text())
    bad["ayat"] = [{"surah_number": "1", "text": "x", "start": 0, "end": 1, "usage": "quotation", "extent": "complete"}]
    (tmp_path / "bad_e2.json").write_text(json.dumps(bad))
    with pytest.raises(ReviewedInputError, match="ayah_number"):
        ingest(tmp_path / "rec", v3_path=_rec() / "v3.json", e2_path=tmp_path / "bad_e2.json")


# ---------------------------------------------------------------- pipeline stages (faked LLM)

def test_correction_and_extraction_with_fake_llm(monkeypatch):
    from minaret.pipeline import correct, extract_entities
    from minaret.schemas import Segment
    v0 = json.loads((_rec() / "v0.json").read_text())[:3]
    segs = [Segment(id=str(i), start=s["start"], end=s["end"], text=s["text"]) for i, s in enumerate(v0)]

    monkeypatch.setattr(correct, "_call_llm", lambda *a, **k: json.dumps({"text": a[4]}))
    v1, prov = correct.correct(segs, base_url="http://fake", model="fake")
    assert [s.text for s in v1] == [s.text for s in segs] and prov["model"] == "fake"

    reply = {"ayat": [{"text": "بِسْمِ اللّٰهِ", "surah_number": 1, "ayah_number": 1, "usage": "quotation"}],
             "hadith": [], "dua": [], "topics": [{"name": "Test topic"}]}
    monkeypatch.setattr(extract_entities, "_call_llm", lambda *a, **k: json.dumps(reply))
    ents, _ = extract_entities.extract(v1, base_url="http://fake", model="fake")
    assert len(ents.ayat) == 3 and ents.ayat[0].key and len(ents.topics) == 3


# ---------------------------------------------------------------- RAG

def test_chunker_reproduces_every_shipped_lecture_index():
    from minaret.downstream.rag.chunk import chunk_segments
    for manifest_path in (ART / "rag" / "index").glob("*/chunks.json"):
        m = json.loads(manifest_path.read_text())
        v3 = json.loads((REPO / m["source_gold_file"]).read_text())
        got = [(c["text"], c["start"], c["end"]) for c in chunk_segments(v3)]
        assert got == [(c["text"], c["start"], c["end"]) for c in m["chunks"]], m["lecture_id"]


def test_rag_index_and_mock_query_end_to_end(tmp_path, monkeypatch):
    from minaret.downstream.rag import index, query
    shipped = np.load(ART / "rag" / "index" / SMALL[1] / "embeddings.npy")
    fake_embed = lambda texts: np.repeat(shipped[:1], len(texts), axis=0)  # noqa: E731
    index.build_lecture_index(_rec() / "v3.json", series=SMALL[0], recording_id=SMALL[1],
                              index_root=tmp_path / "index", embed_fn=fake_embed)
    index.build_series_index(SMALL[0], index_root=tmp_path / "index")
    monkeypatch.setattr(query, "rerank", lambda q, c: ([(ch, e, e) for ch, e in c], "fallback_embedding_order"))
    manifest, emb = query.load_index(tmp_path / "index", scope="series", series=SMALL[0])
    out = query.run_questions([{"question_id": "Q1", "question": "?"}], scope="series", scope_label=SMALL[0],
                              manifest=manifest, embeddings=emb, trace_root=tmp_path / "traces",
                              endpoint=None, system_prompt="p", mock=True, embed_fn=fake_embed)
    rec = json.loads(out.read_text())[0]
    assert rec["generated_answer"].startswith("[MOCK") and len(rec["chunks_sent_to_model"]) == 3


# ---------------------------------------------------------------- KG

@pytest.mark.skipif(not all(p.exists() for p in CORPORA), reason="corpora not present (see artifacts/corpora/README.md)")
def test_kg_build_reproduces_shipped_series(tmp_path):
    pytest.importorskip("rdflib")
    from rdflib import Graph
    from rdflib.compare import isomorphic
    from minaret.downstream.kg.build import build_all
    build_all([ART / "kg" / "series" / "TQ2005.json"], recordings_root=ART / "recordings", out_dir=tmp_path,
              quran_csv=CORPORA[0], duas_csv=CORPORA[1], hadith_dump=CORPORA[2], cache_dir=ART / "corpora" / "cache")
    assert isomorphic(Graph().parse(tmp_path / "instances" / "TQ2005.ttl"),
                      Graph().parse(ART / "kg" / "instances" / "TQ2005.ttl"))


# ---------------------------------------------------------------- paper numbers

def _run(script, out):
    subprocess.run([sys.executable, str(REPO / "evaluation" / script), "--out", str(out)], check=True,
                   capture_output=True)
    return out


def test_reproduction_rq1_rq2_rq3(tmp_path):
    rq1 = json.loads((_run("rq1_transcripts/compute.py", tmp_path / "rq1") / "rq1_metrics.json").read_text())
    pooled = rq1["by_series"]["ALL"]
    assert [round(pooled["cer"][v] * 100, 2) for v in ("v0", "v1", "v2")] == [10.72, 6.03, 4.74]
    assert round(pooled["rer_cer"]["v0_v2"], 1) == 55.8

    rq2 = json.loads((_run("rq2_entities/compute.py", tmp_path / "rq2") / "rq2_entity_accuracy.json").read_text())
    ayat = rq2["by_series"]["ALL"]["ayat"]["entity"]
    assert [round(ayat[k] * 100, 1) for k in ("precision", "recall", "f1")] == [92.5, 82.8, 87.4]

    rq3 = json.loads((_run("rq3_review_effort/compute.py", tmp_path / "rq3") / "rq3_review_effort.json").read_text())
    assert round(rq3["by_series"]["ALL"]["rtf"], 2) == 5.24


def test_reproduction_rq4_rq5(tmp_path):
    pytest.importorskip("rdflib")
    rq4 = json.loads((_run("rq4_kg/compute.py", tmp_path / "rq4") / "rq4_kg.json").read_text())
    assert rq4["statistics"]["knowledge_graph"]["total_triples"] == 54388
    assert all(v["row_count"] > 0 for v in rq4["competency_questions"].values())
    out = _run("rq5_rag/compute.py", tmp_path / "rq5")  # exits non-zero on any metric mismatch
    assert json.loads((out / "lecture_scope.json").read_text())["total_questions"] == 216


def test_reproduction_asr_model_selection(tmp_path):
    res = json.loads((_run("asr_model_selection/compute.py", tmp_path / "asr") / "asr_model_selection.json").read_text())
    best = res["aggregate"][0]
    assert (best["backend"], best["model"]) == ("faster_whisper", "large-v3-turbo")
    assert round(best["mean_cer"] * 100, 2) == 6.26 and best["total_word_deletions"] == 344


def test_llm_json_reply_tolerates_think_blocks_and_fences():
    import json as _json

    import pytest as _pytest

    from minaret.pipeline.llm_json import parse_json_reply

    assert parse_json_reply('{"text": "a"}') == {"text": "a"}
    assert parse_json_reply('<think>\nlet me see {x}\n</think>\n{"text": "a"}') == {"text": "a"}
    assert parse_json_reply('```json\n{\n  "text": "ب"\n}\n```') == {"text": "ب"}
    assert parse_json_reply('Here it is: {"ayat": []} hope that helps') == {"ayat": []}
    with _pytest.raises(_json.JSONDecodeError):
        parse_json_reply("no json here")


def test_rank_candidates_embeds_corpus_once_and_matches_pairwise_scores():
    from minaret.pipeline import corpus_validate as cv

    calls = []

    def fake_embed(texts):
        calls.append(len(texts))
        return [[float(len(t)), float(t.count("ا")) + 1.0, 1.0] for t in texts]

    corpus = [cv.CorpusRow(key=f"K{i}", text=t) for i, t in enumerate(["بسم الله", "الحمد لله رب", "قل هو الله احد"])]
    ranked = cv.rank_candidates("الحمد لله", corpus, alpha=0.7, embed_fn=fake_embed)
    pairwise = sorted(((cv.match_score("الحمد لله", r.text, alpha=0.7, embed_fn=fake_embed), r.key) for r in corpus),
                      reverse=True)
    assert [r.row.key for r in ranked] == [k for _, k in pairwise]
    assert all(abs(r.score - s) < 1e-6 for r, (s, _) in zip(ranked, pairwise))
    calls.clear()
    cv.rank_candidates("قل هو", corpus, alpha=0.7, embed_fn=fake_embed)
    assert calls == [1]  # corpus vectors reused; only the query is embedded


def test_extraction_keeps_every_field_the_prompt_asks_for(monkeypatch):
    import json as _json

    from minaret.pipeline import extract_entities as ex
    from minaret.schemas import Segment

    reply = {  # shaped exactly like the JSON object entity_extraction_v1.txt asks for
        "ayat": [{"text": "الحمد لله رب العالمين", "surah_number": "1", "ayah_number": "2",
                  "usage": "quotation", "extent": "complete"}],
        "dua": [{"text": "رب اشرح لي صدري", "reference": None, "usage": "quotation", "extent": "partial"}],
        "hadith": [{"text": "إنما الأعمال بالنيات", "usage": "quotation", "book": "Sahih al-Bukhari",
                    "number": "1", "expanded_reference": "Sahih al-Bukhari 1"}],
        "topics": [{"name_en": "Sincerity", "name_ur": "اخلاص", "description_en": "Intention.", "description_ur": "نیت"}],
    }
    monkeypatch.setattr(ex, "_call_llm", lambda *a, **k: "```json\n" + _json.dumps(reply, ensure_ascii=False) + "\n```")
    out = ex.extract_from_segment(Segment(id="s", start=1.0, end=9.0, text="..."), base_url="x", model="m",
                                  system_prompt="p")
    assert out.error is None
    e = out.entities.to_dict()
    assert e["ayat"][0]["extent"] == "complete" and e["ayat"][0]["usage"] == "quotation"
    assert e["dua"][0]["extent"] == "partial"
    assert e["hadith"][0]["usage"] == "quotation" and e["hadith"][0]["expanded_reference"] == "Sahih al-Bukhari 1"
    assert e["topics"][0]["name"] == "Sincerity" and e["topics"][0]["description"] == "Intention."
