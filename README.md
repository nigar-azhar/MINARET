# MINARET

Code and released artifacts for the MINARET paper: automatic transcription and correction of
multilingual Islamic lecture audio, corpus-grounded validation of cited Quranic verses and Duas,
human-in-the-loop review, and two downstream knowledge tasks built on the reviewed output (a
knowledge graph and retrieval-augmented question answering).

The core is three parts that depend on each other only through files, plus the reviewer panel
and the project page:

```
minaret/          the approach -- an importable package + CLI
  pipeline/         V0 -> V1 -> E1/V2  (transcribe, correct, extract, corpus-validate)
                    + ingest_reviewed.py: the hand-off point for reviewed V3/E2
  downstream/kg/    knowledge-graph construction (schema.ttl, per-series builder, combine)
  downstream/rag/   chunking, bge-m3 indexing, rerank + answer generation
  prompts/          every LLM prompt used
  calibration/      alpha/tau/delta calibration of corpus validation
artifacts/        what the approach produced for the paper's 18 recordings (read-only)
evaluation/       RQ1-RQ5, reading only from an artifact tree
reviewer_panel/   local web panel: the landing page, review (a simulator of the paper's review
                  stage), every pipeline stage, RAG/KG questions and settings
docs/             the landing page as static files (python -m reviewer_panel.landing --out docs)
minaret.yaml      models, endpoints, prompts, paths (API keys go in .env, never here)
```

Usage of the package itself -- every stage, the CLI, the Python API and the file formats -- is in
[`minaret/README.md`](minaret/README.md).

`minaret/` never imports `evaluation/`. `evaluation/` never writes to `artifacts/`. New runs of the
pipeline write to `runs/` (gitignored) using the same layout as `artifacts/`, so every evaluation
script can score either one.

## Pipeline artifacts

| Artifact | Produced by | File |
|---|---|---|
| V0 | Whisper ASR (faster-whisper large-v3-turbo) | `v0.json` |
| V1 | LLM transcript correction | `v1.json` |
| E1 | LLM entity extraction + corpus-grounded validation | `e1.json` |
| V2 | V1 with validated canonical quotations substituted | `v2.json` |
| V3 | Human-reviewed transcript | `v3.json` |
| E2 | Human-reviewed entity set | `e2.json` |
| KG | `downstream/kg` from V3 + E2 | `artifacts/kg/` |
| RAG index / traces | `downstream/rag` from V3 | `artifacts/rag/` |

Per recording: `artifacts/recordings/<series>/<recording>/{v0,v1,v2,v3,e1,e2}.json` + `source.json`
(audio URL; audio is not redistributed). See [`artifacts/README.md`](artifacts/README.md).

