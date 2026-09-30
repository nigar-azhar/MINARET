# Evaluation

Every script reads from an artifact tree (`--artifacts`, default `artifacts/`) and writes to its own
`results/` folder (or `--out`). Nothing here imports anything from `minaret/` except through the
files it produced, so the same scripts can score a new run: `--artifacts runs`.

```bash
python evaluation/run_all.py                  # all RQs
python evaluation/rq2_entities/compute.py     # one RQ
```

| RQ | Script | Input | Computes |
|---|---|---|---|
| RQ1 | `rq1_transcripts/compute.py` | v0-v3 | CER/WER of V0/V1/V2 vs V3 (`without_diacritics`), RER (Eq. 14), changed-segment rate; per recording and pooled by series from total edit counts |
| RQ1 | `rq1_transcripts/classify_errors.py` | v2, v3 | residual V2-vs-V3 error taxonomy (`relaxed_without_diacritics`); categories in `error_taxonomy.md` |
| RQ1 | `rq1_transcripts/export_diffs.py` | v2, v3 (+ v0, v1 with `--word-diffs`) | one CSV per recording listing every V2-vs-V3 edit with its category, segment and timestamps, and context (`results/v2_v3_diffs/`); `--word-diffs` adds full word-level diff JSON/HTML for V0/V1/V2 under every profile (large, gitignored) |
| RQ2 | `rq2_entities/compute.py` | e1, e2 | entity- and occurrence-level P/R/F1, retention/correction/rejection/omission, per recording and pooled |
| RQ3 | `rq3_review_effort/compute.py` | `review_effort.csv` | review hours, RTF, minutes of review per audio hour |
| RQ4 | `rq4_kg/compute.py` | `kg/minaret_combined.ttl` | ontology/KG statistics; the 16 competency questions in `cqs/*.rq` |
| RQ5 | `rq5_rag/compute.py` | `rag/traces`, `questions/`, `reviews/` | re-scores every graded trace and checks it against the stored reviews, then aggregates retrieval, citation and human answer verdicts (lecture and series scope) |
| -- | `asr_model_selection/compute.py` | `asr_model_selection/`, SKD2025 v3 | the ASR comparison behind choosing faster-whisper large-v3-turbo for V0 (4 Whisper variants x 2 recordings); write-up in `asr_model_selection/REPORT.md` |

`common/transcript_metrics.py` is the deterministic CER/WER implementation (rapidfuzz unit-cost
Levenshtein, NFC, whitespace tokens, six normalization profiles).

**RQ5 answer verdicts are human judgments.** `reviews/*.json` hold them, and they are read, never
recomputed. To grade a new run:

```bash
python -m minaret.cli rag query --scope lecture --recording X --questions-file evaluation/rq5_rag/questions/X.json
python evaluation/rq5_rag/evaluate_rag.py score --gold evaluation/rq5_rag/questions/X.json \
    --trace runs/rag/traces/X/<ts>.json --out runs/rag/reviews/X__mymodel.json
# fill in answer_verdict for each question, then:
python evaluation/rq5_rag/evaluate_rag.py aggregate --reviews runs/rag/reviews/*.json --out runs/rag/evaluation.md
```

**CQ16** follows a link into the external SemanticTafsir KG. Step 1 runs by default; pass
`--tafsir-kg SemanticTafsirKG.ttl` to `rq4_kg/compute.py` to run step 2 as well.
