"""Corpus validation: candidate ranking, acceptance, and quotation-span replacement.

Implements the corpus-grounded validation of the paper (Eq. 1-4, Algorithm 1):

    s(c,e) = alpha * S_lexical(c,e) + (1-alpha) * S_semantic(c,e)          [Eq. 1]
    S_lexical(c,e) = (S_edit(c,e) + S_token(c,e)) / 2                       [Eq. 2]
    S_edit(c,e) = 1 - lev(q_e, t_c) / max(|q_e|, |t_c|)                    [Eq. 3]
    S_semantic(c,e) = cosine(embed(q_e), embed(t_c))                       (same embedding model)
    accept iff s(c*,e) >= tau  AND  s(c*,e) - s(c_2,e) >= delta            [Eq. 4]
    (margin condition omitted when only one candidate is retrieved)

The score is a corpus-match score, not a calibrated probability. alpha, tau and delta are passed
in explicitly by the caller (minaret.yaml `validation`); tau = 0.90 is the paper's
entity-validation threshold.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

from minaret.schemas import AyahEntity, CorpusValidation, DuaEntity, EntitySet, Segment

EmbedFn = Callable[[list[str]], list[list[float]]]  # texts -> embedding vectors, same model for both sides

# Defaults for minaret.yaml's `validation` block; TAU is the paper's entity-validation threshold.
DEFAULT_ALPHA = 0.7
DEFAULT_TAU = 0.9
DEFAULT_DELTA = 0.02

# Multilingual embedding model for S_semantic (the same model the RAG index uses).
DEFAULT_SEMANTIC_MODEL = "BAAI/bge-m3"

_default_model = None


def default_embed_fn(texts: list[str]) -> list[list[float]]:
    """Lazily loads BAAI/bge-m3 once per process. Not imported at module load time - a caller
    using only the lexical-scoring functions, or supplying their own embed_fn, never needs
    sentence-transformers installed at all."""
    global _default_model
    if _default_model is None:
        from sentence_transformers import SentenceTransformer
        _default_model = SentenceTransformer(DEFAULT_SEMANTIC_MODEL)
    return _default_model.encode(texts, normalize_embeddings=True).tolist()


# --- Normalisation ("removing diacritics, punctuation, Quranic annotation symbols, tatweel, and
# spacing variation, and normalising common orthographic variants" - used only for retrieval and
# scoring; the original canonical text is retained for quotation replacement, per the paper.) ---

_ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭࣔ-ࣣ࣡-ࣿ]")
_TATWEEL = "ـ"
_QURAN_ANNOTATION = re.compile(r"[ۖ-ۜ۞-۪ۤۧۨ-ۭ]")  # end-of-ayah marks, sajda, etc.
_PUNCTUATION = re.compile(r"[.,!?;:\"'()\[\]{}«»،؛؟۔۔،؛؟]")
_WHITESPACE = re.compile(r"\s+")

# Orthographic variant folding, including alef wasla (U+0671), which ordinary transcribed or typed
# Arabic does not reproduce and which would otherwise under-score an exact match. For scoring only;
# never applied to the canonical text that is substituted in.
_ALEF_VARIANTS = str.maketrans({
    "ٱ": "ا",  # ALEF WASLA -> ALEF
    "آ": "ا",  # ALEF WITH MADDA ABOVE -> ALEF
    "أ": "ا",  # ALEF WITH HAMZA ABOVE -> ALEF
    "إ": "ا",  # ALEF WITH HAMZA BELOW -> ALEF
    "ة": "ه",  # TEH MARBUTA -> HEH
    "ی": "ي",  # Urdu YEH -> Arabic YEH (letterform-confusion class documented in
                          # SKD2025_reference_validation.md: Urdu keyboards emit these inside
                          # Arabic quotations)
    "ک": "ك",  # Urdu KEHEH -> Arabic KAF
})


def normalize_for_matching(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _QURAN_ANNOTATION.sub("", text)
    text = text.replace(_TATWEEL, "")
    text = text.translate(_ALEF_VARIANTS)
    text = _PUNCTUATION.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


# --- Lexical scoring: Eq. 2 / Eq. 3 ---

def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def edit_score(q_e: str, t_c: str) -> float:
    """Eq. 3: S_edit(c,e) = 1 - lev(q_e, t_c) / max(|q_e|, |t_c|). Both inputs assumed already
    normalized by the caller."""
    denom = max(len(q_e), len(t_c))
    if denom == 0:
        return 1.0
    return 1.0 - (_levenshtein(q_e, t_c) / denom)


def token_f1(q_e: str, t_c: str) -> float:
    """Token-level F1 between the two normalized texts' whitespace-tokenized word sets
    (multiset overlap, so a repeated word counts each occurrence)."""
    tokens_a = q_e.split()
    tokens_b = t_c.split()
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    from collections import Counter
    ca, cb = Counter(tokens_a), Counter(tokens_b)
    overlap = sum((ca & cb).values())
    precision = overlap / len(tokens_a)
    recall = overlap / len(tokens_b)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def lexical_score(q_e_norm: str, t_c_norm: str) -> float:
    """Eq. 2: S_lexical(c,e) = (S_edit(c,e) + S_token(c,e)) / 2. Inputs must already be
    normalized (call normalize_for_matching first) - kept as a separate step so callers can
    normalize once per corpus row rather than on every comparison."""
    return (edit_score(q_e_norm, t_c_norm) + token_f1(q_e_norm, t_c_norm)) / 2


def semantic_score(q_e: str, t_c: str, *, embed_fn: EmbedFn) -> float:
    """Cosine similarity between multilingual embeddings of the two (non-normalized - the paper
    does not say semantic similarity uses the normalized text, and stripping diacritics/case
    before embedding would discard information a semantic model can legitimately use) texts,
    produced by the same model, per the paper's description."""
    import math
    vecs = embed_fn([q_e, t_c])
    a, b = vecs[0], vecs[1]
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def match_score(q_e: str, t_c: str, *, alpha: float, embed_fn: EmbedFn) -> float:
    """Eq. 1: s(c,e) = alpha * S_lexical(c,e) + (1-alpha) * S_semantic(c,e)."""
    lex = lexical_score(normalize_for_matching(q_e), normalize_for_matching(t_c))
    sem = semantic_score(q_e, t_c, embed_fn=embed_fn)
    return alpha * lex + (1 - alpha) * sem


