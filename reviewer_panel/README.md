# Reviewer panel

A local web panel for the human-review stage of MINARET: it loads a recording's **V2** transcript
and **E1** entity set and produces **V3** and **E2** in the pipeline's established format.

**This is a simulator, not the review application used for the paper.** The paper's review was
done in a purpose-built application from an industry collaboration, which is not released (see the
paper's Tool and Data Availability statement). This panel reproduces the review workflow the paper
describes, so the stage can be run, inspected and re-created without it. It has no users, login,
database or job queue, and it keeps no timing log.

The panel only reads `minaret/`, `artifacts/` and `evaluation/rq4_kg/cqs/`, and writes only
under `runs/`, plus `minaret.local.yaml` and `.env` when you save Settings (both gitignored).
Nothing it does changes the released artifacts.

## Run

```bash
python -m reviewer_panel            # then open http://127.0.0.1:8765
python -m reviewer_panel --port 9000 --config path/to/minaret.yaml
```

`/` is the MINARET landing page, which follows one real segment of the released data through every
stage; the panel is at `/review` (`/review#pipeline`, `#ask` and `#settings` open those tabs). The
same landing page can be written out as static files for any web host, reading its examples from
the released artifacts:

```bash
python -m reviewer_panel.landing --out docs
```

It uses only the Python standard library plus the `minaret` package. Individual features need
what the corresponding pipeline stage needs, and each one says what is missing when it can't run:

| Feature | Needs |
|---|---|
| Review, super review, finalize, replay | nothing extra |
| AI suggestion on a segment | `llm.correction` endpoint reachable |
| Transcribe | `faster-whisper` (`pip install -e ".[asr]"`) |
| Correct | `llm.correction` endpoint |
| Extract + validate | `llm.extraction` endpoint, the Quran and Dua corpora (`quran.csv` / `duas.csv`), `sentence-transformers` |
| Build KG | `rdflib`, `corpora.quran_csv` / `duas_csv` / `semantic_hadith_dump`, the series config |
| Build RAG index, RAG questions | `sentence-transformers` (bge-m3 and the reranker download on first use) |
| RAG answers | `llm.rag_answer` endpoint. Without it, retrieval still runs and shows the chunks |
| KG questions | `rdflib` |

Endpoints, models and prompts come from `minaret.yaml` (plus `minaret.local.yaml`, written by the
Settings tab), and API keys from the environment or `.env`, exactly as for the command line. If an
LLM server is not running (e.g. LM Studio is off), rejects the key, or does not list the configured
model, the header shows it and the action explains it, instead of failing.

## Tabs

**Review: first-level review** (paper, "First-Level Human Review")
- The transcript segments run in order on the left. Clicking a time plays exactly that interval of
  the audio (from the publisher's URL in `source.json`, or the local file recorded in `trace.json`).
- Headings are section dividers in the transcript, placed where each heading's span starts; a page
  that begins mid-section repeats its heading. Clicking a divider opens the heading for review.
- Clicking a segment opens the panel on the right with two groups: *Starts here* (the ayat, hadith
  and dua that start in the segment, also counted per type on the segment) and *Covering this
  segment* (every topic and heading whose start-end span includes it).
- *Show span* on a topic or heading highlights every segment it covers and jumps to the first one.
- Topics and headings show the lecture's language first (English or Urdu, from the series config
  or, for a new recording, the language ASR detected), with the other language beneath.
- Segments: *Accept*, *Correct* (text and timestamps), *Insert* (omitted speech), *Remove*
  (duplicate), *Split* at the text cursor, *Merge* with the next segment, and the optional
  *AI suggestion* (the V1 correction prompt; the reviewer decides what to keep).
- Entities (ayah, hadith, dua, topic, heading): *Accept*, *Correct* (text, type, reference or
  fields), *Reject*, and *+ Entity* for a missed one. *Canonical* shows the corpus text (Quran,
  Dua, SemanticHadith). Topics can be set as *Lecture-level* or tied to a *Segment group*.
- *Flag* records the issue type (the paper's categories: missing text, incorrect text, missing
  diacritics, incorrect Quranic/Hadith/Dua quotation, missing reference, extraneous content), the
  selected span and a note. A flag is either *Resolved* by the reviewer or sent to super review
  with *Need Review*.
- *Finalize V3 / E2* is refused while any flag is open or escalated (the paper's completion
  criterion). When allowed, V3 and E2 are checked by `minaret.pipeline.ingest_reviewed` and written
  to `runs/recordings/<series>/<recording>/`, with the reviewer's inputs (V0, V1, V2, E1) alongside.

**Super review** (paper, "Super-Review and Completion Criterion")
- Every item marked *Need Review*, with its segment, audio and entity (and its canonical text). The
  super reviewer can change the wording or the entity, then records the final decision. Only the
  super reviewer can close an escalated item.

**Pipeline**
- One button per automatic stage, runnable separately: Transcribe (V0), Correct (V1), Extract +
  validate (E1, V2), then, for finalized recordings, Build KG and Build RAG index. Stages run in
  the background and write to `runs/`.
- Build KG and Build RAG index are chosen from dropdowns listing only what can be built: the
  series and recordings finalized under `runs/`. Build KG says which recordings it will include; a
  series without a series config is listed but cannot be picked (see `minaret/README.md`, "Series
  config"), and finalized recordings missing from the config are named as left out.

**Ask**
- RAG questions over the released indices (`artifacts/rag/index`) or ones built here
  (`runs/rag/index`), at lecture or series scope, showing the answer, the chunks sent to the model
  and the initial retrieval.
- SPARQL over the released KG or one built here: the 16 competency questions from
  `evaluation/rq4_kg/cqs/`, or your own SELECT/ASK query.

**Settings**
- The three LLM stages (correction, extraction, RAG answers): server preset (LM Studio, Ollama,
  OpenRouter, OpenAI) or any OpenAI-compatible URL, model (with the list the server offers after
  *Test connection*), API key and prompt. Each card notes the model the paper used.
- Transcription language (auto-detect, Urdu, English, Arabic); the ASR model stays the paper's.
- Corpus validation α, τ, δ (τ = 0.9 is the paper's threshold), RAG chunk length and top-k, and the
  corpus file locations, each marked found or not found.
- Saving writes only the values that differ from `minaret.yaml` to the gitignored
  `minaret.local.yaml`, and keys to the gitignored `.env`; keys are never shown again. *Restore
  defaults* removes `minaret.local.yaml`. The command line reads the same files.

## Replay

For recordings that already have a reviewed V3/E2 (all of `artifacts/recordings/`), *Replay review*
restarts the review from V2/E1 and reconstructs a sequence of reviewer actions that produces that
V3/E2. You can step through it one action at a time, ten at a time, or run it to the end, then
finalize. Replaying the whole way reproduces the released V3 and E2 exactly, for all 18 recordings
(`reviewer_panel/tests`).

The actions are a reconstruction: the original review did not record individual actions. The end
state is exact; the path is a plausible one. It follows the transcript in time order, and handles
each segment's entities together with it:
- Transcript: V2 and V3 are aligned by time overlap. Each overlap group becomes accept, correct,
  merge, split, insert or remove.
- Entities: E1 and E2 are matched with the identity keys RQ2 uses (surah:ayah or reference, plus
  start time). Matched items are accepted or corrected, unmatched E1 items rejected, and unmatched
  E2 items added.

The reconstruction is least literal where review restructured a lot, e.g. restored omitted
recitation, or the SKD2025 0001/0004 resegmentation. Flags and escalations are not replayed,
because no record of them exists.

## Files

```
reviewer_panel/
  server.py     local HTTP server and JSON API (standard library)
  session.py    review state and every reviewer action; finalize -> V3/E2
  replay.py     reconstructs reviewer actions from V2/E1 to a known V3/E2
  services.py   recordings, canonical text, LLM checks, pipeline jobs, KG/RAG builds, questions
  settings.py   the Settings tab: minaret.local.yaml and .env
  landing.py    the landing page's examples (from artifacts/) and its static export
  static/       the single-page UI (HTML/CSS/JS, no build step)
  tests/        pytest reviewer_panel/tests
```

Review state is saved under `runs/review_panel/sessions/`, so a review can be closed and resumed.
*Restart review* discards it and starts again from V2/E1.
