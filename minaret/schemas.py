"""Shared data types for the minaret/ pipeline.

Every stage in this package reads and writes these shapes. Kept intentionally small and
framework-free (plain dataclasses, JSON-serializable) so this package has no hard dependency on
any particular storage layer — a caller can persist these however it wants.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Optional


@dataclass
class Segment:
    """One transcript segment. This shape is the wire format at every pipeline stage
    (V0 through V3) — stages only ever change `text` (and, for V0, assign `id`); they never
    change `start`/`end`/`id` semantics once assigned.
    """
    id: str
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


EntityUsage = Literal["quotation", "translation", "paraphrase"]
EntityExtent = Literal["complete", "partial", "unknown"]


@dataclass
class AyahEntity:
    """A Quranic verse citation. Corpus-validated: `canonical_text` and `validation` are filled
    in by the corpus-validation stage, not by entity extraction."""
    text: str
    surah_number: str
    ayah_number: str
    start: float
    end: Optional[float] = None
    usage: Optional[EntityUsage] = None
    extent: Optional[EntityExtent] = None
    key: Optional[str] = None  # CH{surah:03d}_V{ayah:03d}, assigned after corpus validation
    canonical_text: Optional[str] = None
    validation: Optional["CorpusValidation"] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.validation is not None:
            d["validation"] = self.validation.to_dict()
        return d


@dataclass
class DuaEntity:
    """A supplication (dua) citation. Corpus-validated like an ayah: Quranic verses and duas get
    corpus grounding, hadith do not."""
    text: str
    reference: str
    start: float
    end: Optional[float] = None
    usage: Optional[EntityUsage] = None
    extent: Optional[EntityExtent] = None
    key: Optional[str] = None
    canonical_text: Optional[str] = None
    validation: Optional["CorpusValidation"] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.validation is not None:
            d["validation"] = self.validation.to_dict()
        return d


@dataclass
class HadithEntity:
    """A Hadith citation. Deliberately never corpus-validated: no single
    authoritative Urdu-text Hadith source exists to check wording against. Extracted and carried
    to review as-is."""
    text: str
    start: float
    book: Optional[str] = None
    number: Optional[str] = None
    reference: Optional[str] = None
    end: Optional[float] = None
    usage: Optional[EntityUsage] = None
    key: Optional[str] = None  # {BOOK_CODE}-HD{number}, e.g. SB-HD4877
    expanded_reference: Optional[str] = None  # the model's fuller citation, for the reviewer

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TopicEntity:
    name: str
    description: Optional[str] = None
    start: Optional[float] = None
    end: Optional[float] = None
    key: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CorpusValidation:
    """Real, scored evidence from the corpus matcher (minaret.pipeline.corpus_validate) — not an
    LLM's self-report. `outcome` mirrors the paper's two labels for an accepted match: whether
    the winning candidate matched the LLM's own proposed reference, or a different one was
    selected instead (*proposed reference confirmed* / *alternative reference selected*)."""
    verdict: Literal["verified", "ambiguous", "unresolved"]
    score: Optional[float] = None
    margin: Optional[float] = None
    matched_reference_id: Optional[str] = None
    outcome: Optional[Literal["proposed_reference_confirmed", "alternative_reference_selected"]] = None
    candidates: list = field(default_factory=list)  # top-N {reference_id, label, score}

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EntitySet:
    ayat: list[AyahEntity] = field(default_factory=list)
    dua: list[DuaEntity] = field(default_factory=list)
    hadith: list[HadithEntity] = field(default_factory=list)
    topics: list[TopicEntity] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ayat": [e.to_dict() for e in self.ayat],
            "dua": [e.to_dict() for e in self.dua],
            "hadith": [e.to_dict() for e in self.hadith],
            "topics": [e.to_dict() for e in self.topics],
        }
