"""Reviewer panel tests. No LLM server, network or audio needed.

    pytest reviewer_panel/tests
"""
import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from reviewer_panel.replay import apply_all, plan  # noqa: E402
from reviewer_panel.session import ReviewError, Session, SessionKey  # noqa: E402

RECORDINGS = sorted(p for p in (REPO / "artifacts" / "recordings").glob("*/*") if p.is_dir())
SMALL = REPO / "artifacts" / "recordings" / "TQ2005" / "TQ2005-P01-L001C"


def start(tmp_path, rec_dir=SMALL):
    return Session.start(SessionKey("artifacts", rec_dir.parent.name, rec_dir.name), rec_dir, tmp_path / "s.json")


@pytest.mark.parametrize("rec_dir", RECORDINGS, ids=[p.name for p in RECORDINGS])
def test_replay_reproduces_released_v3_e2_and_finalizes(tmp_path, rec_dir):
    s = start(tmp_path, rec_dir)
    v3 = json.loads((rec_dir / "v3.json").read_text())
    e2 = json.loads((rec_dir / "e2.json").read_text())
    apply_all(s, plan(s.state, v3, e2))
    out_v3, out_e2 = s.build_outputs()
    assert out_v3 == v3
    assert out_e2 == {k: e2.get(k, []) for k in out_e2}
    result = s.finalize(tmp_path / "runs" / "recordings")
    assert result["ok"], result
    written = tmp_path / "runs" / "recordings" / rec_dir.parent.name / rec_dir.name
    assert json.loads((written / "v3.json").read_text()) == v3
    for name in ("v0", "v1", "v2", "e1"):
        assert (written / f"{name}.json").exists()  # reviewer inputs carried along for evaluation


def test_flags_block_finalize_and_escalation_needs_super(tmp_path):
    s = start(tmp_path)
    uid = s.state["segments"][0]["uid"]
    fid = s.apply({"op": "flag.add", "target": {"kind": "segment", "uid": uid}, "issue": "missing text"})["id"]
    assert not s.finalize(tmp_path / "runs")["ok"]
    s.apply({"op": "flag.escalate", "id": fid})
    with pytest.raises(ReviewError, match="super reviewer"):
        s.apply({"op": "flag.resolve", "id": fid})
    s.apply({"op": "flag.resolve", "id": fid, "note": "confirmed"}, role="super")
    assert s.blockers() == []
    assert s.finalize(tmp_path / "runs")["ok"]
    with pytest.raises(ReviewError, match="finalized"):
        s.apply({"op": "seg.accept", "uid": uid})


def test_unknown_flag_issue_rejected(tmp_path):
    s = start(tmp_path)
    with pytest.raises(ReviewError):
        s.apply({"op": "flag.add", "target": {"kind": "segment", "uid": s.state["segments"][0]["uid"]},
                 "issue": "not a paper category"})


