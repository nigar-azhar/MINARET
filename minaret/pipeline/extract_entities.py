"""LLM-based candidate entity extraction from V1 segments.

Produces unvalidated candidates only - per the paper (minaret_framework.tex): "Every extracted
candidate is treated as unvalidated... The proposed Quranic and Dua references are hypotheses
that must be checked against the corresponding canonical corpora" by corpus_validate.py. This
module never assigns a final `key`; it only ever proposes one (stored in the same `key` field,
which corpus_validate.py then either confirms, overwrites with a better-scoring alternative, or
leaves as an unresolved proposal for review).

Hadith never gets a proposed canonical key here, matching the paper's explicit scope decision
(no authoritative corpus exists to check Hadith wording against) - only Ayah and Dua propose one.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from minaret.pipeline.llm_json import parse_json_reply
from minaret.schemas import AyahEntity, DuaEntity, EntitySet, HadithEntity, Segment, TopicEntity

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "entity_extraction_v1.txt"


def _call_llm(base_url: str, api_key: str, model: str, system_prompt: str, segment_text: str,
              *, timeout: float = 60.0) -> str:
    import httpx
    r = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"SEGMENT:\n{segment_text}"},
            ],
            "temperature": 0,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


@dataclass
class ExtractionOutcome:
    entities: EntitySet
    error: Optional[str] = None  # set (entities empty) if the call/parse failed for this segment


def extract_from_segment(segment: Segment, *, base_url: str, api_key: str = "", model: str,
                          system_prompt: str, max_retries: int = 3) -> ExtractionOutcome:
    last_error: Optional[str] = None
    for _ in range(max_retries):
        try:
            raw = _call_llm(base_url, api_key, model, system_prompt, segment.text)
            parsed = parse_json_reply(raw)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        try:
            ayat = [
                AyahEntity(text=a["text"], surah_number=str(a.get("surah_number") or ""),
                           ayah_number=str(a.get("ayah_number") or ""), start=segment.start,
                           end=segment.end, usage=a.get("usage"), extent=a.get("extent"),
                           key=_proposed_ayah_key(a.get("surah_number"), a.get("ayah_number")))
                for a in parsed.get("ayat", []) if a.get("text")
            ]
            dua = [
                DuaEntity(text=d["text"], reference=d.get("reference") or "", start=segment.start,
                          end=segment.end, usage=d.get("usage"), extent=d.get("extent"))
                for d in parsed.get("dua", []) if d.get("text")
            ]
            hadith = [
                HadithEntity(text=h["text"], start=segment.start, end=segment.end, usage=h.get("usage"),
                              book=h.get("book"), number=h.get("number"), reference=h.get("reference"),
                              expanded_reference=h.get("expanded_reference"))
                for h in parsed.get("hadith", []) if h.get("text")
            ]
            # The prompt asks for name_en/description_en (+ Urdu); E1 keeps the English pair as
            # name/description, the form the released E1 files use. A bare "name" is accepted too.
            topics = [
                TopicEntity(name=t.get("name_en") or t["name"], description=t.get("description_en") or t.get("description"),
                            start=segment.start, end=segment.end)
                for t in parsed.get("topics", []) if t.get("name_en") or t.get("name")
            ]
            return ExtractionOutcome(entities=EntitySet(ayat=ayat, dua=dua, hadith=hadith, topics=topics))
        except (KeyError, TypeError) as exc:
            last_error = f"malformed extraction response: {type(exc).__name__}: {exc}"
            continue

    return ExtractionOutcome(entities=EntitySet(), error=last_error)


def _proposed_ayah_key(surah_number, ayah_number) -> Optional[str]:
    """CH{surah:03d}_V{ayah:03d}, the ayah key format used throughout. Returns None if either number is
    missing or non-numeric - a proposal the LLM couldn't confidently make, not an error."""
    try:
        s, a = int(surah_number), int(ayah_number)
    except (TypeError, ValueError):
        return None
    return f"CH{s:03d}_V{a:03d}"


def extract(segments: list[Segment], *, base_url: str, api_key: str = "", model: str,
            prompt_path: Optional[Path] = None) -> tuple[EntitySet, dict]:
    """Extract candidates from every segment and merge into one EntitySet. Returns
    (candidates, provenance) - provenance includes the prompt's SHA256."""
    prompt_path = prompt_path or PROMPT_PATH
    system_prompt = prompt_path.read_text(encoding="utf-8")
    prompt_sha256 = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()

    all_ayat, all_dua, all_hadith, all_topics = [], [], [], []
    failed_segments = []
    for seg in segments:
        outcome = extract_from_segment(seg, base_url=base_url, api_key=api_key, model=model,
                                        system_prompt=system_prompt)
        if outcome.error:
            failed_segments.append({"segment_id": seg.id, "error": outcome.error})
            continue
        all_ayat.extend(outcome.entities.ayat)
        all_dua.extend(outcome.entities.dua)
        all_hadith.extend(outcome.entities.hadith)
        all_topics.extend(outcome.entities.topics)

    provenance = {
        "model": model, "prompt_path": str(prompt_path), "prompt_sha256": prompt_sha256,
        "segments_processed": len(segments), "segments_failed": len(failed_segments),
        "failed_segments": failed_segments,
        "candidate_counts": {"ayat": len(all_ayat), "dua": len(all_dua),
                              "hadith": len(all_hadith), "topics": len(all_topics)},
    }
    return EntitySet(ayat=all_ayat, dua=all_dua, hadith=all_hadith, topics=all_topics), provenance
