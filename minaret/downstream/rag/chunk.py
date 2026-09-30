"""Deterministic, segment-preserving chunking of a V3 transcript into contextual
retrieval chunks. No model calls. Mirrors the chunking design described for
MINARET's RAG component: ~30s target, natural stopping point preferred
(sentence-final punctuation, then a pause, then clause punctuation), a
guideline rather than a hard cutoff so a coherent statement is never split.

Operates on whole V3 segments (never splits inside one) since V3 segments
themselves already carry {start, end, text} but not word-level timestamps.
"""
import re

POLICY = {"version": "lecture-rag-chunk-v1", "target_seconds": 30, "minimum_seconds": 15,
          "maximum_seconds": 60, "pause_seconds": 1.0}

SENTENCE_END = re.compile(r"[.!?۔؟]$")
CLAUSE_END = re.compile(r"[,;:،؛]$")


def chunk_segments(segments, policy=POLICY):
    """segments: list of dicts with 'start','end','text' (any extra keys kept,
    e.g. an 'id'). Returns a list of chunk dicts: id, start, end, text,
    constituent_segment_indices (positions in the input list)."""
    if not segments:
        return []
    chunks = []
    n = len(segments)
    i = 0
    while i < n:
        origin = segments[i]["start"]
        extent = segments[i]["end"]
        best = None  # (rank, -|elapsed-target|, stop_exclusive)
        j = i
        while j < n:
            extent = max(extent, segments[j]["end"])
            elapsed = extent - origin
            if elapsed > policy["maximum_seconds"] and j > i:
                break
            text = segments[j]["text"].rstrip().rstrip("\"'”’»)]}")
            gap = segments[j + 1]["start"] - extent if j + 1 < n else 0
            if elapsed >= policy["minimum_seconds"]:
                if SENTENCE_END.search(text):
                    rank = 3
                elif gap >= policy["pause_seconds"]:
                    rank = 2
                elif CLAUSE_END.search(text):
                    rank = 1
                else:
                    rank = 0
                candidate = (rank, -abs(elapsed - policy["target_seconds"]), j + 1)
                if best is None or candidate > best:
                    best = candidate
            j += 1
        if j == n:
            stop = n
        elif best is not None:
            stop = best[2]
        else:
            stop = j
        if stop <= i:
            stop = i + 1
        group = segments[i:stop]
        chunks.append({
            "chunk_index": len(chunks),
            "start": group[0]["start"],
            "end": max(s["end"] for s in group),
            "text": " ".join(s["text"].strip() for s in group),
            "constituent_segment_indices": list(range(i, stop)),
        })
        i = stop
    return chunks
