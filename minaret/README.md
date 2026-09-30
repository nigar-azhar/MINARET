# `minaret` -- the approach

The MINARET pipeline as an importable package with a CLI. For install, configuration and
reproducing the paper, see the [repository README](../README.md). This page covers how to use the
package itself. [`ARCHITECTURE.md`](ARCHITECTURE.md) maps every module to the paper.

## Stages

| # | Stage | Module | Reads | Writes | CLI |
|---|---|---|---|---|---|
| 1 | ASR | `pipeline/transcribe.py` | audio (path or URL) | `v0.json` | `transcribe` |
| 2 | LLM transcript correction | `pipeline/correct.py` | `v0.json` | `v1.json` | `transcribe` (unless `--skip-correction`) |
| 3 | Entity extraction | `pipeline/extract_entities.py` | `v1.json` | candidates | `validate-entities` |
| 4 | Corpus-grounded validation | `pipeline/corpus_validate.py` | candidates, `v1.json`, Quran/Dua corpora | `e1.json`, `v2.json` | `validate-entities` |
| -- | Human review (**not included**) | your own process | `v2.json`, `e1.json` | reviewed V3, E2 | -- |
| 5 | Reviewed-input hand-off | `pipeline/ingest_reviewed.py` | reviewed V3, E2 | `v3.json`, `e2.json` | `ingest-reviewed` |
| 6 | Knowledge graph | `downstream/kg/` | `v3.json`, `e2.json`, series config | `instances/<SERIES>.ttl`, `minaret_combined.ttl` | `kg build`, `kg combine` |
| 7 | RAG index | `downstream/rag/index.py` | `v3.json` | `chunks.json`, `embeddings.npy` | `rag index` |
| 8 | RAG question answering | `downstream/rag/query.py` | index, questions | trace JSON | `rag query` |

Every stage appends to the recording's `trace.json`, recording which model, prompt (with its
hash), time and outcome produced each file. Stages 1-4 need an OpenAI-compatible LLM endpoint for
2-3, set in `minaret.yaml`. Stages 6-8 need no LLM except the answer model in stage 8.

## Where output goes

```
runs/                                   paths.runs_dir in minaret.yaml
  recordings/<series>/<recording>/      v0 v1 e1 v2 (+ v3 e2 after ingest-reviewed) + trace.json
  kg/instances/<SERIES>.ttl             kg build
  kg/series/<SERIES>_*.{json,md,txt}    topic proposals, topic dictionary, build log
  kg/minaret_combined.ttl               kg combine
  rag/index/<recording>/, rag/index/series/<series>/
  rag/traces/<recording or series_X>/<timestamp>.json
```

`kg build` and `rag index` read from `paths.recordings_root`. It defaults to the paper's
`artifacts/recordings`; pass `--recordings-root runs/recordings` to use your own.

## CLI

```bash
python -m minaret.cli transcribe <audio-path-or-url> --series-id S --recording-id R [--language ur]
python -m minaret.cli validate-entities runs/recordings/S/R
python -m minaret.cli ingest-reviewed  runs/recordings/S/R --v3 my_v3.json --e2 my_e2.json
python -m minaret.cli kg build   [--series S ...] [--recordings-root runs/recordings] [--out runs/kg]
python -m minaret.cli kg combine [--kg-dir runs/kg]
python -m minaret.cli rag index  --series S [--recording R ...] [--recordings-root runs/recordings]
python -m minaret.cli rag query  --scope lecture --recording R --question "..."   # or --questions-file
python -m minaret.cli rag query  --scope series  --series S   --question "..." [--mock]
```

`python -m minaret.cli <command> --help` lists every flag. You can override an LLM stage per run
with `--<stage>-base-url`, `--<stage>-model` and `--<stage>-prompt`, where the stage is
`correction`, `extraction` or `rag-answer`. `--mock` on `rag query` runs retrieval and reranking
but skips the answer model.

The correction and extraction prompts ask for a single JSON object. Replies that wrap it in a
` ```json ` fence or put a `<think>` block first (common with local models) are accepted
(`pipeline/llm_json.py`); a reply with no usable object counts as a failed attempt, and after three
the segment keeps its text (correction) or yields no candidates (extraction).

Corpus validation embeds the Quran and Dua corpora with `BAAI/bge-m3` once and caches the vectors
in `.minaret_cache/embeddings/` under the working directory (about two minutes the first time on a
CPU); after that each candidate takes about a second.

## Python API

```python
from pathlib import Path
from minaret import config
from minaret.pipeline.run import run_v0_v1, run_e1_v2
from minaret.pipeline.ingest_reviewed import ingest
from minaret.downstream.kg.build import build_all
from minaret.downstream.kg.combine import combine
from minaret.downstream.rag.index import build_lecture_index, build_series_index
from minaret.downstream.rag.query import load_index, run_questions

cfg = config.load()                      # minaret.yaml + .env
corr = cfg.llm("correction")             # base_url, model, api_key, prompt

rec = run_v0_v1("lecture.mp3", output_root=Path("runs/recordings"), series_id="S", recording_id="R",
                correction_base_url=corr.base_url, correction_api_key=corr.api_key,
                correction_model=corr.model, correction_prompt=corr.prompt)
