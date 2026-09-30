# Released artifacts

Everything the MINARET pipeline produced for the paper's 18 recordings (4 series). The evaluation
reads this tree; the pipeline never writes into it. New runs go to `runs/` using the same layout.

```
recordings/<series>/<recording>/
    v0.json v1.json v2.json v3.json   segment lists [{start, end, text, id?}]
    e1.json e2.json                   {ayat, hadith, dua, topics, headings}
    source.json                       audio URL, duration, titles (audio not redistributed)
kg/
    instances/<SERIES>.ttl            per-series ABox
    minaret_combined.ttl              schema + all series (the graph RQ4 queries)
    topic_registry.json               cross-series topic registry after building all series in order
    series/<SERIES>.json              builder input: metadata + every recorded reviewer decision
    series/<SERIES>_topic_proposals.json, _topics.md, _build_log.txt   builder outputs
rag/
    index/<recording>/                chunks.json, chunks.csv, embeddings.npy (bge-m3)
    index/series/<series>/            concatenated series-level index
    traces/<recording>/<ts>.json      the graded lecture-scope traces (3 answer models)
    traces/series_merged/<series>__<model>.json   the graded series-scope traces
    graded_trace_index.json           which trace each review in evaluation/rq5_rag/reviews scored
asr_model_selection/<recording>/<backend>/<model>.json
                                  raw ASR outputs of the V0 model comparison (2 SKD2025 recordings;
                                  OpenAI Whisper and faster-whisper, turbo / large-v3 / medium)
```

Series folders use the recording collection names (`TQ2005`, `HajjJourney2022Eng`, `SKD2025`,
`HEA`); the KG uses the catalogue series codes (`TQ2005`, `HAJJLT22`, `SKD2025`, `HUSN_AKHL`).

## Notes on specific files

- **`e2.json`** is the reviewed entity set in the exact form the KG was built from. Compared with
  the raw reviewer export, ayah ranges (e.g. `1-7`) are expanded to one entry per verse, and topic
  curation from review is applied: split compound topics (`split_from`), topics renamed onto an
  existing cross-series topic (`renamed_from`, kept as `skos:altLabel`), and Urdu names and
  descriptions filled in (`ur_translation_generated` marks LLM-generated Urdu). RQ2 compares
  `e1.json` against this file.
- **`e1.json`** comes from the authors' production extraction run. It has the same top-level keys
  as `e2.json`; its topics use `name`/`description` (as does the package's own extractor), while
  reviewed `e2.json` topics use `name_en`/`name_ur`/`description_*`. The KG builder and RQ2 accept
  both.
- **`SKD2025/SKD_U001_S001_0001` and `_0004` `v3.json`** were resegmented after review, because the
  review tool had split every segment into three near-duplicates (1,529 -> 510 and 1,292 -> 431
  segments; text unchanged). The KG uses the resegmented files. Their RAG indices were built and
  graded *before* the resegmentation, so those two indices ship with the V3 they were built from
  (`rag/index/<recording>/source_v3.json`). Chunk text and timings are identical either way; only
  the RQ5 chunk ids depend on it.
- **`HajjJourney2022Eng/HajjJourney2022Eng-L02` and `-L03` `v3.json`** had four segment
  timestamps corrected after RQ5 was run (a start or end time entered as 2360.32 instead of the
  time from V0: L02 segments 300 and 302, L03 segments 343-344). The KG uses the corrected files.
  L03's RAG index is unaffected; L02's index ships with the V3 it was built from
  (`rag/index/HajjJourney2022Eng-L02/source_v3.json`), since a fresh build regroups its chunks from
  0092 on.
