# Data notice

The MIT license in the repository root covers the code only. The files under `artifacts/` mix
the authors' own contributions with third-party material, and the two carry different rights.

## Authors' contributions

These are the entity annotations (`e1.json`, `e2.json`), the knowledge-graph structure and
alignments (`kg/`), the per-series review decisions (`kg/series/*.json`), the RAG gold questions,
the graded reviews and the traces.

> **TODO (authors): confirm before release.** Intended license: CC BY 4.0
> (https://creativecommons.org/licenses/by/4.0/).

## Third-party material, not relicensed here

| Material | Where it appears | Rights holder |
|---|---|---|
| Lecture content: transcripts `v0`-`v3`, RAG chunk text, `TranscriptSegment` text in the KG | `recordings/`, `rag/`, `kg/` | The speakers / publishers of the lectures. Redistribution depends on the industry partner's permission. **TODO (authors): confirm.** |
| Audio | Not included; `source.json` links to the publisher's URL | Publisher |
| Quran translations (`translationEn`, `translationUr` on `QuranVerse`) | `kg/` | Their respective translators and publishers |
| Dua translations and transliterations | `kg/` | Source of `duas.csv` |
| Series / speaker / recording metadata | `kg/series/*.json`, `recordings/*/source.json` | Publisher's public catalogue |

## Linked knowledge graphs and ontologies

The KG reuses or links to three external resources. Please cite them when you use `kg/`:

| Resource | How the release uses it | Status | Cite |
|---|---|---|---|
| **SemanticHadith** ontology and KG | Hadith text and translations copied onto `minaret:Hadith` nodes; `skos:exactMatch` to `hadith:` individuals; `skos:closeMatch` from topics to its concepts | The authors' own prior work | Kamran, Abro & Basharat (2023), *SemanticHadith: An Ontology-Driven Knowledge Graph for the Hadith Corpus*, Journal of Web Semantics 78, 100797. doi:10.1016/j.websem.2023.100797 |
| **SemanticTafsir** ontology and KG | `skos:exactMatch` from every `QuranVerse` to `tafsir:V{surah}_{ayah}` (links only, no content copied); CQ16 queries it externally | A co-author's work; reuse confirmed | Kamran, Basharat & Rehman (2026), *SemanticTafsir: Building a Cultural Heritage Ontology and Knowledge Graph from the Quranic Exegesis of al-Tabari*, Semantic Web (accepted) |
| **Quran Ontology** (quranontology.com) | `skos:exactMatch` from every `QuranVerse` to `qur:quran{surah}-{ayah}` (links only, no content copied) | Third-party | Hakkoum & Raghay (2015), *Ontological Approach for Semantic Modeling and Querying the Qur'an*, Proc. International Conference on Islamic Applications in Computer Science and Technology |

Anyone reusing this material must follow each rights holder's terms. If you are a rights holder
and want something removed, please contact the authors.
