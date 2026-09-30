# alpha/tau/delta calibration results

Gold set: 320 examples (265 ayah, 55 dua) from `minaret/calibration/gold_set.json`, built by `build_gold_set.py` from the E1-vs-E2 pairs of the 18 released recordings (the pairing RQ2 uses).

**Primary scope: usage == "quotation" only** (182/265 ayah, 52/55 dua) - translation/paraphrase-usage entities are excluded from tuning (structurally unmatchable against an Arabic-only corpus via lexical scoring, not a threshold problem). The same triples' performance against *all* usages (including translation/paraphrase) is shown alongside for transparency, not used to pick the recommendation.

Grid: alpha in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], tau in [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95], delta in [0.0, 0.02, 0.05, 0.08, 0.12, 0.18, 0.25] (770 points).

## Top candidates by F1 on the quotation-only scope

| alpha | tau | delta | correct | wrong | missed | recall | precision | F1 || all-usages recall | all-usages precision |
|---|---|---|---|---|---|---|---|---||---|---|
| 0.7 | 0.5 | 0.02 | 153 | 10 | 66 | 0.668 | 0.939 | 0.781 || 0.487 | 0.939 |
| 0.8 | 0.5 | 0.02 | 152 | 10 | 67 | 0.664 | 0.938 | 0.777 || 0.484 | 0.938 |
| 0.6 | 0.55 | 0.02 | 151 | 10 | 68 | 0.659 | 0.938 | 0.774 || 0.481 | 0.938 |
| 0.6 | 0.5 | 0.02 | 153 | 15 | 61 | 0.668 | 0.911 | 0.771 || 0.487 | 0.911 |
| 0.7 | 0.55 | 0.02 | 149 | 9 | 71 | 0.651 | 0.943 | 0.770 || 0.475 | 0.943 |
| 0.9 | 0.5 | 0.02 | 149 | 9 | 71 | 0.651 | 0.943 | 0.770 || 0.475 | 0.943 |
| 0.7 | 0.5 | 0.05 | 149 | 9 | 71 | 0.651 | 0.943 | 0.770 || 0.475 | 0.943 |
| 0.8 | 0.5 | 0.0 | 154 | 17 | 58 | 0.672 | 0.901 | 0.770 || 0.490 | 0.901 |
| 0.8 | 0.55 | 0.02 | 148 | 8 | 73 | 0.646 | 0.949 | 0.769 || 0.471 | 0.949 |
| 1.0 | 0.5 | 0.02 | 148 | 8 | 73 | 0.646 | 0.949 | 0.769 || 0.471 | 0.949 |
| 0.6 | 0.6 | 0.02 | 147 | 8 | 74 | 0.642 | 0.948 | 0.766 || 0.468 | 0.948 |
| 0.5 | 0.6 | 0.02 | 148 | 10 | 71 | 0.646 | 0.937 | 0.765 || 0.471 | 0.937 |
| 0.5 | 0.55 | 0.02 | 151 | 15 | 63 | 0.659 | 0.910 | 0.765 || 0.481 | 0.910 |
| 0.5 | 0.5 | 0.02 | 155 | 22 | 52 | 0.677 | 0.876 | 0.764 || 0.500 | 0.877 |
| 0.4 | 0.65 | 0.02 | 146 | 8 | 75 | 0.638 | 0.948 | 0.762 || 0.465 | 0.948 |