ext = cfg.llm("extraction")
run_e1_v2(rec, quran_corpus_db=str(cfg.path("corpora.quran_db")), dua_corpus_db=str(cfg.path("corpora.dua_db")),
          extraction_base_url=ext.base_url, extraction_api_key=ext.api_key, extraction_model=ext.model,
          extraction_prompt=ext.prompt, alpha=0.7, tau=0.5, delta=0.02)

ingest(rec, v3_path=Path("reviewed_v3.json"), e2_path=Path("reviewed_e2.json"))

build_all([Path("artifacts/kg/series/S.json")], recordings_root=Path("runs/recordings"), out_dir=Path("runs/kg"),
          quran_csv=cfg.path("corpora.quran_csv"), duas_csv=cfg.path("corpora.duas_csv"),
          hadith_dump=cfg.path("corpora.semantic_hadith_dump"), cache_dir=cfg.path("corpora.cache_dir"))
combine(Path("runs/kg/instances"), Path("runs/kg/minaret_combined.ttl"))

build_lecture_index(rec / "v3.json", series="S", recording_id="R", index_root=Path("runs/rag/index"))
manifest, emb = load_index(Path("runs/rag/index"), scope="lecture", recording_id="R")
run_questions([{"question_id": "Q1", "question": "..."}], scope="lecture", scope_label="R",
              manifest=manifest, embeddings=emb, trace_root=Path("runs/rag/traces"),
              endpoint=cfg.llm("rag_answer"), system_prompt=cfg.llm("rag_answer").prompt.read_text())
```

Each stage function can also be called on its own, for example
`correct.correct(segments, base_url=..., model=...)` or `corpus_validate.validate(...)`, if you
want to swap in your own implementation of one stage.

## File formats

**Transcripts** (`v0`-`v3`): a list of segments, `[{"start": s, "end": s, "text": "...", "id": "..."}]`.
The `id` is optional.

**Entities** (`e1`, `e2`): an object with lists `ayat`, `hadith`, `dua`, `topics` and `headings`.
The reviewed `e2.json` the KG reads needs these fields:

```json
{
  "ayat":     [{"surah_number": "2", "ayah_number": "255", "text": "...", "start": 0.0, "end": 9.5,
                "usage": "quotation|translation|explicit paraphrase", "extent": "complete|partial"}],
  "hadith":   [{"reference": "SB_723", "expanded_reference": "Sahih al-Bukhari 723", "text": "...",
                "start": 0.0, "end": 9.5, "usage": "quotation"}],
  "dua":      [{"reference": "QuranicDua-08", "text": "...", "start": 0.0, "end": 9.5,
                "usage": "quotation", "extent": "complete"}],
  "topics":   [{"name_en": "...", "description_en": "...", "name_ur": "...", "description_ur": "...",
                "start": 0.0, "end": 60.0, "renamed_from": "optional original name"}],
  "headings": [{"title_en": "...", "title_ur": "...", "start": 0.0, "end": 60.0}]
}
```

`ingest-reviewed` checks exactly these fields. It rejects files that would break the KG or RAG
build and warns about recoverable problems.

**Series config** (`artifacts/kg/series/<SERIES>.json`, one per series, needed by `kg build`).
Copy a shipped one and edit it:

```json
{
  "series_code": "MYSERIES",
  "recordings_dir": "MySeries",
  "category": "Hadith",
  "series":   {"title_en": "...", "title_ur": "...", "category_id": 0, "series_type": "..."},
  "speaker":  {"code": "speaker_code", "name_en": "...", "name_ur": "..."},
  "language": {"code": "ur", "label": "Urdu"},
  "recordings": [{"recording_id": "L01", "kg_recording_id": "MYSERIES-0001",
                  "audio": {"audio_link": "https://...", "english_name": "...", "urdu_name": "...",
                            "duration": "00:45:10"}}],
  "concept_keywords":  {"hadith:PillarsOfIslam": ["salah", "zakah"]},
  "reviewed_merges":   [{"topics": ["Topic A", "Topic B"], "decision": "accept|reject|reject_but_related"}],
  "reviewed_concepts": [{"topic": "Topic A", "concept": "hadith:PillarsOfIslam", "decision": "accept|reject"}],
  "topic_related": [], "hub_related": null, "manual_concept_matches": []
}
```

On a first build, leave `reviewed_merges` and `reviewed_concepts` empty. The builder writes its
merge and concept-mapping proposals to `kg/series/<SERIES>_topic_proposals.json`. Record your
decisions on them in the config, then rebuild.

## Prompts

`prompts/` holds every prompt the paper used: `correction_v1.txt`, `entity_extraction_v1.txt`,
`rag_answer_v1.txt` (the RQ5 runs) and `rag_answer_strict_v2.txt` (an alternative). Point
`llm.<stage>.prompt` in `minaret.yaml`, or `--<stage>-prompt`, at your own file to change one.
`trace.json` records the path and SHA-256 of the correction and extraction prompts each run used,
and every RAG trace stores its full system prompt.