**Not included:** the reviewer application that turns V2/E1 into V3/E2 (see the paper's Tool and
Data Availability statement). Any review process that emits `v3.json`/`e2.json` in the documented
shape can take its place: `python -m minaret.cli ingest-reviewed`.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all,test]"      # or pick extras: asr, kg, rag
cp .env.example .env              # only if your LLM endpoints need keys
```

Python 3.11+. The RAG stage downloads `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3` on first use.
The KG build and corpus validation need third-party corpora that are not redistributed; see
[`artifacts/corpora/README.md`](artifacts/corpora/README.md).

## Configure

Edit [`minaret.yaml`](minaret.yaml), or use the reviewer panel's **Settings** tab
(`python -m reviewer_panel`). Each LLM stage (`correction`, `extraction`, `rag_answer`) has its own
`base_url`, `model`, `prompt`, and `api_key_env`, the *name* of the environment variable holding
its key. Any OpenAI-compatible endpoint works: LM Studio, Ollama, vLLM, OpenRouter or a hosted
provider. No keys or accounts ship with the repository; put your own in `.env` (see
[`.env.example`](.env.example)).

The shipped defaults point every stage at a local LM Studio server. The paper used GPT-OSS-120B
via OpenRouter for correction (Nemotron-3-Super-120B-A12B as fallback), Gemini 2.5 Flash for
extraction, and local models (Gemma-4-E4B, Qwen3.5-9B, Llama-3.1-8B) for RAG answers; it found
that no local model it piloted corrected transcripts reliably enough to run unattended. In our
tests the default `qwen3.5-9b-mlx` also repeats itself on the correction prompt until it runs out
of tokens, so every segment keeps its V0 text. For usable V1 transcripts, point `llm.correction`
at a stronger model.

Settings you change locally can go in a gitignored `minaret.local.yaml` next to `minaret.yaml`,
holding only the values that differ; it is merged over `minaret.yaml` by both the CLI and the
panel (the Settings tab writes it). Every value can also be overridden per run with CLI flags, for
example `--correction-model`, `--rag-answer-base-url` or `--extraction-prompt my_prompt.txt`.

## Reproduce the paper's results

```bash
python evaluation/run_all.py
```

This recomputes RQ1-RQ5 from `artifacts/` into `evaluation/rq*/results/`. See
[`evaluation/README.md`](evaluation/README.md) for what each RQ computes. To rebuild the
downstream artifacts themselves, you need the corpora for the KG and the embedding models for RAG:

```bash
python -m minaret.cli kg build --out runs/kg && python -m minaret.cli kg combine --kg-dir runs/kg
python -m minaret.cli rag index --series TQ2005 --index-root runs/rag/index
```

The KG rebuild is isomorphic to `artifacts/kg/` (same triples, blank-node labels aside).

## Run it on your own recordings

```bash
# 1. V0 + V1
python -m minaret.cli transcribe https://example.org/lecture.mp3 --series-id MySeries --recording-id L01
# 2. E1 + V2 (needs the Quran and Dua corpora, quran.csv / duas.csv)
python -m minaret.cli validate-entities runs/recordings/MySeries/L01
# 3. review v2.json/e1.json (e.g. in the reviewer panel), or hand your own reviewed files back
python -m minaret.cli ingest-reviewed runs/recordings/MySeries/L01 --v3 reviewed_v3.json --e2 reviewed_e2.json
# 4. downstream: write artifacts/kg/series/MySeries.json in the same shape as the shipped ones
python -m minaret.cli kg build --series MySeries --recordings-root runs/recordings
python -m minaret.cli rag index --series MySeries --recordings-root runs/recordings
python -m minaret.cli rag query --scope lecture --recording L01 --question "..."
# 5. evaluate your run exactly like the paper's
python evaluation/run_all.py --artifacts runs
```

## Reviewer panel

```bash
python -m reviewer_panel      # then open http://127.0.0.1:8765
```

The home page walks through one real segment of the released data, stage by stage. The panel
itself (at `/review`) reviews a recording's V2/E1 into V3/E2, replays the released reviews, runs
each pipeline stage, answers RAG and SPARQL questions, and has a Settings tab for models, keys and
pipeline parameters. See [`reviewer_panel/README.md`](reviewer_panel/README.md).

## Tests

```bash
pytest
```

The smoke tests make no network calls and need no LLM server: LLM responses and embeddings are
faked. They also assert the headline paper numbers. Tests needing the corpora skip themselves
when the corpora are absent.

## External ontologies and knowledge graphs

The knowledge graph aligns with, and in part reuses, three external resources. Please cite them
alongside MINARET when you use `artifacts/kg/`:

- **SemanticHadith** (hadith text, `skos:exactMatch` and concept alignment): Kamran, A. B., Abro, B.,
  & Basharat, A. (2023). SemanticHadith: An ontology-driven knowledge graph for the Hadith corpus.
  *Journal of Web Semantics*, 78, 100797. https://doi.org/10.1016/j.websem.2023.100797
- **SemanticTafsir** (verse-level `skos:exactMatch` links; CQ16): Kamran, A. B., Basharat, A., &
  Rehman, M. (2026). SemanticTafsir: Building a cultural heritage ontology and knowledge graph from
  the Quranic exegesis of al-Tabari. *Semantic Web* (accepted).
- **Quran Ontology**, quranontology.com (verse-level `skos:exactMatch` links): Hakkoum, A., &
  Raghay, S. (2015). Ontological approach for semantic modeling and querying the Qur'an. In
  *Proc. International Conference on Islamic Applications in Computer Science and Technology*.

## License

Code: MIT ([`LICENSE`](LICENSE)). The released artifacts contain third-party material (lecture
transcripts, Quran/Hadith/Dua texts and translations) that this license does not cover; see
[`artifacts/NOTICE.md`](artifacts/NOTICE.md).

## Citation

See [`CITATION.cff`](CITATION.cff).