# --- Corpus and ranking ---

@dataclass
class CorpusRow:
    key: str          # e.g. "CH001_V001" (ayah) or a dua_id
    text: str          # canonical text, untouched by normalization - this is what gets substituted in
    label: Optional[str] = None


def _read_csv(path: str) -> list[dict]:
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_quran_corpus(path: str) -> list[CorpusRow]:
    """Loads the Quran reference corpus from quran.csv (columns sura, aya, text, ...) or from a
    SQLite database with a `quran` table of the same columns. `text` is the Uthmani-diacritized
    form, the canonical text retained for quotation replacement."""
    if str(path).lower().endswith(".csv"):
        rows = [(int(r["sura"]), int(r["aya"]), r["text"]) for r in _read_csv(path)]
    else:
        import sqlite3
        con = sqlite3.connect(path)
        try:
            rows = con.execute("SELECT sura, aya, text FROM quran").fetchall()
        finally:
            con.close()
    return [CorpusRow(key=f"CH{s:03d}_V{a:03d}", text=t, label=f"{s}:{a}") for s, a, t in rows]


def load_dua_corpus(path: str) -> list[CorpusRow]:
    """Loads the Dua reference corpus from duas.csv (columns duaId, duaArabic, duaTitle_en, ...) or
    from a SQLite database with a `dua` table (dua_id, arabic, title_en). `text` is the unmodified
    Arabic; matching applies its own normalization (normalize_for_matching)."""
    if str(path).lower().endswith(".csv"):
        rows = [(r["duaId"], r["duaArabic"], r.get("duaTitle_en") or None) for r in _read_csv(path)
                if r.get("duaId") and r.get("duaArabic")]
    else:
        import sqlite3
        con = sqlite3.connect(path)
        try:
            rows = con.execute("SELECT dua_id, arabic, title_en FROM dua").fetchall()
        finally:
            con.close()
    return [CorpusRow(key=dua_id, text=arabic, label=title_en) for dua_id, arabic, title_en in rows]


@dataclass
class RankedCandidate:
    row: CorpusRow
    score: float


EMBEDDING_CACHE_DIR = Path.cwd() / ".minaret_cache" / "embeddings"
_corpus_vectors_memo: dict[tuple[int, str], "np.ndarray"] = {}


def _unit_rows(vecs) -> "np.ndarray":
    import numpy as np
    m = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return np.divide(m, norms, out=np.zeros_like(m), where=norms > 0)


def _corpus_vectors(corpus: list[CorpusRow], embed_fn: EmbedFn) -> "np.ndarray":
    """Unit-length embeddings of every corpus text, computed once per corpus and model: kept in
    memory for the process and, for the default model, on disk under .minaret_cache/embeddings/."""
    import numpy as np
    texts = [r.text for r in corpus]
    digest = hashlib.sha256("\x00".join(texts).encode("utf-8")).hexdigest()
    memo_key = (id(embed_fn), digest)
    if memo_key in _corpus_vectors_memo:
        return _corpus_vectors_memo[memo_key]
    disk = (EMBEDDING_CACHE_DIR / f"{DEFAULT_SEMANTIC_MODEL.replace('/', '_')}_{digest[:20]}.npy"
            if embed_fn is default_embed_fn else None)
    if disk is not None and disk.exists():
        vecs = np.load(disk)
    else:
        vecs = _unit_rows(embed_fn(texts))
        if disk is not None:
            disk.parent.mkdir(parents=True, exist_ok=True)
            np.save(disk, vecs)
    _corpus_vectors_memo[memo_key] = vecs
    return vecs


