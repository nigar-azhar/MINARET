# RQ5 evaluation — transcript-based RAG

Total questions: 216 (174 answerable, 42 unanswerable)

## Retrieval

- Recall@10 (initial, pre-rerank): 0.914
- Recall@4 (after rerank): 0.914
- Recall@4 (chunks actually sent to model): 0.914
- MRR (initial): 0.849
- MRR (reranked): 0.897
- Mean precision of sent chunks: 0.395
- Mean recall of sent chunks: 0.961

## Citation / source attribution

- Mean citation precision: 0.928
- Mean citation recall: 0.823
- No-citation rate (all questions): 0.227

## Answer verdicts (human-graded)

Answerable questions:
- correct_grounded: 136
- partially_correct: 19
- incorrect: 14
- hallucinated: 5

Unanswerable questions (refusal test):
- correctly_refused: 38
- incorrectly_answered: 4

## Rerank status

- reranked: 216

## Accuracy by generation model

("correct" = correct_grounded or correctly_refused, out of graded questions)

| Model | Graded | Correct | Accuracy |
|---|---:|---:|---:|
| gemma-4-e4b-it | 72 | 61 | 0.847 |
| meta-llama-3.1-8b-instruct@q6_k | 72 | 53 | 0.736 |
| qwen3.5-9b-mlx | 72 | 60 | 0.833 |

## Accuracy by question language

| Language | Graded | Correct | Accuracy |
|---|---:|---:|---:|
| english | 108 | 86 | 0.796 |
| urdu | 108 | 88 | 0.815 |

## Accuracy by model x language

| Model | Language | Graded | Correct | Accuracy |
|---|---|---:|---:|---:|
| gemma-4-e4b-it | english | 36 | 31 | 0.861 |
| gemma-4-e4b-it | urdu | 36 | 30 | 0.833 |
| meta-llama-3.1-8b-instruct@q6_k | english | 36 | 25 | 0.694 |
| meta-llama-3.1-8b-instruct@q6_k | urdu | 36 | 28 | 0.778 |
| qwen3.5-9b-mlx | english | 36 | 30 | 0.833 |
| qwen3.5-9b-mlx | urdu | 36 | 30 | 0.833 |

## Source review files

- evaluation/rq5_rag/reviews/HEA-00-1A__gemma4e4b.json
- evaluation/rq5_rag/reviews/HEA-00-1A__llama31_8b.json
- evaluation/rq5_rag/reviews/HEA-00-1A__qwen35.json
- evaluation/rq5_rag/reviews/HEA-01-1A__gemma4e4b.json
- evaluation/rq5_rag/reviews/HEA-01-1A__llama31_8b.json
- evaluation/rq5_rag/reviews/HEA-01-1A__qwen35.json
- evaluation/rq5_rag/reviews/HEA-02-1A__gemma4e4b.json
- evaluation/rq5_rag/reviews/HEA-02-1A__llama31_8b.json
- evaluation/rq5_rag/reviews/HEA-02-1A__qwen35.json
- evaluation/rq5_rag/reviews/HEA-03-1A__gemma4e4b.json
- evaluation/rq5_rag/reviews/HEA-03-1A__llama31_8b.json
- evaluation/rq5_rag/reviews/HEA-03-1A__qwen35.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L01__gemma4e4b.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L01__llama31_8b.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L01__qwen35.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L02__gemma4e4b.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L02__llama31_8b.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L02__qwen35.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L03__gemma4e4b.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L03__llama31_8b.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L03__qwen35.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L04__gemma4e4b.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L04__llama31_8b.json
- evaluation/rq5_rag/reviews/HajjJourney2022Eng-L04__qwen35.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0001__gemma4e4b.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0001__llama31_8b.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0001__qwen35.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0002__gemma4e4b.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0002__llama31_8b.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0002__qwen35.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0003__gemma4e4b.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0003__llama31_8b.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0003__qwen35.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0004__gemma4e4b.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0004__llama31_8b.json
- evaluation/rq5_rag/reviews/SKD_U001_S001_0004__qwen35.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001A__gemma4e4b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001A__llama31_8b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001A__qwen35.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001B__gemma4e4b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001B__llama31_8b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001B__qwen35.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001C__gemma4e4b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001C__llama31_8b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001C__qwen35.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001D__gemma4e4b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001D__llama31_8b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001D__qwen35.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001E__gemma4e4b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001E__llama31_8b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001E__qwen35.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001F__gemma4e4b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001F__llama31_8b.json
- evaluation/rq5_rag/reviews/TQ2005-P01-L001F__qwen35.json
