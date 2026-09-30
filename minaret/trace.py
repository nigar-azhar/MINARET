"""Traceability: which recording, and which pipeline stage, produced a given output.

Per project decision: existing artifact structures (segment/entity JSON shapes) are not changed
to carry this information. Instead, every recording gets one companion `trace.json` file
alongside its pipeline outputs, appended to (never overwritten) as each stage runs. This is
deliberately a thin, dependency-free append-log — implementation detail, not a process detail;
swap it for a database later without touching any pipeline stage's own logic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class StageRecord:
    stage: str  # "V0" | "V1" | "entity_extraction" | "corpus_validation" | "kg_ingestion" | "rag_ingestion"
    started_at: str
    finished_at: str
    status: str  # "completed" | "failed"
    detail: dict = field(default_factory=dict)  # stage-specific provenance, e.g. model, prompt_sha256
    error: Optional[str] = None


@dataclass
class Trace:
    recording_id: str
    series_id: Optional[str]
    source: str  # original local path or URL this recording was ingested from
    stages: list[StageRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Trace":
        stages = [StageRecord(**s) for s in d.get("stages", [])]
        return cls(recording_id=d["recording_id"], series_id=d.get("series_id"),
                    source=d["source"], stages=stages)


def load(path: Path) -> Optional[Trace]:
    if not path.exists():
        return None
    return Trace.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save(path: Path, trace: Trace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure(path: Path, *, recording_id: str, series_id: Optional[str], source: str) -> Trace:
    """Load the existing trace for this recording, or start a new one. Never overwrites an
    existing trace's history — only appends via record_stage()."""
    existing = load(path)
    if existing is not None:
        return existing
    return Trace(recording_id=recording_id, series_id=series_id, source=source)


def record_stage(path: Path, trace: Trace, *, stage: str, started_at: datetime,
                  status: str, detail: Optional[dict] = None, error: Optional[str] = None) -> Trace:
    """Append one stage record and persist immediately — so a crash mid-pipeline still leaves an
    accurate trace of what actually completed, not just what was attempted."""
    trace.stages.append(StageRecord(
        stage=stage,
        started_at=started_at.astimezone(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        detail=detail or {},
        error=error,
    ))
    save(path, trace)
    return trace
