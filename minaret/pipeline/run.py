"""Orchestrates one recording through the automatic pipeline (V0 -> V1 -> E1/V2), writing output
+ a trace.json alongside it at every stage. Reviewed V3/E2 enter through ingest_reviewed.py, and
the KG/RAG stages live in minaret.downstream. Every stage is also directly callable on its own
(see transcribe.py, correct.py, extract_entities.py, corpus_validate.py) — this module is the
convenience path, not the only path; a caller who wants to run one stage standalone, inspect
intermediate output, or substitute their own implementation of one stage is free to call that
module directly instead of going through run.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from minaret import trace as trace_mod
from minaret.schemas import EntitySet, Segment
from minaret.pipeline import correct as correct_mod
from minaret.pipeline import corpus_validate as corpus_validate_mod
from minaret.pipeline import extract_entities as extract_entities_mod
from minaret.pipeline import transcribe as transcribe_mod


def _write_segments(path: Path, segments: list[Segment]) -> None:
    path.write_text(json.dumps([s.to_dict() for s in segments], ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")


def _read_segments(path: Path) -> list[Segment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Segment(id=d["id"], start=d["start"], end=d["end"], text=d["text"]) for d in data]


def _default_recording_id(source: str) -> str:
    from urllib.parse import unquote, urlsplit
    import re
    name = Path(unquote(urlsplit(source).path) if transcribe_mod.is_remote(source) else source).stem
    return re.sub(r"[^\w.-]+", "_", name).strip("._") or "recording"


def run_v0_v1(source: str, *, output_root: Path, recording_id: Optional[str] = None,
              series_id: Optional[str] = None, language: Optional[str] = None,
              correction_base_url: str = "http://127.0.0.1:1234/v1",
              correction_api_key: str = "", correction_model: str = "qwen3.5-9b-mlx",
              correction_prompt: Optional[Path] = None,
              skip_correction: bool = False) -> Path:
    """Runs V0 (transcription) then V1 (correction) for one recording, writing:
        <output_root>/[<series_id>/]<recording_id>/v0.json
        <output_root>/[<series_id>/]<recording_id>/v1.json   (unless skip_correction)
        <output_root>/[<series_id>/]<recording_id>/trace.json
    Returns the recording's output directory.
    """
    recording_id = recording_id or _default_recording_id(source)
    directory = output_root / series_id / recording_id if series_id else output_root / recording_id
    directory.mkdir(parents=True, exist_ok=True)
    trace_path = directory / "trace.json"
    trace = trace_mod.ensure(trace_path, recording_id=recording_id, series_id=series_id, source=source)

    started = datetime.now(timezone.utc)
    try:
        result = transcribe_mod.transcribe(source, language=language, cache_dir=directory / ".cache")
        v0_path = directory / "v0.json"
        v0_path.write_text(
            json.dumps([s.to_dict() for s in result.segments], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        trace = trace_mod.record_stage(
            trace_path, trace, stage="V0", started_at=started, status="completed",
            detail={
                "backend": result.backend, "model": result.model, "language": result.language,
                "duration_seconds": result.duration_seconds, "audio_sha256": result.audio_sha256,
                "audio_path": result.audio_path, "segment_count": len(result.segments),
            },
        )
    except Exception as exc:  # noqa: BLE001
        trace_mod.record_stage(trace_path, trace, stage="V0", started_at=started, status="failed",
                                error=f"{type(exc).__name__}: {exc}")
        raise

    if skip_correction:
        return directory

    started = datetime.now(timezone.utc)
    try:
        v1_segments, provenance = correct_mod.correct(
            result.segments, base_url=correction_base_url, api_key=correction_api_key,
            model=correction_model, prompt_path=correction_prompt,
        )
        v1_path = directory / "v1.json"
        v1_path.write_text(
            json.dumps([s.to_dict() for s in v1_segments], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        trace_mod.record_stage(trace_path, trace, stage="V1", started_at=started, status="completed",
                                detail=provenance)
    except Exception as exc:  # noqa: BLE001
        trace_mod.record_stage(trace_path, trace, stage="V1", started_at=started, status="failed",
                                error=f"{type(exc).__name__}: {exc}")
        raise

    return directory


def run_e1_v2(recording_dir: Path, *, quran_corpus_db: str, dua_corpus_db: str,
              extraction_base_url: str = "http://127.0.0.1:1234/v1", extraction_api_key: str = "",
              extraction_model: str = "qwen3.5-9b-mlx", extraction_prompt: Optional[Path] = None,
              alpha: float, tau: float, delta: float,
              embed_fn=corpus_validate_mod.default_embed_fn) -> Path:
    """Continues a recording that already has v1.json (from run_v0_v1) through entity extraction
    and corpus validation, writing e1.json (EntitySet) and v2.json (Segment list) into the same
    recording_dir, and recording both stages in the same trace.json.

    alpha/tau/delta are required, not defaulted here either — see corpus_validate.py's module
    docstring for why."""
    v1_path = recording_dir / "v1.json"
    if not v1_path.exists():
        raise FileNotFoundError(f"{v1_path} not found — run_v0_v1() must complete (with correction, "
                                 f"not --skip-correction) before run_e1_v2()")
    v1_segments = _read_segments(v1_path)

    trace_path = recording_dir / "trace.json"
    existing_trace = trace_mod.load(trace_path)
    recording_id = existing_trace.recording_id if existing_trace else recording_dir.name
    series_id = existing_trace.series_id if existing_trace else None
    trace = trace_mod.ensure(trace_path, recording_id=recording_id, series_id=series_id,
                              source=(existing_trace.source if existing_trace else "<unknown>"))

    started = datetime.now(timezone.utc)
    try:
        candidates, extraction_provenance = extract_entities_mod.extract(
            v1_segments, base_url=extraction_base_url, api_key=extraction_api_key, model=extraction_model,
            prompt_path=extraction_prompt,
        )
        trace = trace_mod.record_stage(trace_path, trace, stage="entity_extraction", started_at=started,
                                        status="completed", detail=extraction_provenance)
    except Exception as exc:  # noqa: BLE001
        trace_mod.record_stage(trace_path, trace, stage="entity_extraction", started_at=started,
                                status="failed", error=f"{type(exc).__name__}: {exc}")
        raise

    started = datetime.now(timezone.utc)
    try:
        quran_corpus = corpus_validate_mod.load_quran_corpus(quran_corpus_db)
        dua_corpus = corpus_validate_mod.load_dua_corpus(dua_corpus_db)
        outcome = corpus_validate_mod.validate(
            candidates, v1_segments, quran_corpus=quran_corpus, dua_corpus=dua_corpus,
            alpha=alpha, tau=tau, delta=delta, embed_fn=embed_fn,
        )
        (recording_dir / "e1.json").write_text(
            json.dumps(outcome.entities.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_segments(recording_dir / "v2.json", outcome.segments)
        trace_mod.record_stage(
            trace_path, trace, stage="corpus_validation", started_at=started, status="completed",
            detail={"alpha": alpha, "tau": tau, "delta": delta,
                    "replacements_applied": outcome.replacements_applied,
                    "replacements_skipped_no_span": outcome.replacements_skipped_no_span},
        )
    except Exception as exc:  # noqa: BLE001
        trace_mod.record_stage(trace_path, trace, stage="corpus_validation", started_at=started,
                                status="failed", error=f"{type(exc).__name__}: {exc}")
        raise

    return recording_dir
