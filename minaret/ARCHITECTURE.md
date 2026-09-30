# minaret/ — architecture

What each module does and where it maps onto the paper. The package covers every automatic stage;
the human review that turns V2/E1 into V3/E2 happens outside it (the paper's review application is
not released; `reviewer_panel/` simulates that stage), and `ingest_reviewed.py` takes the reviewed
files back in.

## `schemas.py`

Shared data types: `Segment` (one shape carried through V0→V3; only `text` changes),
`AyahEntity`, `DuaEntity`, `HadithEntity`, `TopicEntity`, `CorpusValidation`, `EntitySet`.
Plain dataclasses with no storage dependency.

**Paper**: the entity fields of the framework section — `usage` (quotation / translation /
paraphrase), `extent` (complete / partial), a proposed vs. confirmed `key`, and
`CorpusValidation.outcome` (*proposed reference confirmed* / *alternative reference selected*).

## `trace.py`

Per-recording `trace.json`, appended to as each stage runs: which stage produced which file, with
what model, prompt hash and outcome.

## `pipeline/transcribe.py` — V0

Local path or HTTP(S) URL → faster-whisper `large-v3-turbo` (CPU, int8) → segments merged by word
count (at least 8, aiming for 15 words). The model is the one chosen in the ASR model-selection
study (`evaluation/asr_model_selection/`).

**Paper**: Framework Overview, the Whisper-based ASR that produces V0.

## `pipeline/correct.py` — V1

One segment at a time, text in and out, with a single-key JSON reply (`{"text": "..."}`). A reply
is accepted only within a character ratio of 0.90–1.10 (Arabic marks stripped) and a word ratio of
1.00–1.15; otherwise the segment keeps its text and the reason is recorded. Prompt:
`prompts/correction_v1.txt`.

**Paper**: LLM-Based Transcript Correction.

## `pipeline/extract_entities.py`

LLM candidate extraction from V1: ayah, hadith, dua, topic. Ayah and dua candidates carry a
proposed reference (`key`), a hypothesis until validated; hadith get none. Prompt:
`prompts/entity_extraction_v1.txt`.

**Paper**: Domain Entity Processing.

## `pipeline/corpus_validate.py` — E1 / V2

The corpus-match score, acceptance rule and quotation-span replacement. Each candidate is ranked
against the whole canonical corpus by the hybrid lexical + semantic score; the top candidate is
accepted only if it clears the threshold τ and the margin δ over the runner-up, and on acceptance
only the quoted span in the transcript is replaced with the canonical text. Needs a Quran and a Dua
SQLite corpus (`load_quran_corpus`, `load_dua_corpus`), which are not shipped.

**Paper**: Corpus-grounded validation, Eq. 1–4 and Algorithm 1 (the equations are quoted in the
module docstring).

## `pipeline/ingest_reviewed.py`

Takes reviewed V3 + E2, checks them against the fields the KG builder and RAG indexer read
(segment start/end/text, entity fields, the usage/extent vocabularies), copies them into the
recording directory and records the `reviewed_input` trace stage. Problems that would break a
downstream stage raise; recoverable oddities (out-of-order segments, entities outside the
transcript span) are returned as warnings.

**Paper**: the boundary between Human-in-the-Loop Review and everything downstream of it.

## `downstream/kg/` — knowledge-graph construction

`build.py` builds one series' instance data from its recordings' `v3.json` + `e2.json` and a
per-series config (`artifacts/kg/series/<SERIES>.json`: series, speaker and recording metadata plus
the recorded topic-merge and concept-mapping decisions). `common.py` holds the shared machinery
(canonical Quran/Dua/Hadith lookup, SemanticHadith / Quran Ontology / SemanticTafsir alignment,
topic deduplication and the cross-series topic registry); `hadith_blocks.py` streams the
SemanticHadith dump for just the cited hadith; `combine.py` merges `schema.ttl` with every series
TTL. Rebuilding from the released artifacts is isomorphic to the released TTLs.

**Paper**: Knowledge Graph Construction; RQ4.

## `downstream/rag/` — retrieval-augmented QA

`chunk.py` (segment-preserving chunks of about 30 s), `index.py` (bge-m3 lecture and series
indices), `query.py` (cosine top-10 → bge-reranker-v2-m3 → top-4 to any OpenAI-compatible answer
model, with a full per-question trace).

**Paper**: Retrieval-Augmented Generation; RQ5.

## `pipeline/run.py` / `cli.py`

`run_v0_v1` (V0→V1) and `run_e1_v2` (from `v1.json` through extraction and corpus validation to
`e1.json`/`v2.json`); every stage is also callable on its own. `cli.py` exposes `transcribe`,
`validate-entities`, `ingest-reviewed`, `kg build|combine` and `rag index|query`, with defaults
from `minaret.yaml` via `config.py` and API keys from the environment or `.env`.

## `calibration/`

An offline tool, not part of the pipeline: `build_gold_set.py` derives a gold set of E1 ayah/dua
candidates labelled from their reviewed E2 counterparts, and `sweep.py` grid-searches α/τ/δ over
it (`CALIBRATION_RESULTS.md`, `sweep_results.json`).

## Scope limits

- Corpus validation is designed for quotations: translated or paraphrased ayat cannot be matched
  lexically against an Arabic corpus and go to review unresolved.
- Multi-verse ranges ("25-28") have no single corpus row to match.
- A quotation split across two segments is not replaced.
- Hadith are not corpus-validated (as in the paper); headings are produced by review, not by an
  extraction stage.