def test_structural_edits(tmp_path):
    s = start(tmp_path)
    segs = s.state["segments"]
    n, first = len(segs), segs[0]
    text = first["data"]["text"]
    a, b = s.apply({"op": "seg.split", "uid": first["uid"], "at": len(text) // 2})["uids"]
    assert len(s.state["segments"]) == n + 1
    assert s.state["segments"][0]["data"]["end"] == s.state["segments"][1]["data"]["start"]
    s.apply({"op": "seg.merge", "uids": [a, b]})
    assert len(s.state["segments"]) == n
    new = s.apply({"op": "seg.insert", "after_uid": a, "start": 1.0, "end": 2.0, "text": "restored"})["uid"]
    assert s.state["segments"][1]["uid"] == new
    s.apply({"op": "seg.delete", "uid": new})
    assert len(s.state["segments"]) == n


def test_entity_actions_and_topic_scope(tmp_path):
    s = start(tmp_path)
    added = s.apply({"op": "ent.add", "type": "topics",
                     "fields": {"name_en": "Test topic", "description_en": "d", "start": 5.0, "end": 9.0}})["uid"]
    s.apply({"op": "ent.scope", "uid": added, "scope": "lecture"})
    topic = next(e for e in s.state["entities"] if e["uid"] == added)
    assert topic["fields"]["start"] == 0.0 and topic["fields"]["end"] == s.recording_end()
    first = s.state["entities"][0]
    s.apply({"op": "ent.reject", "uid": first["uid"]})
    _, e2 = s.build_outputs()
    assert first["fields"] not in e2[first["type"]]
    assert any(t.get("name_en") == "Test topic" for t in e2["topics"])


def test_finalize_refuses_output_that_breaks_the_format(tmp_path):
    s = start(tmp_path)
    s.apply({"op": "ent.add", "type": "ayat", "fields": {"surah_number": "1", "text": "x", "start": 1.0,
                                                           "end": 2.0, "usage": "quotation", "extent": "complete"}})
    r = s.finalize(tmp_path / "runs")
    assert not r["ok"] and "ayah_number" in r["blockers"][0]


def test_http_api_end_to_end(tmp_path):
    from minaret import config as config_mod
    from reviewer_panel.server import LocalServer, Panel, make_handler

    cfg = config_mod.load(REPO / "minaret.yaml")
    cfg.data = {**cfg.data, "paths": {**cfg.data.get("paths", {}), "runs_dir": str(tmp_path / "runs")},
                "llm": {k: {**v, "base_url": "http://127.0.0.1:9/v1"} for k, v in cfg.data["llm"].items()}}
    panel = Panel(cfg)
    server = LocalServer(("127.0.0.1", 0), make_handler(panel))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        status, st = call("/api/status")
        assert status == 200 and not st["llm"]["correction"]["reachable"]
        assert "LM Studio" in st["llm"]["correction"]["message"]
        key = {"source": "artifacts", "series": "TQ2005", "recording": "TQ2005-P01-L001C"}
        status, p = call("/api/session/open", key)
        assert status == 200 and len(p["state"]["segments"]) == 12
        status, p = call("/api/replay/start", key)
        assert p["replay"]["total"] > 0
        status, p = call("/api/replay/step", {**key, "steps": 100000})
        assert p["replay"]["next"] == p["replay"]["total"]
        status, r = call("/api/session/finalize", key)
        assert status == 200 and r["ok"]
        written = json.loads(Path(r["v3"]).read_text())
        assert written == json.loads((SMALL / "v3.json").read_text())
        # An LLM stage with no server running explains itself instead of failing obscurely.
        status, r = call("/api/ai/suggest", {"text": "abc"})
        assert status == 503 and "No LLM server reachable" in r["error"]
        status, r = call("/api/jobs", {"kind": "correct", "params": {"series": "X", "recording": "Y"}})
        assert status == 503 and "Transcribe first" in r["error"]
        status, info = call("/api/kg/info")
        assert "artifacts" in info["graphs"] and len(info["cqs"]) == 16
        status, r = call("/api/kg/query", {"graph": "artifacts",
                                           "query": "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"})
        assert r["rows"][0][0] == "54388"
        status, r = call("/api/kg/query", {"graph": "artifacts", "query": "DELETE WHERE { ?s ?p ?o }"})
        assert status == 400
    finally:
        server.shutdown()


def test_lecture_language_from_series_config_or_asr(tmp_path):
    from minaret import config as config_mod
    from reviewer_panel.services import Services

    cfg = config_mod.load(REPO / "minaret.yaml")
    cfg.data = {**cfg.data, "paths": {**cfg.data.get("paths", {}), "runs_dir": str(tmp_path / "runs")}}
    svc = Services(cfg)
    assert svc.lecture_language("artifacts", "HajjJourney2022Eng", "HajjJourney2022Eng-L01") == "en"
    assert svc.lecture_language("artifacts", "TQ2005", "TQ2005-P01-L001C") == "ur"
    new = tmp_path / "runs" / "recordings" / "NEW" / "R1"
    new.mkdir(parents=True)
    assert svc.lecture_language("runs", "NEW", "R1") is None
    (new / "trace.json").write_text(json.dumps({"stages": [{"stage": "V0", "detail": {"language": "ur"}}]}))
    assert svc.lecture_language("runs", "NEW", "R1") == "ur"


def test_build_targets_list_only_finalized_recordings(tmp_path):
    from minaret import config as config_mod
    from reviewer_panel.services import Services

    cfg = config_mod.load(REPO / "minaret.yaml")
    cfg.data = {**cfg.data, "paths": {**cfg.data.get("paths", {}), "runs_dir": str(tmp_path / "runs")}}
    svc = Services(cfg)
    assert svc.build_targets() == {"correct": [], "extract": [], "kg": [], "rag": []}
    rec = tmp_path / "runs" / "recordings" / "TQ2005"
    for name, files in (("TQ2005-P01-L001C", ("v3.json", "e2.json")), ("TQ2005-P01-L001D", ("v2.json", "e1.json")),
                        ("NOT-IN-CONFIG", ("v3.json", "e2.json"))):
        (rec / name).mkdir(parents=True)
        for f in files:
            (rec / name / f).write_text("[]")
    (tmp_path / "runs" / "recordings" / "NEWSERIES" / "R1").mkdir(parents=True)
    for f in ("v3.json", "e2.json"):
        (tmp_path / "runs" / "recordings" / "NEWSERIES" / "R1" / f).write_text("[]")
    t = svc.build_targets()
    kg = {k["series"]: k for k in t["kg"]}
    assert kg["TQ2005"]["build"] == ["TQ2005-P01-L001C"] and kg["TQ2005"]["not_in_config"] == ["NOT-IN-CONFIG"]
    assert kg["NEWSERIES"]["build"] == [] and "no series config" in kg["NEWSERIES"]["reason"]
    assert [(r["recording"], r["done"]) for r in t["extract"]] == []  # no recording here has a V1
    assert t["correct"] == []
    v0_only = tmp_path / "runs" / "recordings" / "NEWSERIES" / "R0"
    v0_only.mkdir()
    (v0_only / "v0.json").write_text("[]")
    (rec / "TQ2005-P01-L001D" / "v1.json").write_text("[]")
    (rec / "TQ2005-P01-L001D" / "v0.json").write_text("[]")
    t = svc.build_targets()
    assert [(r["recording"], r["done"]) for r in t["correct"]] == [("R0", False), ("TQ2005-P01-L001D", True)]
    assert [(r["recording"], r["done"]) for r in t["extract"]] == [("TQ2005-P01-L001D", True)]
    assert {(r["series"], r["recording"]) for r in t["rag"]} == {
        ("NEWSERIES", "R1"), ("TQ2005", "NOT-IN-CONFIG"), ("TQ2005", "TQ2005-P01-L001C")}


def test_canonical_lookup_returns_arabic_for_ayah_and_dua(tmp_path):
    from minaret import config as config_mod
    from reviewer_panel.services import Services

    svc = Services(config_mod.load(REPO / "minaret.yaml"))
    if not svc.cfg.path("corpora.duas_csv").exists() or not svc.cfg.path("corpora.quran_csv").exists():
        pytest.skip("quran.csv / duas.csv not in artifacts/corpora")
    dua = svc.lookup("dua", {"reference": "MasnoonDua-118"})
    row = svc._duas_index()["MasnoonDua-118"]
    assert dua["found"] and dua["text"] == row["duaArabic"] != "" and dua["translation_en"].startswith("O Allah")
    ayah = svc.lookup("ayat", {"surah_number": "1", "ayah_number": "1"})
    assert ayah["found"] and ayah["text"]


def test_settings_write_local_override_and_env_only(tmp_path, monkeypatch):
    import shutil

    import yaml

    from minaret import config as config_mod
    from reviewer_panel.settings import Settings

    shutil.copy(REPO / "minaret.yaml", tmp_path / "minaret.yaml")
    shared_before = (tmp_path / "minaret.yaml").read_text()
    monkeypatch.delenv("MINARET_CORRECTION_API_KEY", raising=False)
    cfg = config_mod.load(tmp_path / "minaret.yaml")
    st = Settings(cfg)
    view = st.view()
    assert view["fields"]["validation.tau"]["value"] == 0.9 and not view["local_exists"]
    assert view["keys"]["correction"] == {"env": "MINARET_CORRECTION_API_KEY", "set": False}

    st.save({"llm.correction.base_url": "https://openrouter.ai/api/v1", "llm.correction.model": "openai/gpt-oss-120b",
             "validation.tau": "0.9", "asr.language": "ur"}, {"correction": "sk-test-123"})
    local = yaml.safe_load((tmp_path / "minaret.local.yaml").read_text())
    assert local == {"llm": {"correction": {"base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-oss-120b"}},
                     "asr": {"language": "ur"}}  # tau equals the shared value, so it is not written
    assert (tmp_path / "minaret.yaml").read_text() == shared_before
    assert "MINARET_CORRECTION_API_KEY=sk-test-123" in (tmp_path / ".env").read_text()
    assert "sk-test-123" not in json.dumps(st.view())

    reloaded = config_mod.load(tmp_path / "minaret.yaml")
    ep = reloaded.llm("correction")
    assert (ep.base_url, ep.model, ep.api_key) == ("https://openrouter.ai/api/v1", "openai/gpt-oss-120b", "sk-test-123")
    assert reloaded.get("llm.correction.prompt") == "minaret/prompts/correction_v1.txt"  # untouched keys kept

    with pytest.raises(ValueError):
        st.save({"validation.tau": "2"})
    with pytest.raises(ValueError):
        st.save({"paths.runs_dir": "/tmp/x"})
    st.save({"asr.language": ""}, {"correction": ""})  # back to the shared value; key removed
    assert "MINARET_CORRECTION_API_KEY" not in (tmp_path / ".env").read_text()
    st.restore_defaults()
    assert not (tmp_path / "minaret.local.yaml").exists()


def test_landing_examples_come_from_the_released_artifacts(tmp_path):
    from reviewer_panel import landing

    data = landing.build("static")
    assert data["mode"] == "static" and [e["id"] for e in data["examples"]] == ["ur", "en"]
    for ex in data["examples"]:
        texts = ex["segment"]["text"]
        assert len({texts["v0"], texts["v1"], texts["v2"], texts["v3"]}) == 4  # every stage changed it
        assert ex["ayah"]["e2"]["usage"] == "quotation" and ex["ayah"]["e2"]["extent"] == "complete"
        assert ex["rag"]["answer"]["verdict"] == "correct_grounded" and ex["rag"]["answer"]["chunks"]
        assert any("semantictafsir" in u for u in ex["ayah"]["kg"]["exact_match"])
    assert data["released"]["recordings"] == 18
    landing.export(tmp_path / "site")
    html = (tmp_path / "site" / "index.html").read_text()
    assert 'content="landing.json"' in html
    assert json.loads((tmp_path / "site" / "landing.json").read_text())["mode"] == "static"
