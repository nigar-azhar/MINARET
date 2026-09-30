# ASR model selection -- recomputed

Diacritics removed. CER/WER in %. Mean = unweighted mean of the two recordings (as in REPORT.md).

| Recording | Backend | Model | CER | WER | Char del. | Word del. | CER (diacritics kept) |
|---|---|---|---:|---:|---:|---:|---:|
| SKD_U001_S001_0001 | faster_whisper | large-v3-turbo | 6.25 | 10.83 | 1,093 | 197 | 8.51 |
| SKD_U001_S001_0001 | openai_whisper | turbo | 6.56 | 11.16 | 1,167 | 211 | 8.73 |
| SKD_U001_S001_0001 | faster_whisper | large-v3 | 9.12 | 13.00 | 2,124 | 426 | 11.74 |
| SKD_U001_S001_0001 | openai_whisper | large-v3 | 9.20 | 13.47 | 2,053 | 419 | 11.54 |
| SKD_U001_S001_0001 | openai_whisper | medium (excluded) | 74.31 | 97.46 | 14,950 | 4,182 | 75.11 |
| SKD_U001_S001_0001 | faster_whisper | medium (excluded) | 76.50 | 96.97 | 18,560 | 4,899 | 77.12 |
| SKD_U001_S001_0002 | faster_whisper | large-v3-turbo | 6.27 | 11.10 | 825 | 147 | 8.51 |
| SKD_U001_S001_0002 | openai_whisper | turbo | 7.49 | 11.97 | 1,198 | 235 | 9.90 |
| SKD_U001_S001_0002 | openai_whisper | large-v3 | 8.81 | 13.47 | 1,517 | 297 | 11.48 |
| SKD_U001_S001_0002 | faster_whisper | large-v3 | 9.49 | 14.09 | 1,031 | 189 | 11.60 |
| SKD_U001_S001_0002 | openai_whisper | medium (excluded) | 74.92 | 95.04 | 16,587 | 4,425 | 75.73 |
| SKD_U001_S001_0002 | faster_whisper | medium (excluded) | 79.22 | 97.18 | 18,246 | 4,828 | 79.94 |

| Backend | Model | Mean CER | Mean WER | Total char del. | Total word del. |
|---|---|---:|---:|---:|---:|
| faster_whisper | large-v3-turbo | 6.26 | 10.96 | 1,918 | 344 |
| openai_whisper | turbo | 7.03 | 11.56 | 2,365 | 446 |
| openai_whisper | large-v3 | 9.01 | 13.47 | 3,570 | 716 |
| faster_whisper | large-v3 | 9.30 | 13.54 | 3,155 | 615 |
