# Gold test questions for RQ5

One file per lecture (or per series, for `--scope series` evaluation), named
`<recording_id>.json` or `<series>.json`. A list of:

```json
[
  {
    "question_id": "Q1",
    "question": "What does the lecturer say the meaning of Ar-Rahman is?",
    "answerable": true,
    "gold_chunk_ids": ["SKD_U001_S001_0001_chunk_0003"]
  },
  {
    "question_id": "Q2",
    "question": "What did the lecturer say about the Battle of Badr?",
    "answerable": false,
    "gold_chunk_ids": []
  }
]
```

## How to pick `gold_chunk_ids`

Open `artifacts/rag/index/<recording_id>/chunks.json` (or the series index at
`artifacts/rag/index/series/<series>/chunks.json`) and read the chunk text
directly — that file has every chunk's id, constituent V3 segment ids,
start/end timestamps, and text, exactly so this can be done without running
anything. Pick every chunk that genuinely supports the answer (usually one,
sometimes two adjacent ones if the answer spans a chunk boundary).

## Include deliberately unanswerable questions

Set `"answerable": false` and `"gold_chunk_ids": []` for questions this
specific lecture does not cover. These test whether the system correctly
refuses ("This lecture does not provide enough information...") instead of
guessing or pulling in irrelevant content — this is a named risk in the
project's own related-work review (long-context/meeting QA must "account for
questions that have no answer in the source material"). Aim for at least a
few unanswerable questions per lecture alongside the answerable ones, not
just a token one.

## Question mix worth covering per lecture

- A direct factual question (what did the lecturer say about X)
- A question about a specific Qur'an verse or du'a mentioned, if any
- A question requiring the explanatory/tafsir content, not just a quoted verse
- At least one deliberately unanswerable question

## Then run

```bash
python -m minaret.cli rag query --scope lecture --recording <id> \
  --questions-file evaluation/rq5_rag/questions/<id>.json
python evaluation/rq5_rag/evaluate_rag.py score \
  --gold evaluation/rq5_rag/questions/<id>.json \
  --trace runs/rag/traces/<id>/<timestamp>.json \
  --out runs/rag/reviews/<id>.json
```

Then fill in `answer_verdict` in the `--out` file by reading each
`generated_answer` against the lecture, and run
`evaluate_rag.py aggregate` (see `evaluation/README.md`).
