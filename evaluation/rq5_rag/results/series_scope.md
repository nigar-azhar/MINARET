# RQ5 evaluation — transcript-based RAG

Total questions: 216 (174 answerable, 42 unanswerable)

## Retrieval

- Recall@10 (initial, pre-rerank): 0.879
- Recall@4 (after rerank): 0.879
- Recall@4 (chunks actually sent to model): 0.879
- MRR (initial): 0.733
- MRR (reranked): 0.819
- Mean precision of sent chunks: 0.363
- Mean recall of sent chunks: 0.895

## Citation / source attribution

- Mean citation precision: 0.79
- Mean citation recall: 0.742
- No-citation rate (all questions): 0.245

## Answer verdicts (human-graded)

Answerable questions:
- correct_grounded: 129
- partially_correct: 22
- incorrect: 19
- hallucinated: 4

Unanswerable questions (refusal test):
- correctly_refused: 39
- incorrectly_answered: 3

## Rerank status

- reranked: 216

## Accuracy by generation model

("correct" = correct_grounded or correctly_refused, out of graded questions)

| Model | Graded | Correct | Accuracy |
|---|---:|---:|---:|
| gemma-4-e4b-it | 72 | 59 | 0.819 |
| meta-llama-3.1-8b-instruct@q6_k | 72 | 54 | 0.75 |
| qwen3.5-9b-mlx | 72 | 55 | 0.764 |

## Accuracy by question language

| Language | Graded | Correct | Accuracy |
|---|---:|---:|---:|
| english | 108 | 83 | 0.769 |
| urdu | 108 | 85 | 0.787 |

## Accuracy by model x language

| Model | Language | Graded | Correct | Accuracy |
|---|---|---:|---:|---:|
| gemma-4-e4b-it | english | 36 | 30 | 0.833 |
| gemma-4-e4b-it | urdu | 36 | 29 | 0.806 |
| meta-llama-3.1-8b-instruct@q6_k | english | 36 | 26 | 0.722 |
| meta-llama-3.1-8b-instruct@q6_k | urdu | 36 | 28 | 0.778 |
| qwen3.5-9b-mlx | english | 36 | 27 | 0.75 |
| qwen3.5-9b-mlx | urdu | 36 | 28 | 0.778 |

## Source review files

- evaluation/rq5_rag/reviews/series_HEA__gemma4e4b.json
- evaluation/rq5_rag/reviews/series_HEA__llama31_8b.json
- evaluation/rq5_rag/reviews/series_HEA__qwen35.json
- evaluation/rq5_rag/reviews/series_HajjJourney2022Eng__gemma4e4b.json
- evaluation/rq5_rag/reviews/series_HajjJourney2022Eng__llama31_8b.json
- evaluation/rq5_rag/reviews/series_HajjJourney2022Eng__qwen35.json
- evaluation/rq5_rag/reviews/series_SKD2025__gemma4e4b.json
- evaluation/rq5_rag/reviews/series_SKD2025__llama31_8b.json
- evaluation/rq5_rag/reviews/series_SKD2025__qwen35.json
- evaluation/rq5_rag/reviews/series_TQ2005__gemma4e4b.json
- evaluation/rq5_rag/reviews/series_TQ2005__llama31_8b.json
- evaluation/rq5_rag/reviews/series_TQ2005__qwen35.json
