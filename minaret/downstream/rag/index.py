"""Build retrieval indices from reviewed V3 transcripts.

Lecture index: chunk one recording's v3.json (chunk.py), embed every chunk locally with
BAAI/bge-m3, save chunks.json / chunks.csv / embeddings.npy under <index_root>/<recording_id>/.

Series index: concatenate the already-built lecture indices of one series (no re-embedding)
into <index_root>/series/<series>/. Every chunk keeps its own lecture_id, so series-scope
answers still attribute each chunk to its source lecture.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from minaret.downstream.rag.chunk import POLICY, chunk_segments

EMBED_MODEL = "BAAI/bge-m3"

_embedder = None


def default_embed(texts: list[str]) -> np.ndarray:
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder.encode(texts, normalize_embeddings=True, show_progress_bar=len(texts) > 32)


def load_v3_segments(v3_path: Path) -> list[dict]:
    data = json.loads(Path(v3_path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and "segments" in data:
        data = data["segments"]
    return data


def _display_path(path: Path) -> str:
    """Store a portable, repo-relative path in the manifest where possible."""
    try:
        return os.path.relpath(Path(path).resolve(), Path.cwd())
    except ValueError:
        return str(path)


def build_lecture_index(v3_path: Path, *, series: str, recording_id: str, index_root: Path,
                        target_seconds: float = 30, embed_fn: Optional[Callable] = None) -> Path:
    segments = load_v3_segments(v3_path)
    policy = {**POLICY, "target_seconds": target_seconds}
    chunks = chunk_segments(segments, policy)
    manifest = []
    for c in chunks:
        constituent = [segments[i].get("id") or f"idx_{i}" for i in c["constituent_segment_indices"]]
        manifest.append({
            "chunk_id": f"{recording_id}_chunk_{c['chunk_index']:04d}",
            "lecture_id": recording_id,
            "series": series,
            "chunk_index": c["chunk_index"],
            "start": c["start"],
            "end": c["end"],
            "constituent_segment_ids": constituent,
            "text": c["text"],
        })

    out_dir = Path(index_root) / recording_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "chunks.json").write_text(
        json.dumps({"lecture_id": recording_id, "series": series,
                    "source_gold_file": _display_path(v3_path), "chunk_policy": policy,
                    "chunk_count": len(manifest), "chunks": manifest},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "chunks.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["chunk_id", "lecture_id", "series", "chunk_index",
                                          "start", "end", "constituent_segment_ids", "text"])
        w.writeheader()
        for m in manifest:
            row = dict(m)
            row["constituent_segment_ids"] = ";".join(row["constituent_segment_ids"])
            w.writerow(row)

    embeddings = (embed_fn or default_embed)([m["text"] for m in manifest])
    np.save(out_dir / "embeddings.npy", np.asarray(embeddings).astype("float32"))
    print(f"[rag] {recording_id}: {len(manifest)} chunks from {len(segments)} V3 segments -> {out_dir}")
    return out_dir


def build_series_index(series: str, *, index_root: Path) -> Path:
    index_root = Path(index_root)
    matched = []
    for d in sorted(p for p in index_root.iterdir() if p.is_dir() and p.name != "series"):
        if not (d / "chunks.json").exists():
            continue
        manifest = json.loads((d / "chunks.json").read_text(encoding="utf-8"))
        if manifest.get("series") == series:
            matched.append((d, manifest))
    if not matched:
        raise SystemExit(f"No lecture indices found for series={series}; build those first.")

    all_chunks, all_embeddings = [], []
    for d, manifest in matched:
        emb = np.load(d / "embeddings.npy")
        assert emb.shape[0] == len(manifest["chunks"]), f"{d}: embedding/manifest count mismatch"
        all_chunks.extend(manifest["chunks"])
        all_embeddings.append(emb)

    out_dir = index_root / "series" / series
    out_dir.mkdir(parents=True, exist_ok=True)
    out_manifest = {
        "series": series,
        "scope": "series",
        "lecture_ids": sorted({c["lecture_id"] for c in all_chunks}),
        "source_lecture_indices": [str(d.relative_to(index_root)) for d, _ in matched],
        "chunk_count": len(all_chunks),
        "chunks": all_chunks,
    }
    (out_dir / "chunks.json").write_text(json.dumps(out_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    np.save(out_dir / "embeddings.npy", np.concatenate(all_embeddings, axis=0).astype("float32"))
    print(f"[rag] series index {series}: {len(all_chunks)} chunks from {len(matched)} lecture(s) -> {out_dir}")
    return out_dir
