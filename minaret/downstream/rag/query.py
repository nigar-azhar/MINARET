"""Retrieval-augmented question answering over a lecture or series index.

Pipeline per question: bge-m3 cosine retrieval (top_k_initial) -> bge-reranker-v2-m3 rerank
(documented fallback to embedding order if the reranker cannot load/run) -> top_k_final chunks
sent to the answer model (any OpenAI-compatible endpoint; `llm.rag_answer` in minaret.yaml).

Every question produces one full trace record: initial/reranked/sent chunks with ranks and
scores, each chunk's lecture id / segment ids / start / end / text, the generated answer, the
exact system prompt, and whether reranking succeeded. evaluation/rq5_rag scores these traces.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from minaret.config import LLMEndpoint
from minaret.downstream.rag.index import EMBED_MODEL, default_embed

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
TOP_K_INITIAL = 10
TOP_K_FINAL = 4
# Reasoning models (e.g. Qwen3.5) can spend a small completion budget entirely on hidden
# reasoning and return empty content; the paper's runs used 6000.
DEFAULT_MAX_TOKENS = 6000


def load_index(index_root: Path, *, scope: str, recording_id: Optional[str] = None,
               series: Optional[str] = None):
    index_root = Path(index_root)
    if scope == "lecture":
        out_dir = index_root / recording_id
    elif scope == "series":
        out_dir = index_root / "series" / series
    else:
        raise SystemExit(f"Unknown scope {scope!r}, expected 'lecture' or 'series'")
    if not out_dir.exists():
        raise SystemExit(f"No index at {out_dir}; build it first (python -m minaret.cli rag index ...)")
    manifest = json.loads((out_dir / "chunks.json").read_text(encoding="utf-8"))
    return manifest, np.load(out_dir / "embeddings.npy")


_reranker = None


def rerank(question, candidates):
    """candidates: [(chunk, embed_score)] -> ([(chunk, rerank_score, embed_score)], status)."""
    global _reranker
    try:
        if _reranker is None:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(RERANK_MODEL)
        scores = _reranker.predict([(question, c["text"]) for c, _ in candidates])
        combined = [(c, float(s), e) for (c, e), s in zip(candidates, scores)]
        combined.sort(key=lambda x: x[1], reverse=True)
        return combined, "reranked"
    except Exception as exc:  # model unavailable, OOM, etc. -- documented fallback
        print(f"[rag] rerank fallback ({exc}); using embedding-similarity order", file=sys.stderr)
        return [(c, e, e) for c, e in candidates], "fallback_embedding_order"


def call_llm(messages, endpoint: Optional[LLMEndpoint], *, max_tokens: int, mock: bool = False) -> dict:
    if mock or endpoint is None:
        return {"content": "[MOCK ANSWER - no LLM called]", "provider": "mock"}
    import httpx
    headers = {"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}
    r = httpx.post(f"{endpoint.base_url.rstrip('/')}/chat/completions", headers=headers,
                   json={"model": endpoint.model, "messages": messages,
                         "temperature": endpoint.temperature, "max_tokens": max_tokens},
                   timeout=420)
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    finish_reason = data["choices"][0].get("finish_reason")
    if finish_reason == "length" and not (msg.get("content") or "").strip():
        print(f"[rag] WARNING: hit max_tokens ({max_tokens}) before producing content; raise it.",
              file=sys.stderr)
    return {"content": msg.get("content") or "", "provider": endpoint.base_url, "raw_usage": data.get("usage"),
            "finish_reason": finish_reason, "reasoning_content": msg.get("reasoning_content")}


def answer_question(scope, scope_label, question_id, question, manifest, embeddings, *,
                    endpoint: Optional[LLMEndpoint], system_prompt: str, mock: bool = False,
                    max_tokens: int = DEFAULT_MAX_TOKENS, top_k_initial: int = TOP_K_INITIAL,
                    top_k_final: int = TOP_K_FINAL, embed_fn=None) -> dict:
    chunks = manifest["chunks"]
    q_vec = np.asarray((embed_fn or default_embed)([question]))[0]
    sims = embeddings @ q_vec
    order = np.argsort(-sims)[:top_k_initial]
    initial = [(chunks[i], float(sims[i])) for i in order]

    reranked, rerank_status = rerank(question, initial)
    sent = reranked[:top_k_final]

    context = "\n\n".join(
        f"[chunk_id={c['chunk_id']} lecture_id={c['lecture_id']} start={c['start']:.2f}s end={c['end']:.2f}s]\n{c['text']}"
        for c, _, _ in sent
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Retrieved excerpts:\n\n{context}\n\nQuestion: {question}"},
    ]
    result = call_llm(messages, endpoint, max_tokens=max_tokens, mock=mock)

    def entry(c, **extra):
        return {"chunk_id": c["chunk_id"], "lecture_id": c["lecture_id"],
                "segment_ids": c["constituent_segment_ids"],
                "start": c["start"], "end": c["end"], "text": c["text"], **extra}

    return {
        "question_id": question_id,
        "search_scope": scope,
        "scope_label": scope_label,
        "question": question,
        "rewritten_query": question,  # no query rewriting in this version
        "initial_retrieved": [{"rank": i + 1, "score": s, **entry(c)} for i, (c, s) in enumerate(initial)],
        "reranked": [{"rank": i + 1, "rerank_score": rs, "embedding_score": es, **entry(c)}
                     for i, (c, rs, es) in enumerate(reranked)],
        "rerank_status": rerank_status,
        "chunks_sent_to_model": [entry(c) for c, _, _ in sent],
        "generated_answer": result["content"],
        "generation_provider": result["provider"],
        "generation_model": endpoint.model if (endpoint and not mock) else "mock",
        "embedding_model": EMBED_MODEL,
        "system_prompt_used": system_prompt,
        "finish_reason": result.get("finish_reason"),
        "reasoning_content_length": len(result.get("reasoning_content") or ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def run_questions(items, *, scope, scope_label, manifest, embeddings, trace_root: Path, **kwargs) -> Path:
    records = []
    for item in items:
        t0 = time.time()
        rec = answer_question(scope, scope_label, item["question_id"], item["question"],
                              manifest, embeddings, **kwargs)
        rec["elapsed_seconds"] = round(time.time() - t0, 2)
        records.append(rec)
        print(f"[rag] {item['question_id']}: scope={scope} rerank={rec['rerank_status']} "
              f"chunks_sent={len(rec['chunks_sent_to_model'])} elapsed={rec['elapsed_seconds']}s")
    out_dir = Path(trace_root) / (scope_label if scope == "lecture" else f"series_{scope_label}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[rag] wrote {len(records)} trace record(s) -> {out_path}")
    return out_path
