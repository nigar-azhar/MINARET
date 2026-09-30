"""V1: general linguistic correction of V0 segments via an LLM.

One segment per request, text-only in and out. The model never sees or returns segment ids or
timestamps; they stay in application code, so segment identity never depends on model output.

Any OpenAI-compatible endpoint works: local LM Studio/Ollama, OpenRouter, or a direct provider.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from minaret.pipeline.llm_json import parse_json_reply
from minaret.schemas import Segment

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "correction_v1.txt"

# Acceptance window for a corrected segment: base-character ratio 0.90-1.10 with Arabic marks
# removed before comparison, word ratio 1.00-1.15 (correction may add diacritics/joining, never
# drop words).
CHAR_RATIO_BOUNDS = (0.90, 1.10)
WORD_RATIO_BOUNDS = (1.00, 1.15)

_ARABIC_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")


def _strip_marks(text: str) -> str:
    return _ARABIC_MARKS.sub("", text)


def _word_count(text: str) -> int:
    return len(text.split())


def _passes_validation(original: str, corrected: str) -> bool:
    if not corrected.strip():
        return False
    orig_chars = len(_strip_marks(original)) or 1
    new_chars = len(_strip_marks(corrected))
    char_ratio = new_chars / orig_chars
    if not (CHAR_RATIO_BOUNDS[0] <= char_ratio <= CHAR_RATIO_BOUNDS[1]):
        return False
    orig_words = _word_count(original) or 1
    new_words = _word_count(corrected)
    word_ratio = new_words / orig_words
    return WORD_RATIO_BOUNDS[0] <= word_ratio <= WORD_RATIO_BOUNDS[1]


@dataclass
class CorrectionOutcome:
    segment: Segment
    changed: bool
    fallback: bool  # true if the model's output was rejected and the original text was kept
    raw_response: Optional[str] = None
    error: Optional[str] = None


def _call_llm(base_url: str, api_key: str, model: str, system_prompt: str, target_text: str,
              *, timeout: float = 60.0) -> str:
    import httpx
    r = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"TARGET:\n{target_text}"},
            ],
            "temperature": 0,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def correct_segment(segment: Segment, *, base_url: str, api_key: str = "", model: str,
                     system_prompt: str, max_retries: int = 3) -> CorrectionOutcome:
    last_error: Optional[str] = None
    for attempt in range(max_retries):
        try:
            raw = _call_llm(base_url, api_key, model, system_prompt, segment.text)
            parsed = parse_json_reply(raw)
            corrected_text = parsed["text"]
        except Exception as exc:  # noqa: BLE001 - deliberately broad: any failure here falls back
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        if _passes_validation(segment.text, corrected_text):
            new_segment = Segment(id=segment.id, start=segment.start, end=segment.end, text=corrected_text)
            return CorrectionOutcome(segment=new_segment, changed=corrected_text != segment.text,
                                      fallback=False, raw_response=raw)
        last_error = "validation failed (char/word ratio out of bounds, or empty result)"

    # All attempts failed or were rejected: keep the original text, but record why.
    return CorrectionOutcome(segment=segment, changed=False, fallback=True, error=last_error)


def correct(segments: list[Segment], *, base_url: str, api_key: str = "", model: str,
            prompt_path: Optional[Path] = None) -> tuple[list[Segment], dict]:
    """Correct every segment. Returns (V1 segments, provenance dict) — provenance includes the
    prompt's SHA256 (not just its file path — filenames are not immutable versions, per this
    project's own prompt-tracking convention) and per-segment outcome counts."""
    prompt_path = prompt_path or PROMPT_PATH
    system_prompt = prompt_path.read_text(encoding="utf-8")
    prompt_sha256 = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()

    outcomes = [
        correct_segment(seg, base_url=base_url, api_key=api_key, model=model, system_prompt=system_prompt)
        for seg in segments
    ]

    provenance = {
        "model": model,
        "prompt_path": str(prompt_path),
        "prompt_sha256": prompt_sha256,
        "total_segments": len(outcomes),
        "changed": sum(1 for o in outcomes if o.changed),
        "fallback": sum(1 for o in outcomes if o.fallback),
        "fallback_reasons": [o.error for o in outcomes if o.fallback and o.error],
    }
    return [o.segment for o in outcomes], provenance
