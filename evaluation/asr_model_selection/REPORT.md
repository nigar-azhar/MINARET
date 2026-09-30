# SKD2025 Two-Recording ASR Pilot: Model Selection

## Decision

For the next stage of the SKD2025 pilot, select **faster-whisper `large-v3-turbo` with `int8` compute** as the primary transcription model.

This is a provisional decision based on two reviewed recordings. The selected model achieved the lowest CER and WER on both recordings, both with Arabic diacritics preserved and with diacritics removed. It also produced fewer global character and word deletions than OpenAI Whisper Turbo and both full `large-v3` implementations.

In this report, “faster-whisper” refers to the ASR implementation. It is not FastAPI, the Python web framework.

## Scope and method

Recordings evaluated:

- `SKD_U001_S001_0001`
- `SKD_U001_S001_0002`

For each recording, ASR segment text was concatenated in chronological order and compared with the final reviewed `v3` transcript. Two otherwise identical normalization profiles were used:

1. **Diacritics preserved:** Unicode and whitespace normalization were applied while Arabic diacritics were retained.
2. **Diacritics removed:** the same normalization was applied, then Arabic vowel and Quranic annotation marks were removed from both reference and hypothesis.

CER is the primary mixed-script accuracy metric. WER uses whitespace-delimited tokens and is treated as a secondary measure. Global character and word deletions are included as currently available proxies for omitted content. They do not yet constitute counts of completely missed segments or missed Quran ayat.

## Results with diacritics removed

Lower values are better.

### Recording 1 — `SKD_U001_S001_0001`

| Backend | Model | CER | WER | Character deletions | Word deletions |
|---|---|---:|---:|---:|---:|
| faster-whisper | large-v3-turbo | **6.25%** | **10.83%** | **1,093** | **197** |
| OpenAI Whisper | turbo | 6.56% | 11.16% | 1,167 | 211 |
| faster-whisper | large-v3 | 9.12% | 13.00% | 2,124 | 426 |
| OpenAI Whisper | large-v3 | 9.20% | 13.47% | 2,053 | 419 |

### Recording 2 — `SKD_U001_S001_0002`

| Backend | Model | CER | WER | Character deletions | Word deletions |
|---|---|---:|---:|---:|---:|
| faster-whisper | large-v3-turbo | **6.27%** | **11.10%** | **825** | **147** |
| OpenAI Whisper | turbo | 7.49% | 11.97% | 1,198 | 235 |
| OpenAI Whisper | large-v3 | 8.81% | 13.47% | 1,517 | 297 |
| faster-whisper | large-v3 | 9.49% | 14.09% | 1,031 | 189 |

### Two-recording aggregate

The CER and WER values below are unweighted means of the two lecture-level rates. Deletion counts are totals across the two recordings.

| Backend | Model | Mean CER | Mean WER | Total character deletions | Total word deletions |
|---|---|---:|---:|---:|---:|
| faster-whisper | large-v3-turbo | **6.26%** | **10.96%** | **1,918** | **344** |
| OpenAI Whisper | turbo | 7.03% | 11.56% | 2,365 | 446 |
| OpenAI Whisper | large-v3 | 9.01% | 13.47% | 3,570 | 716 |
| faster-whisper | large-v3 | 9.30% | 13.54% | 3,155 | 615 |

## Results with diacritics preserved

| Recording | Backend | Model | CER | WER |
|---|---|---|---:|---:|
| Recording 1 | faster-whisper | large-v3-turbo | **8.51%** | **11.83%** |
| Recording 1 | OpenAI Whisper | turbo | 8.73% | 12.10% |
| Recording 1 | OpenAI Whisper | large-v3 | 11.54% | 14.54% |
| Recording 1 | faster-whisper | large-v3 | 11.74% | 13.84% |
| Recording 2 | faster-whisper | large-v3-turbo | **8.51%** | **12.43%** |
| Recording 2 | OpenAI Whisper | turbo | 9.90% | 13.31% |
| Recording 2 | OpenAI Whisper | large-v3 | 11.48% | 14.73% |
| Recording 2 | faster-whisper | large-v3 | 11.60% | 14.96% |

The model ranking is therefore not an artifact of removing diacritics: faster-whisper Turbo remained best under both profiles on both recordings.

## Runtime observations

The cleanest available Turbo observations for Recording 2 were:

| Backend | Model | Elapsed time | Audio duration | Approximate real-time factor |
|---|---|---:|---:|---:|
| OpenAI Whisper | turbo | 15m 22s | 45m 25s | 0.34 |
| faster-whisper | large-v3-turbo | 17m 52s | 45m 25s | 0.39 |

Both models completed faster than real time. OpenAI Whisper Turbo was approximately 2 minutes 30 seconds faster in this observation, while faster-whisper Turbo was more accurate and had fewer deletions.

These timings are not a controlled benchmark. Several local model runs overlapped and earlier runs may have included model download or initialization time. Runtime is therefore supporting evidence only and is not the primary basis for selection.

## Why faster-whisper `large-v3-turbo` was selected

1. **Best accuracy on both recordings.** It had the lowest diacritic-insensitive CER and WER in both cases.
2. **The result was stable across normalization profiles.** It also ranked first when diacritics were preserved.
3. **Fewer global deletions.** Across the two recordings it had 344 word deletions, compared with 446 for OpenAI Whisper Turbo, 615 for faster-whisper `large-v3`, and 716 for OpenAI Whisper `large-v3`.
4. **Better than full `large-v3` in this pilot.** Both Turbo implementations outperformed their full `large-v3` comparisons, and faster-whisper Turbo had the strongest overall result.
5. **Operationally practical.** On Recording 2 it transcribed approximately 45 minutes of audio in under 18 minutes on the available machine.
6. **The speed tradeoff against OpenAI Turbo was modest.** The observed difference was about 2.5 minutes, while faster-whisper Turbo improved both accuracy and deletion counts.
7. **Local and cost-free transcription.** It does not require a paid transcription API and preserves segment- and word-level timestamps.

Relative to OpenAI Whisper Turbo, faster-whisper Turbo improved the two-recording mean diacritic-insensitive CER by approximately **0.76 percentage points** and WER by approximately **0.60 percentage points**. It also produced approximately **23% fewer word deletions** and **19% fewer character deletions** in the global alignments.

## Exclusions and limitations

- The medium-model outputs were excluded from model selection because their hypothesis word counts were far below the gold transcripts, indicating incomplete outputs rather than ordinary recognition differences.
- Only two recordings have been evaluated. The result supports a pilot choice, not a statistically general conclusion.
- Global deletion counts indicate omitted reference content but do not identify complete missed segments.
- Quran-specific omission has not yet been measured because reviewed Quran entities have not been aligned to gold segment IDs or timestamp intervals in this report.
- A hypothesis can contain text in the correct interval while still omitting or replacing the actual ayah. Dedicated timestamp-based missed-segment and Quran-grounding metrics remain necessary.
- Runtime measurements included model loading and were affected by overlapping local runs. A cached, sequential benchmark is needed before making a formal efficiency claim.

## Recommended next step

Use faster-whisper `large-v3-turbo` as the primary ASR model for the next pilot recordings. Retain OpenAI Whisper Turbo as the comparison model. Continue calculating both diacritic-preserved and diacritic-removed CER/WER, and add timestamp-aligned missed-segment and Quran-specific omission measures when the required grounded review data is available.
