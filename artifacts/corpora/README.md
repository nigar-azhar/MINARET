# Third-party corpora (not redistributed)

These files are used by the pipeline but belong to their publishers, so they are not part of this
repository. Place them here, or point `corpora.*` in `minaret.yaml` at them. Everything in this
folder except this README is gitignored.

| `minaret.yaml` key | File | Used by | Expected columns / content |
|---|---|---|---|
| `corpora.quran_csv` | `quran.csv` | KG canonical verses | `sura, aya, juz, text, text_indopak, textc, en_sahih, ur_farhat` |
| `corpora.duas_csv` | `duas.csv` | KG canonical Duas | `duaId, duaArabic, dua_en, dua_ur, transliteration, duaType_en, duaType_ur` |
| `corpora.quran_db` | `quran.csv` (default) or a SQLite DB with a `quran` table (`sura, aya, text`) | corpus validation (E1/V2) | Uthmani verse text in `text` |
| `corpora.dua_db` | `duas.csv` (default) or a SQLite DB with a `dua` table (`dua_id, arabic, title_en`) | corpus validation (E1/V2) | Dua Arabic in `duaArabic` |
| `corpora.semantic_hadith_dump` | `SemanticHadithKG.rdf.zip` (contains `SemanticHadithKGV2.ttl`) | KG hadith text + alignment | SemanticHadith KG V2 (Kamran, Butt & Basharat, 2026, doi:10.1177/22104968261431425; original: Kamran, Abro & Basharat, 2023, doi:10.1016/j.websem.2023.100797) |

Only the KG build and corpus validation need these. Evaluation (`evaluation/run_all.py`) and the
RAG stage do not. `corpora.cache_dir` holds a small JSON cache of the hadith blocks extracted from
the SemanticHadith dump.
