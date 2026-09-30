"""Everything the panel does besides review state: listing recordings, canonical-text lookup, the
optional AI suggestion, pipeline stages as background jobs, KG/RAG builds, and questions.

All model/endpoint/path settings come from minaret.yaml via `minaret.config`. Stages that need
something that is not available (an LLM endpoint that is not running, an optional package that is
not installed, corpora that are not in place) fail fast with a message saying exactly what is
missing, instead of failing inside the pipeline.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from minaret import config as config_mod

REPO_ROOT = config_mod.REPO_ROOT
CQ_DIR = REPO_ROOT / "evaluation" / "rq4_kg" / "cqs"


class Unavailable(RuntimeError):
    """A stage cannot run because something it needs is missing; the message says what."""


class Services:
    def __init__(self, cfg: config_mod.Config):
        self.cfg = cfg
        self.runs_dir = cfg.path("paths.runs_dir", "runs")
        self.roots = {"artifacts": REPO_ROOT / "artifacts" / "recordings",
                      "runs": self.runs_dir / "recordings"}
        self.jobs: dict[str, dict] = {}
        self._jobs_lock = threading.Lock()
        self._quran = self._duas = None
        self._graphs: dict[str, object] = {}
        self._indices: dict[tuple, tuple] = {}

    # ------------------------------------------------------------------ environment status
    @staticmethod
    def has_module(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    @staticmethod
    def probe_endpoint(base_url: str, model: str, api_key: str = "", *, key_env: Optional[str] = None) -> dict:
        """GET {base_url}/models: is the server up, is the key accepted, is the model listed."""
        import httpx
        where = f"{base_url.rstrip('/')}/models"
        try:
            r = httpx.get(where, headers={"Authorization": f"Bearer {api_key}"} if api_key else {}, timeout=5)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "models": [], "message": (
                f"No LLM server reachable at {base_url} ({type(exc).__name__}). Start your local server "
                f"(e.g. LM Studio) with '{model}' loaded, or change the endpoint in Settings.")}
        if r.status_code in (401, 403):
            hint = f" ({key_env} in .env)" if key_env else ""
            return {"ok": False, "models": [], "message": (
                f"{base_url} refused the request (HTTP {r.status_code}): the API key{hint} is "
                + ("missing" if not api_key else "not accepted") + ". Add it in Settings.")}
        if r.status_code >= 400:
            return {"ok": False, "models": [], "message": f"{where} answered HTTP {r.status_code}"}
        try:
            models = sorted({m.get("id", "") for m in r.json().get("data", []) if m.get("id")})
        except Exception:  # noqa: BLE001 - a server without a model list is still usable
            models = []
        listed = not models or model in models or any(m.split("/")[-1] == model.split("/")[-1] for m in models)
        return {"ok": True, "models": models, "warning": None if listed else
                f"'{model}' is not in the models {base_url} lists; check the name",
                "message": f"{model} at {base_url}"}

    def llm_reachable(self, stage: str) -> tuple[bool, str]:
        try:
            ep = self.cfg.llm(stage)
        except ValueError as exc:
            return False, str(exc)
        r = self.probe_endpoint(ep.base_url, ep.model, ep.api_key,
                                key_env=self.cfg.get(f"llm.{stage}.api_key_env"))
        return r["ok"], (r.get("warning") or r["message"])

    def require_llm(self, stage: str):
        ok, msg = self.llm_reachable(stage)
        if not ok:
            raise Unavailable(msg)
        return self.cfg.llm(stage)

    def status(self) -> dict:
        corpora = {k: bool(self.cfg.path(f"corpora.{k}") and self.cfg.path(f"corpora.{k}").exists())
                   for k in ("quran_db", "dua_db", "quran_csv", "duas_csv", "semantic_hadith_dump")}
        llm = {}
        for stage in config_mod.LLM_STAGES:
            try:
                ep = self.cfg.llm(stage)
            except ValueError as exc:
                llm[stage] = {"reachable": False, "message": str(exc)}
                continue
            r = self.probe_endpoint(ep.base_url, ep.model, ep.api_key, key_env=self.cfg.get(f"llm.{stage}.api_key_env"))
            llm[stage] = {"reachable": r["ok"], "message": r.get("warning") or r["message"], "warning": bool(r.get("warning"))}
        return {"runs_dir": str(self.runs_dir), "llm": llm, "corpora": corpora,
                "packages": {m: self.has_module(m) for m in ("faster_whisper", "sentence_transformers", "rdflib")}}

    # ------------------------------------------------------------------ recordings
    def recordings(self) -> list[dict]:
        out = []
        for source, root in self.roots.items():
            if not root.exists():
                continue
            for series in sorted(p for p in root.iterdir() if p.is_dir()):
                for rec in sorted(p for p in series.iterdir() if p.is_dir()):
                    files = sorted(p.stem for p in rec.glob("*.json") if p.stem in
                                   ("v0", "v1", "v2", "v3", "e1", "e2"))
                    out.append({"source": source, "series": series.name, "recording": rec.name, "files": files,
                                "reviewable": "v2" in files and "e1" in files,
                                "has_reference": "v3" in files and "e2" in files})
        return out

    def recording_dir(self, source: str, series: str, recording: str) -> Path:
        if source not in self.roots:
            raise ValueError(f"Unknown source {source!r}")
        d = (self.roots[source] / series / recording).resolve()
        if self.roots[source].resolve() not in d.parents:
            raise ValueError("Invalid recording path")
        return d

    def audio_source(self, source: str, series: str, recording: str) -> dict:
        d = self.recording_dir(source, series, recording)
        if (d / "source.json").exists():
            info = json.loads((d / "source.json").read_text(encoding="utf-8"))
            return {"kind": "url", "url": info.get("audio_url")}
        trace = d / "trace.json"
        if trace.exists():
            src = json.loads(trace.read_text(encoding="utf-8")).get("source", "")
            if src.startswith(("http://", "https://")):
                return {"kind": "url", "url": src}
            if src and Path(src).is_file():
                return {"kind": "file", "url": f"/api/audio?source={source}&series={series}&recording={recording}",
                        "path": src}
        return {"kind": "none"}

    def lecture_language(self, source: str, series: str, recording: str) -> Optional[str]:
        """The lecture's language code: the series config's, else the language ASR detected (trace.json)."""
        try:
            return self.series_config(series)[1]["language"]["code"]
        except (Unavailable, KeyError, TypeError):
            pass
        trace = self.recording_dir(source, series, recording) / "trace.json"
        if trace.exists():
            for stage in json.loads(trace.read_text(encoding="utf-8")).get("stages", []):
                if stage.get("stage") == "V0" and (stage.get("detail") or {}).get("language"):
                    return stage["detail"]["language"]
        return None

    # ------------------------------------------------------------------ canonical text
    def _quran_index(self):
        if self._quran is None:
            p = self.cfg.path("corpora.quran_csv")
            self._quran = {}
            if p and p.exists():
                with open(p, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        self._quran[(row["sura"], row["aya"])] = row
        return self._quran

    def _duas_index(self):
        if self._duas is None:
            p = self.cfg.path("corpora.duas_csv")
            self._duas = {}
            if p and p.exists():
                with open(p, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        self._duas[row["duaId"]] = row
        return self._duas

    def lookup(self, etype: str, fields: dict) -> dict:
        if etype == "ayat":
            row = self._quran_index().get((str(fields.get("surah_number")), str(fields.get("ayah_number"))))
            if not self._quran:
                return {"found": False, "message": "quran.csv not in place (corpora.quran_csv)"}
            return {"found": bool(row), "text": row and row["text"], "text_indopak": row and row["text_indopak"],
                    "translation_en": row and row["en_sahih"], "translation_ur": row and row["ur_farhat"]}
        if etype == "dua":
            row = self._duas_index().get(str(fields.get("reference")))
            if not self._duas:
                return {"found": False, "message": "duas.csv not in place (corpora.duas_csv)"}
            return {"found": bool(row), "text": row and row["duaArabic"],
                    "text_indopak": row and (row["duaArabic_indopak"] or None),
                    "translation_en": row and row["dua_en"], "translation_ur": row and row["dua_ur"],
                    "transliteration": row and row["transliteration"]}
        if etype == "hadith":
            from minaret.downstream.kg.common import our_ref_to_kg_id, parse_hadith_block
            from minaret.downstream.kg.hadith_blocks import extract_blocks
            dump = self.cfg.path("corpora.semantic_hadith_dump")
            kg_id = our_ref_to_kg_id(str(fields.get("reference", "")))
            if not kg_id:
                return {"found": False, "message": "Reference is not in a collection the SemanticHadith KG covers"}
            if not (dump and dump.exists()):
                return {"found": False, "message": "SemanticHadith dump not in place (corpora.semantic_hadith_dump)"}
            block = parse_hadith_block(extract_blocks(dump, [kg_id], cache_dir=self.cfg.path("corpora.cache_dir")).get(kg_id))
            if not block:
                return {"found": False, "message": f"{kg_id} not found in the SemanticHadith KG"}
            texts = {t["lang"]: t["text"] for t in block["fullHadithText"]}
            return {"found": True, "kg_id": kg_id, "text": texts.get("ar"), "translation_en": texts.get("en"),
                    "translation_ur": texts.get("ur"), "url": block.get("hadithURL")}
        return {"found": False, "message": "No canonical corpus for this entity type"}

    # ------------------------------------------------------------------ AI-assisted suggestion
    def suggest(self, text: str) -> dict:
        """The paper's optional AI-assisted editing aid: a correction suggestion for one segment,
        from the same correction prompt and validation as V1. The reviewer decides what to keep."""
        from minaret.pipeline import correct as correct_mod
        from minaret.schemas import Segment
        ep = self.require_llm("correction")
        prompt = ep.prompt.read_text(encoding="utf-8") if ep.prompt else correct_mod.PROMPT_PATH.read_text(encoding="utf-8")
        outcome = correct_mod.correct_segment(Segment(id="panel", start=0.0, end=0.0, text=text), base_url=ep.base_url,
                                              api_key=ep.api_key, model=ep.model, system_prompt=prompt)
        return {"suggestion": outcome.segment.text, "changed": outcome.changed, "fallback": outcome.fallback,
                "note": outcome.error or ""}

    # ------------------------------------------------------------------ pipeline stages (background jobs)
    def start_job(self, kind: str, params: dict) -> dict:
        runner = getattr(self, f"_job_{kind}", None)
        if runner is None:
            raise ValueError(f"Unknown stage {kind!r}")
        check = getattr(self, f"_check_{kind}", None)
        if check:
            check(params)  # raises Unavailable with a precise message before anything starts
        job = {"id": uuid.uuid4().hex[:8], "kind": kind, "params": params, "status": "running",
               "started": datetime.now(timezone.utc).isoformat(), "finished": None, "message": "", "error": None}
        with self._jobs_lock:
            self.jobs[job["id"]] = job

        def work():
            try:
                job["message"] = runner(params) or "done"
                job["status"] = "completed"
            except Exception as exc:  # noqa: BLE001
                job["status"], job["error"] = "failed", f"{type(exc).__name__}: {exc}"
                job["traceback"] = traceback.format_exc(limit=5)
            job["finished"] = datetime.now(timezone.utc).isoformat()

        threading.Thread(target=work, daemon=True).start()
        return job

    def _rec_dir(self, params) -> Path:
        return self.runs_dir / "recordings" / params["series"] / params["recording"]

    # V0
    def _check_transcribe(self, p):
        if not self.has_module("faster_whisper"):
            raise Unavailable("faster-whisper is not installed (pip install -e \".[asr]\")")
        if not p.get("audio") or not p.get("series") or not p.get("recording"):
            raise ValueError("Transcribe needs an audio path or URL, a series and a recording id")

    def _job_transcribe(self, p):
        from minaret.pipeline.run import run_v0_v1
        d = run_v0_v1(p["audio"], output_root=self.runs_dir / "recordings", series_id=p["series"],
                      recording_id=p["recording"], language=self.cfg.get("asr.language"), skip_correction=True)
        return f"V0 written to {d / 'v0.json'}"

    # V1
    def _check_correct(self, p):
        if not (self._rec_dir(p) / "v0.json").exists():
            raise Unavailable("No v0.json for this recording yet: run Transcribe first")
        self.require_llm("correction")

    def _job_correct(self, p):
        from minaret import trace as trace_mod
        from minaret.pipeline import correct as correct_mod
        from minaret.schemas import Segment
        d = self._rec_dir(p)
        ep = self.cfg.llm("correction")
        # Transcribe writes a uuid per segment; some released V0s have none, so give those one the same way.
        v0 = [Segment(id=s.get("id") or str(uuid.uuid4()), start=s["start"], end=s["end"], text=s["text"])
              for s in json.loads((d / "v0.json").read_text(encoding="utf-8"))]
        trace_path = d / "trace.json"
        trace = trace_mod.ensure(trace_path, recording_id=p["recording"], series_id=p["series"], source="<v0.json>")
        started = datetime.now(timezone.utc)
        try:
            v1, provenance = correct_mod.correct(v0, base_url=ep.base_url, api_key=ep.api_key, model=ep.model,
                                                 prompt_path=ep.prompt)
            (d / "v1.json").write_text(json.dumps([s.to_dict() for s in v1], ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
            trace_mod.record_stage(trace_path, trace, stage="V1", started_at=started, status="completed",
                                   detail=provenance)
        except Exception as exc:  # noqa: BLE001
            trace_mod.record_stage(trace_path, trace, stage="V1", started_at=started, status="failed",
                                   error=f"{type(exc).__name__}: {exc}")
            raise
        return f"V1 written to {d / 'v1.json'}"

    # E1 / V2
    def _check_extract(self, p):
        if not (self._rec_dir(p) / "v1.json").exists():
            raise Unavailable("No v1.json for this recording yet: run Correct first")
        for key in ("quran_db", "dua_db"):
            path = self.cfg.path(f"corpora.{key}")
            if not (path and path.exists()):
                raise Unavailable(f"Corpus validation needs corpora.{key} ({path}); see artifacts/corpora/README.md")
        if not self.has_module("sentence_transformers"):
            raise Unavailable("sentence-transformers is not installed (pip install -e \".[rag]\")")
        self.require_llm("extraction")

    def _job_extract(self, p):
        from minaret.pipeline.run import run_e1_v2
        ep = self.cfg.llm("extraction")
        d = run_e1_v2(self._rec_dir(p), quran_corpus_db=str(self.cfg.path("corpora.quran_db")),
                      dua_corpus_db=str(self.cfg.path("corpora.dua_db")), extraction_base_url=ep.base_url,
                      extraction_api_key=ep.api_key, extraction_model=ep.model, extraction_prompt=ep.prompt,
                      alpha=float(self.cfg.get("validation.alpha")), tau=float(self.cfg.get("validation.tau")),
                      delta=float(self.cfg.get("validation.delta")))
        return f"E1 and V2 written to {d}"

    # KG
    def series_config(self, series_folder: str) -> tuple[Path, dict]:
        root = self.cfg.path("paths.series_configs")
        for f in sorted(root.glob("*.json")):
            if f.stem.endswith("_topic_proposals"):
                continue
            cfg = json.loads(f.read_text(encoding="utf-8"))
            if cfg.get("recordings_dir") == series_folder:
                return f, cfg
        raise Unavailable(f"No KG series config for '{series_folder}' in {root}: write one "
                          "(see minaret/README.md, 'Series config') before building its KG")

    def build_targets(self) -> dict:
        """What each stage after Transcribe can run on, from the recordings in runs/: Correct needs a V0,
        Extract a V1, and Build KG / Build RAG index a finalized review (V3 + E2)."""
        root = self.runs_dir / "recordings"
        recordings = [r for series in sorted(p for p in root.iterdir() if p.is_dir())
                      for r in sorted(series.iterdir()) if r.is_dir()] if root.exists() else []
        has = lambda r, *names: all((r / n).exists() for n in names)  # noqa: E731
        stage = lambda need, done: [{"series": r.parent.name, "recording": r.name, "done": has(r, done)}  # noqa: E731
                                    for r in recordings if has(r, need)]
        finalized: dict[str, list[str]] = {}
        for r in recordings:
            if has(r, "v3.json", "e2.json"):
                finalized.setdefault(r.parent.name, []).append(r.name)
        kg = []
        for series, recs in finalized.items():
            try:
                cfg_path, cfg = self.series_config(series)
            except Unavailable:
                kg.append({"series": series, "finalized": recs, "config": None, "build": [],
                           "reason": "no series config (see minaret/README.md, 'Series config')"})
                continue
            listed = [r["recording_id"] for r in cfg["recordings"]]
            build = [r for r in listed if r in recs]
            kg.append({"series": series, "finalized": recs, "config": cfg_path.name, "build": build,
                       "not_in_config": [r for r in recs if r not in listed],
                       "reason": None if build else "none of its finalized recordings is listed in its series config"})
        rag = [{"series": series, "recording": r} for series, recs in finalized.items() for r in recs]
        return {"correct": stage("v0.json", "v1.json"), "extract": stage("v1.json", "e1.json"), "kg": kg, "rag": rag}

    def _check_kg(self, p):
        if not self.has_module("rdflib"):
            raise Unavailable("rdflib is not installed (pip install -e \".[kg]\")")
        for key in ("quran_csv", "duas_csv", "semantic_hadith_dump"):
            path = self.cfg.path(f"corpora.{key}")
            if not (path and path.exists()):
                raise Unavailable(f"The KG build needs corpora.{key} ({path}); see artifacts/corpora/README.md")
        _, cfg = self.series_config(p["series"])
        done = [r for r in cfg["recordings"]
                if (self.runs_dir / "recordings" / p["series"] / r["recording_id"] / "e2.json").exists()]
        if not done:
            raise Unavailable(f"No finalized recording of {p['series']} in {self.runs_dir / 'recordings'} is listed "
                              "in its series config")

    def _job_kg(self, p):
        from minaret.downstream.kg.build import build_all
        from minaret.downstream.kg.combine import combine
        _, cfg = self.series_config(p["series"])
        cfg = dict(cfg)
        cfg["recordings"] = [r for r in cfg["recordings"]
                             if (self.runs_dir / "recordings" / p["series"] / r["recording_id"] / "e2.json").exists()]
        tmp_cfg = self.runs_dir / "kg" / "panel_configs" / f"{cfg['series_code']}.json"
        tmp_cfg.parent.mkdir(parents=True, exist_ok=True)
        tmp_cfg.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        out = self.runs_dir / "kg"
        builders = build_all([tmp_cfg], recordings_root=self.runs_dir / "recordings", out_dir=out,
                             quran_csv=self.cfg.path("corpora.quran_csv"), duas_csv=self.cfg.path("corpora.duas_csv"),
                             hadith_dump=self.cfg.path("corpora.semantic_hadith_dump"),
                             cache_dir=self.cfg.path("corpora.cache_dir"), fresh_registry=False)
        combine(out / "instances", out / "minaret_combined.ttl")
        self._graphs.pop(str(out / "minaret_combined.ttl"), None)
        return (f"{cfg['series_code']}: {len(builders[0].g)} triples from {len(cfg['recordings'])} recording(s); "
                f"combined graph at {out / 'minaret_combined.ttl'}")

    # RAG index
    def _check_rag_index(self, p):
        if not self.has_module("sentence_transformers"):
            raise Unavailable("sentence-transformers is not installed (pip install -e \".[rag]\")")
        if not (self._rec_dir(p) / "v3.json").exists():
            raise Unavailable("No v3.json for this recording in runs/ yet: finalize its review first")

    def _job_rag_index(self, p):
        from minaret.downstream.rag.index import build_lecture_index, build_series_index
        index_root = self.runs_dir / "rag" / "index"
        build_lecture_index(self._rec_dir(p) / "v3.json", series=p["series"], recording_id=p["recording"],
                            index_root=index_root, target_seconds=float(self.cfg.get("rag.target_seconds", 30)))
        build_series_index(p["series"], index_root=index_root)
        self._indices.clear()
        return f"Lecture and {p['series']} series indices written under {index_root}"

    # ------------------------------------------------------------------ questions
    def index_roots(self) -> dict:
        return {"artifacts": REPO_ROOT / "artifacts" / "rag" / "index", "runs": self.runs_dir / "rag" / "index"}

    def rag_targets(self) -> dict:
        out = {}
        for name, root in self.index_roots().items():
            if root.exists():
                out[name] = {"lecture": sorted(p.name for p in root.iterdir() if p.is_dir() and p.name != "series"
                                               and (p / "chunks.json").exists()),
                             "series": sorted(p.name for p in (root / "series").iterdir() if p.is_dir())
                             if (root / "series").exists() else []}
        return out

    def rag_query(self, *, index: str, scope: str, target: str, question: str) -> dict:
        if not self.has_module("sentence_transformers"):
            raise Unavailable("sentence-transformers is not installed (pip install -e \".[rag]\")")
        from minaret.downstream.rag.query import DEFAULT_MAX_TOKENS, answer_question, load_index
        key = (index, scope, target)
        if key not in self._indices:
            kw = {"recording_id": target} if scope == "lecture" else {"series": target}
            self._indices[key] = load_index(self.index_roots()[index], scope=scope, **kw)
        manifest, embeddings = self._indices[key]
        ok, msg = self.llm_reachable("rag_answer")
        ep = self.cfg.llm("rag_answer") if ok else None
        prompt_path = self.cfg.path("llm.rag_answer.prompt") or REPO_ROOT / "minaret/prompts/rag_answer_v1.txt"
        rec = answer_question(scope, target, "Q", question, manifest, embeddings, endpoint=ep,
                              system_prompt=Path(prompt_path).read_text(encoding="utf-8"), mock=not ok,
                              max_tokens=(ep.max_tokens if ep and ep.max_tokens else DEFAULT_MAX_TOKENS),
                              top_k_initial=int(self.cfg.get("rag.top_k_initial", 10)),
                              top_k_final=int(self.cfg.get("rag.top_k_final", 4)))
        rec["answer_unavailable"] = None if ok else msg
        return rec

    def kg_graphs(self) -> dict:
        return {name: p for name, p in {"artifacts": REPO_ROOT / "artifacts" / "kg" / "minaret_combined.ttl",
                                        "runs": self.runs_dir / "kg" / "minaret_combined.ttl"}.items() if p.exists()}

    def competency_questions(self) -> list[dict]:
        out = []
        for f in sorted(CQ_DIR.glob("CQ*.rq")) if CQ_DIR.exists() else []:
            if "step2" in f.stem:
                continue
            text = f.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip()
            out.append({"id": f.stem, "title": title, "query": text})
        return out

    def kg_query(self, *, graph: str, query: str) -> dict:
        if not self.has_module("rdflib"):
            raise Unavailable("rdflib is not installed (pip install -e \".[kg]\")")
        from rdflib import Graph
        from rdflib.plugins.sparql import prepareQuery
        path = self.kg_graphs().get(graph)
        if path is None:
            raise Unavailable(f"No combined KG for '{graph}' yet")
        try:  # SPARQL Update cannot be prepared as a query, so this also refuses DELETE/INSERT
            q = prepareQuery(query)
        except Exception as exc:  # noqa: BLE001  (pyparsing errors are not ValueErrors)
            raise ValueError(f"Not a valid SELECT/ASK query: {exc}") from exc
        if str(path) not in self._graphs:
            self._graphs[str(path)] = Graph().parse(path)
        res = self._graphs[str(path)].query(q)
        if res.type not in ("SELECT", "ASK"):
            raise ValueError("Only SELECT and ASK queries are supported here")
        if res.type == "ASK":
            return {"type": "ASK", "answer": bool(res.askAnswer)}
        vars_ = [str(v) for v in res.vars]
        rows = [[None if v is None else str(v) for v in row] for row in res]
        return {"type": "SELECT", "vars": vars_, "rows": rows[:500], "row_count": len(rows)}
