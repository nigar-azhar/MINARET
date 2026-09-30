"""Hand-off point for externally-reviewed V3 + E2.

This package never produces V3/E2 itself: human review turns V2/E1 into V3/E2 (the paper's
review application is not released; reviewer_panel/ simulates that stage). Whatever review
process produced them, the reviewed files enter here: `ingest()` checks the two files structurally against
exactly what the downstream KG builder and RAG indexer read, copies them into the recording
directory as v3.json / e2.json, and records a `reviewed_input` stage in trace.json.

Expected shapes (the same as artifacts/recordings/*/*/{v3,e2}.json):
  v3.json  [{"start": float, "end": float, "text": str, "id"?: str}, ...]   (or {"segments": [...]})
  e2.json  {"ayat":    [{"surah_number", "ayah_number", "text", "start", "end", "usage", "extent"}],
            "hadith":  [{"reference", "expanded_reference"?, "text", "start", "end", "usage"}],
            "dua":     [{"reference", "text", "start", "end", "usage", "extent"}],
            "topics":  [{"name_en" | "name", "description_en" | "description", "start", "end",
                         "name_ur"?, "description_ur"?, "renamed_from"?}],
            "headings":[{"title_en", "title_ur", "start", "end"}]}
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from minaret import trace as trace_mod

USAGE_VALUES = {"quotation", "translation", "paraphrase", "explicit paraphrase"}
EXTENT_VALUES = {"complete", "partial"}
REQUIRED = {
    "ayat": ("surah_number", "ayah_number", "text", "start", "end", "usage", "extent"),
    "hadith": ("reference", "text", "start", "end", "usage"),
    "dua": ("reference", "text", "start", "end", "usage", "extent"),
    "topics": ("start", "end"),
    "headings": ("title_en", "title_ur", "start", "end"),
}


class ReviewedInputError(ValueError):
    """Raised when the supplied V3/E2 would break a downstream stage."""


@dataclass
class IngestResult:
    v3_path: Path
    e2_path: Path
    warnings: list[str]


def load_v3(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and "segments" in data:
        data = data["segments"]
    return data


def validate(v3: list[dict], e2: dict) -> list[str]:
    """Raise on fatal problems, return non-fatal warnings."""
    warnings: list[str] = []
    if not isinstance(v3, list) or not v3:
        raise ReviewedInputError("V3 must be a non-empty list of segments")
    for i, s in enumerate(v3):
        if not isinstance(s, dict) or not {"start", "end", "text"} <= set(s):
            raise ReviewedInputError(f"V3 segment {i} needs start, end and text")
        if s["end"] < s["start"]:
            warnings.append(f"V3 segment {i} has end ({s['end']}) < start ({s['start']}); it will "
                            "anchor to no entity span in the KG")
        if i and s["start"] < v3[i - 1]["start"]:
            warnings.append(f"V3 segment {i} starts before segment {i - 1}; RAG chunking assumes "
                            "time-ordered segments")
    ids = [s["id"] for s in v3 if s.get("id") is not None]  # reviewer-added segments may have id: null
    if len(set(ids)) != len(ids):
        raise ReviewedInputError("Duplicate segment ids in V3")

    if not isinstance(e2, dict):
        raise ReviewedInputError("E2 must be an object with ayat/hadith/dua/topics/headings lists")
    span_end = max(s["end"] for s in v3)
    for kind, fields in REQUIRED.items():
        for i, item in enumerate(e2.get(kind, [])):
            missing = [f for f in fields if f not in item]
            if kind == "topics" and not (item.get("name_en") or item.get("name")):
                missing.append("name_en")
            if missing:
                raise ReviewedInputError(f"E2 {kind}[{i}] is missing {missing}")
            if "usage" in fields and str(item["usage"] or "").strip().lower() not in USAGE_VALUES:
                raise ReviewedInputError(f"E2 {kind}[{i}] usage={item['usage']!r} not in {sorted(USAGE_VALUES)}")
            if "extent" in fields and str(item["extent"] or "").strip().lower() not in EXTENT_VALUES:
                raise ReviewedInputError(f"E2 {kind}[{i}] extent={item['extent']!r} not in {sorted(EXTENT_VALUES)}")
            if item["start"] > span_end:
                warnings.append(f"E2 {kind}[{i}] starts at {item['start']}s, after the last V3 segment "
                                f"ends ({span_end}s); it will anchor to no transcript segment")
    return warnings


def ingest(recording_dir: Path, *, v3_path: Path, e2_path: Path, recording_id: Optional[str] = None,
           series_id: Optional[str] = None) -> IngestResult:
    recording_dir = Path(recording_dir)
    v3 = load_v3(v3_path)
    e2 = json.loads(Path(e2_path).read_text(encoding="utf-8"))
    warnings = validate(v3, e2)

    recording_dir.mkdir(parents=True, exist_ok=True)
    dst_v3, dst_e2 = recording_dir / "v3.json", recording_dir / "e2.json"
    if Path(v3_path).resolve() != dst_v3.resolve():
        shutil.copyfile(v3_path, dst_v3)
    if Path(e2_path).resolve() != dst_e2.resolve():
        shutil.copyfile(e2_path, dst_e2)

    trace_path = recording_dir / "trace.json"
    started = datetime.now(timezone.utc)
    tr = trace_mod.ensure(trace_path, recording_id=recording_id or recording_dir.name, series_id=series_id,
                          source="<externally supplied V3/E2>")
    trace_mod.record_stage(
        trace_path, tr, stage="reviewed_input", started_at=started, status="completed",
        detail={"segment_count": len(v3), "warning_count": len(warnings), "warnings": warnings,
                "entity_counts": {k: len(e2.get(k, [])) for k in REQUIRED}},
    )
    return IngestResult(v3_path=dst_v3, e2_path=dst_e2, warnings=warnings)
