"""Read-only access to a pipeline artifact tree (the shipped artifacts/ or your own runs/).

Every evaluation script takes `--artifacts <dir>` and only ever reads from it. Layout:
    <dir>/recordings/<series>/<recording>/{v0,v1,v2,v3,e1,e2}.json
    <dir>/kg/minaret_combined.ttl
    <dir>/rag/traces/..., <dir>/rag/graded_trace_index.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS = REPO_ROOT / "artifacts"

# Paper order: series, then recording.
SERIES_ORDER = ["TQ2005", "HajjJourney2022Eng", "SKD2025", "HEA"]


def arg_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS,
                   help="Artifact tree to evaluate (default: the shipped artifacts/)")
    p.add_argument("--out", type=Path, default=None, help="Results directory (default: <script dir>/results)")
    return p


def recordings(artifacts: Path) -> list[tuple[str, str, Path]]:
    """[(series, recording_id, recording_dir)] in paper order, then any other series alphabetically."""
    root = Path(artifacts) / "recordings"
    present = sorted(p.name for p in root.iterdir() if p.is_dir())
    ordered = [s for s in SERIES_ORDER if s in present] + [s for s in present if s not in SERIES_ORDER]
    out = []
    for series in ordered:
        for rec in sorted(p for p in (root / series).iterdir() if p.is_dir()):
            out.append((series, rec.name, rec))
    return out


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_segments(path: Path) -> list[dict]:
    data = load_json(path)
    if isinstance(data, dict) and "segments" in data:
        data = data["segments"]
    return data


def write_results(out_dir: Path, name: str, data, markdown: str | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if markdown is not None:
        (out_dir / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(f"wrote {out_dir / name}.json" + (" (+ .md)" if markdown is not None else ""))