def rank_candidates(q_e: str, corpus: list[CorpusRow], *, alpha: float, embed_fn: EmbedFn,
                     limit: int = 5) -> list[RankedCandidate]:
    """Score every row in `corpus` against q_e per Eq. 1, return the top `limit` by score
    descending, scoring the full corpus (6,236 verses for the Quran). S_semantic is the cosine of the query embedding with the (cached) corpus embeddings, so the
    embedding model runs once per candidate rather than once per corpus row."""
    if not corpus:
        return []
    corpus_vecs = _corpus_vectors(corpus, embed_fn)
    query_vec = _unit_rows(embed_fn([q_e]))[0]
    sem = corpus_vecs @ query_vec
    q_norm = normalize_for_matching(q_e)
    scored = [RankedCandidate(row=row, score=alpha * lexical_score(q_norm, normalize_for_matching(row.text))
                              + (1 - alpha) * float(sem[i]))
              for i, row in enumerate(corpus)]
    scored.sort(key=lambda rc: rc.score, reverse=True)
    return scored[:limit]


OutcomeLabel = Literal["proposed_reference_confirmed", "alternative_reference_selected"]


def accept(ranked: list[RankedCandidate], *, tau: float, delta: float,
           proposed_key: Optional[str] = None) -> tuple[Optional[RankedCandidate], Optional[OutcomeLabel]]:
    """Eq. 4's acceptance rule. Returns (accepted_candidate_or_None, outcome_label_or_None).
    Margin condition is omitted when only one candidate was retrieved, per the paper."""
    if not ranked:
        return None, None
    top = ranked[0]
    if top.score < tau:
        return None, None
    if len(ranked) > 1:
        second = ranked[1]
        if top.score - second.score < delta:
            return None, None
    label: OutcomeLabel = (
        "proposed_reference_confirmed" if proposed_key is not None and top.row.key == proposed_key
        else "alternative_reference_selected"
    )
    return top, label


# --- Quotation-span replacement (targeted, not whole-segment) ---

def _normalize_with_index_map(text: str) -> tuple[str, list[int]]:
    """Same output as normalize_for_matching(text), but also returns a list mapping each
    character of that output back to the index of the `text` character it came from.

    Built as one pass over `text`, not by calling normalize_for_matching on each character
    independently — that approach was tried first and is wrong: normalize_for_matching's
    whitespace collapse (_WHITESPACE.sub + .strip()) behaves differently applied to a whole
    string versus applied separately to each single-character substring, since .strip() on a
    lone space character deletes it entirely. Applied per-character, every space in the segment
    vanishes and the two normalized forms silently diverge. Collapsing/stripping is done once
    here, over the full assembled sequence, exactly matching normalize_for_matching's own order
    of operations.
    """
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch):
            if _ARABIC_DIACRITICS.match(c) or _QURAN_ANNOTATION.match(c) or c == _TATWEEL:
                continue
            c = c.translate(_ALEF_VARIANTS)
            if _PUNCTUATION.match(c):
                c = " "
            chars.append(c)
            idx.append(i)

    collapsed_chars: list[str] = []
    collapsed_idx: list[int] = []
    prev_space = False
    for c, i in zip(chars, idx):
        if c.isspace():
            c = " "
            if prev_space:
                continue
            prev_space = True
        else:
            prev_space = False
        collapsed_chars.append(c)
        collapsed_idx.append(i)

    start = 0
    while start < len(collapsed_chars) and collapsed_chars[start] == " ":
        start += 1
    end = len(collapsed_chars)
    while end > start and collapsed_chars[end - 1] == " ":
        end -= 1
    return "".join(collapsed_chars[start:end]), collapsed_idx[start:end]


def _locate_and_replace(segment_text: str, quoted_fragment: str, canonical_text: str) -> Optional[str]:
    """Find quoted_fragment's span within segment_text (matching on normalized form, since the
    transcript's actual characters may differ from the extracted candidate's exact substring) and
    replace just that span with canonical_text. Returns None if no matching span is found, so the
    segment is left unchanged rather than guessed at."""
    norm_fragment = normalize_for_matching(quoted_fragment)
    if not norm_fragment:
        return None

    norm_segment, index_map = _normalize_with_index_map(segment_text)

    pos = norm_segment.find(norm_fragment)
    if pos == -1:
        return None
    start_orig = index_map[pos]
    end_orig = index_map[pos + len(norm_fragment) - 1] + 1
    return segment_text[:start_orig] + canonical_text + segment_text[end_orig:]


# --- Full pipeline step: Algorithm 1 ---

@dataclass
class ValidationOutcome:
    entities: EntitySet          # E1
    segments: list[Segment]      # V2
    replacements_applied: int = 0
    replacements_skipped_no_span: int = 0


def validate(entities: EntitySet, v1_segments: list[Segment], *, quran_corpus: list[CorpusRow],
             dua_corpus: list[CorpusRow], alpha: float, tau: float, delta: float,
             embed_fn: EmbedFn) -> ValidationOutcome:
    """Algorithm 1. Hadith and Topic candidates bypass corpus matching entirely (never corpus
    validated, per the paper - not an oversight, a deliberate scope decision) and are carried
    into E1 unchanged, pending reviewer validation. Ayah and Dua candidates are ranked against
    their corresponding corpus and either accepted (recorded in E1, quotation replaced in V2) or
    retained with ranked alternatives for human review."""
    v2_segments = [Segment(id=s.id, start=s.start, end=s.end, text=s.text) for s in v1_segments]
    v2_by_id = {s.id: s for s in v2_segments}

    replaced, skipped = 0, 0
    validated_ayat: list[AyahEntity] = []
    for candidate in entities.ayat:
        ranked = rank_candidates(candidate.text, quran_corpus, alpha=alpha, embed_fn=embed_fn)
        accepted, label = accept(ranked, tau=tau, delta=delta, proposed_key=candidate.key)
        if accepted is None:
            candidate.validation = CorpusValidation(
                verdict="unresolved" if not ranked or ranked[0].score < tau else "ambiguous",
                score=ranked[0].score if ranked else None,
                candidates=[{"key": r.row.key, "label": r.row.label, "score": r.score} for r in ranked],
            )
            validated_ayat.append(candidate)
            continue

        candidate.key = accepted.row.key
        candidate.canonical_text = accepted.row.text
        candidate.validation = CorpusValidation(
            verdict="verified", score=accepted.score,
            margin=(accepted.score - ranked[1].score) if len(ranked) > 1 else None,
            matched_reference_id=accepted.row.key, outcome=label,
            candidates=[{"key": r.row.key, "label": r.row.label, "score": r.score} for r in ranked],
        )
        validated_ayat.append(candidate)

        # locate which segment(s) this candidate's quotation lives in and apply the replacement
        applied = False
        for seg_id, seg in list(v2_by_id.items()):
            new_text = _locate_and_replace(seg.text, candidate.text, accepted.row.text)
            if new_text is not None:
                v2_by_id[seg_id] = Segment(id=seg.id, start=seg.start, end=seg.end, text=new_text)
                applied = True
                break
        if applied:
            replaced += 1
        else:
            skipped += 1

    validated_dua: list[DuaEntity] = []
    for candidate in entities.dua:
        ranked = rank_candidates(candidate.text, dua_corpus, alpha=alpha, embed_fn=embed_fn)
        accepted, label = accept(ranked, tau=tau, delta=delta, proposed_key=candidate.key)
        if accepted is None:
            candidate.validation = CorpusValidation(
                verdict="unresolved" if not ranked or ranked[0].score < tau else "ambiguous",
                score=ranked[0].score if ranked else None,
                candidates=[{"key": r.row.key, "label": r.row.label, "score": r.score} for r in ranked],
            )
            validated_dua.append(candidate)
            continue

        candidate.key = accepted.row.key
        candidate.canonical_text = accepted.row.text
        candidate.validation = CorpusValidation(
            verdict="verified", score=accepted.score,
            margin=(accepted.score - ranked[1].score) if len(ranked) > 1 else None,
            matched_reference_id=accepted.row.key, outcome=label,
            candidates=[{"key": r.row.key, "label": r.row.label, "score": r.score} for r in ranked],
        )
        validated_dua.append(candidate)

        applied = False
        for seg_id, seg in list(v2_by_id.items()):
            new_text = _locate_and_replace(seg.text, candidate.text, accepted.row.text)
            if new_text is not None:
                v2_by_id[seg_id] = Segment(id=seg.id, start=seg.start, end=seg.end, text=new_text)
                applied = True
                break
        if applied:
            replaced += 1
        else:
            skipped += 1

    # Hadith and Topic: pass through untouched, pending review - per the paper, never corpus
    # validated, this is a deliberate scope decision (no single authoritative source for Hadith
    # wording across its many acceptable renderings).
    e1 = EntitySet(ayat=validated_ayat, dua=validated_dua, hadith=entities.hadith, topics=entities.topics)
    return ValidationOutcome(
        entities=e1, segments=list(v2_by_id.values()),
        replacements_applied=replaced, replacements_skipped_no_span=skipped,
    )
