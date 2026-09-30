# RQ1 — residual error taxonomy, all 18 recordings (V2 vs V3)

Answers the counting part of RQ1's residual-error question ("what types of
transcript errors remain after automated processing") —
V2 is the automated-pipeline output before human review, V3 is the reviewer's
final golden transcript, so every diff below is something the reviewer had to
catch and fix that the automated stages (correction + canonical substitution)
did not.

Equivalence/letterform noise (hamza-carrier unification, alef-maqsura/yeh
unification, Urdu-heh/Arabic-heh unification, glued-punctuation detachment) is
already excluded before classification — everything counted below is a real
remaining difference, not a scoring artifact.

## What "wrong/missing text" counts — and what it doesn't

**Every count in this document is at the word level, not the character
level.** A "diff" is one edit operation (one substitution, one deletion, or
one insertion) from the word-level alignment between V2 and gold, the same
alignment WER is computed from — not a character-level CER edit. `wrong_missing_text`
specifically is the catch-all bucket for word-level deletions, insertions, and
substitutions that don't match any more specific category below (not a close
spelling variant, not punctuation, not a known formula/name word, not a
cross-script pair). It is best read as "the reviewer had to add, remove, or
substitute this word, for a reason not captured by the other categories" —
it does not distinguish *why* (grammar, missing audio content, wrong ASR guess,
LLM hallucination, etc.) without reading the actual segment, which is why the
discussion below gives concrete examples per recording rather than treating the count alone as
self-explanatory.

Two units are reported per category:

- **Diff count** — raw number of edit operations in that category. A single
  bad word that gets deleted-then-reinserted-differently counts as more than
  one diff. This is the finer-grained number.
- **Affected segments** — number of *distinct* gold (or, for pure insertions
  with no gold position, V2) segments containing at least one diff of that
  category. It shows how much of the *transcript*, not how much raw edit
  volume, a category touches. A segment with 20 small
  punctuation fixes counts once here, not 20 times.

## Category descriptions (extended taxonomy — 7 categories + structural)

| Category | What it is | Detection rule |
|---|---|---|
| **`punctuation`** | A diff where either side is punctuation-only (`، ۔ ؟ ! . , ? : ; -`) | Deterministic string check |
| **`spelling_typographical`** | A substitution where gold and candidate are close in edit distance (≤2 characters) in the same script | Levenshtein distance ≤ 2, same dominant script |
| **`proper_noun_identity`** *(new)* | A diff touching a known name of a Prophet, companion, or historical Islamic figure — misspelling *or* substitution with a different valid name *or* outright deletion | Curated name lexicon (see script) — flags before the spelling-distance check, so a name that happens to be edit-distance-1 from a *different* name (e.g. `عمرو`→`عمر`, ʿAmr→ʿUmar) is correctly separated from generic spelling noise |
| **`script_conversion`** *(new, split from the old "transliteration_script")* | The same word rendered in two different non-Latin scripts (e.g. Devanagari vs. Perso-Arabic Urdu for the same Hindi/Urdu word) | Cross-script substitution, neither side Latin |
| **`code_switch_transliteration`** *(new, split from the old "transliteration_script")* | An English (or other Latin-script) loanword transliterated into Arabic/Urdu script instead of kept in Latin, or vice versa | Cross-script substitution, one side Latin |
| **`quranic_hadith_wording`** | A diff touching a word from a curated list of common Quranic/tasbih/durood/dhikr formula vocabulary | Curated word list (see script) |
| **`wrong_missing_text`** | Everything else — real content deletions, insertions, and substitutions not covered above | Default bucket |

**Known heuristic limitation, disclosed rather than hidden:** the
edit-distance-≤2 rule still occasionally misclassifies a genuine wrong-word
error as a spelling variant when the two words are one letter apart but mean
different things and aren't in the proper-noun list — e.g. `دوا` (medicine) vs
`دعا` (supplication), edit-distance 1. `spelling_typographical` should be read
as an upper bound, `wrong_missing_text` as a lower bound, on true content
errors. The proper-noun and formula-word lists are hand-curated from manual
inspection of this corpus, not exhaustive lexicons — extend
`PROPER_NOUNS`/`FORMULA_WORDS` in the script and re-run if a recording's
vocabulary isn't covered.

## Per-recording counts (diff count / affected segments)

| Recording | Total diffs | Punctuation | Spelling/typo | Proper noun/identity | Script conversion | Code-switch translit. | Quranic/Hadith wording | Wrong/missing text |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TQ2005-L001A | 23 | 4 / 4 | 2 / 2 | — | — | — | — | 17 / 9 |
| TQ2005-L001B | 20 | 2 / 1 | — | — | — | — | — | 18 / 2 |
| TQ2005-L001C | 0 | — | — | — | — | — | — | — |
| TQ2005-L001D | 39 | 5 / 2 | — | — | — | — | — | 34 / 2 |
| TQ2005-L001E | 27 | 6 / 1 | — | — | — | — | 1 / 1 | 20 / 5 |
| TQ2005-L001F | 346 | 167 / 111 | 68 / 40 | — | — | 1 / 1 | 4 / 3 | 106 / 38 |
| Hajj-L01 | 1,428 | 168 / 45 | 6 / 6 | — | — | — | 10 / 3 | 1,244 / 62 |
| Hajj-L02 | 20 | 5 / 1 | — | — | — | — | 3 / 1 | 12 / 1 |
| Hajj-L03 | 883 | 99 / 33 | 3 / 3 | 1 / 1 | — | — | 11 / 8 | 769 / 59 |
| Hajj-L04 | 387 | 13 / 9 | 165 / 95 | 1 / 1 | — | — | 23 / 7 | 185 / 53 |
| SKD_0001 | 674 | 76 / 69 | 166 / 152 | 2 / 2 | — | 55 / 47 | 13 / 12 | 362 / 187 |
| SKD_0002 | 576 | 37 / 33 | 200 / 167 | 9 / 7 | — | 94 / 74 | 22 / 21 | 214 / 87 |
| SKD_0003 | 266 | 50 / 43 | 14 / 14 | — | 185 / 71 | — | 1 / 1 | 16 / 13 |
| SKD_0004 | 909 | 8 / 4 | 230 / 196 | 11 / 11 | — | 12 / 8 | 196 / 72 | 452 / 178 |
| HEA-00-1A | 573 | 70 / 35 | 268 / 151 | 30 / 13 | — | 1 / 1 | 17 / 11 | 187 / 67 |
| HEA-01-1A | 975 | 95 / 25 | 70 / 37 | 15 / 9 | — | — | 53 / 9 | 742 / 32 |
| HEA-02-1A | 177 | 17 / 8 | — | 1 / 1 | — | — | 7 / 3 | 152 / 26 |
| HEA-03-1A | 194 | 27 / 9 | — | 10 / 3 | — | — | 15 / 8 | 142 / 10 |
| **Grand total** | **7,517** | **849** | **1,192** | **80** | **185** | **163** | **376** | **4,672** |

(Grand-total column is diff-count sum only — affected-segment counts don't sum
cleanly across recordings since segment indices aren't comparable across
files.)

## Segment structural analysis (split / merge)

| Recording | V2 segments | Gold segments | Segment ratio | V2 words | Gold words | Word ratio | Classification |
|---|---:|---:|---:|---:|---:|---:|---|
| TQ2005-L001A | 106 | 107 | 1.01 | 3,385 | 3,405 | 1.01 | neutral |
| TQ2005-L001B | 160 | 163 | 1.02 | 5,207 | 5,227 | 1.00 | neutral |
| TQ2005-L001C | 12 | 12 | 1.00 | 188 | 188 | 1.00 | neutral |
| TQ2005-L001D | 78 | 80 | 1.03 | 2,606 | 2,645 | 1.01 | neutral |
| TQ2005-L001E | 131 | 135 | 1.03 | 4,390 | 4,417 | 1.01 | neutral |
| TQ2005-L001F | 221 | 222 | 1.00 | 7,091 | 7,177 | 1.01 | neutral |
| Hajj-L01 | 282 | 332 | 1.18 | 9,480 | 10,861 | 1.15 | **split-dominant** |
| Hajj-L02 | 337 | 338 | 1.00 | 10,192 | 10,212 | 1.00 | neutral |
| Hajj-L03 | 325 | 370 | 1.14 | 10,127 | 10,935 | 1.08 | **split-dominant** |
| Hajj-L04 | 329 | 332 | 1.01 | 10,380 | 10,412 | 1.00 | neutral |
| SKD_0001 | 274 | 510 | **1.86** | 8,184 | 8,269 | 1.01 | **split-dominant** |
| SKD_0002 | 1,441 | 1,426 | 0.99 | 7,347 | 7,496 | 1.02 | neutral |
| SKD_0003 | 243 | 242 | 1.00 | 9,316 | 9,315 | 1.00 | neutral |
| SKD_0004 | 237 | 431 | **1.82** | 6,400 | 6,652 | 1.04 | **split-dominant** |
| HEA-00-1A | 299 | 303 | 1.01 | 8,138 | 8,317 | 1.02 | neutral |
| HEA-01-1A | 168 | 185 | 1.10 | 8,696 | 9,556 | 1.10 | **structure + content both changed** |
| HEA-02-1A | 183 | 189 | 1.03 | 10,453 | 10,593 | 1.01 | neutral |
| HEA-03-1A | 135 | 140 | 1.04 | 7,378 | 7,569 | 1.03 | neutral |

**No recording shows evidence of merge-dominant behavior** (gold ending up
with fewer, larger segments than V2) — every structural change goes the other
direction, gold splitting V2's segments into more, finer units.

**Split-dominant, not deletion, for SKD_0001/0004:** word counts are nearly
identical between V2 and gold (ratio 1.01–1.04) despite the segment count
being roughly 1.8–1.9× higher in gold. This means the reviewer is not adding
large blocks of missing content — they are re-segmenting existing content
into more, shorter segments.

*(In these two recordings the review tool had split each segment into three
near-duplicate sub-segments; the V3 files used here merge each triple back
into one segment.)*

**Hajj-L01/L03 show a milder version of the same pattern** — 14–18% more
segments in gold, word count tracking closely, i.e. lighter re-segmentation.

**HEA-01-1A is the one case where structure and content changed together** —
segment ratio (1.10) and word ratio (1.10) move together but neither is small,
and this recording's `wrong_missing_text` count (742, the highest of all 18)
and affected-segment count (32) are consistent with the genuine multi-sentence
content gap found by manual inspection — some of its structural difference
is real content the automated pipeline dropped, not just re-segmentation.

**HEA-02-1A and HEA-03-1A are both neutral**, same as
HEA-00-1A — confirming HEA-01-1A's combined structure-and-content shift is
specific to that one recording, not a property of the HEA series. Across all
4 HEA recordings, 3 are neutral and only 1 shows real structural drift, the
same pattern as every other series in this set (a mix, not a systematic
issue) rather than HEA being structurally different from TQ2005/Hajj/SKD2025.

**Limitation:** this structural classification is a net comparison (total
segment count vs total word count), not a true per-segment alignment. It
cannot rule out a recording having some segments split *and* others deleted
in roughly offsetting numbers. A full alignment pass (matching each V2 segment
to its corresponding gold segment span by timestamp or content overlap) would
be needed to state split/merge/delete/add counts individually rather than net
— flag if that level of detail is wanted; it's a larger job than this pass.

## Discussion — why TQ2005 outperforms every other series

TQ2005's error rate isn't explained by its recordings simply being shorter.
Normalizing diff count by gold word count (diffs per 100 words) instead of
looking at raw counts:

| Series | Total diffs | Total gold words | Rate per 100 words |
|---|---:|---:|---:|
| **TQ2005** | 455 | 23,059 | **1.97** |
| Hajj | 2,718 | 42,420 | 6.41 |
| SKD2025 | 2,425 | 31,732 | 7.64 |
| HEA | 1,919 | 36,035 | 5.33 |

TQ2005's error *density* is 2.7–3.9× lower than every other series, not just
its total volume — genuinely cleaner content, not a duration effect. HEA's
rate dropped from 8.66 to 5.33 once HEA-02-1A/03-1A were added (both far
cleaner than HEA-00-1A/01-1A) — it's now the second-cleanest series rather
than the noisiest, which changes the ranking but not TQ2005's lead.

Three converging pieces of evidence point at *why*:

1. **Zero identity/script errors.** TQ2005 has 0 `proper_noun_identity`,
   0 `script_conversion`, and only 1 `code_switch_transliteration` diff across
   all 6 recordings (23,059 words) — compare to HEA's 56 proper-noun errors
   across its 4 recordings, SKD_0003's 185 script-conversion diffs in one
   recording, or SKD_0001/0002's 149 combined code-switch diffs. These
   categories are largely genre-driven: proper-noun errors track companion/
   historical-figure narration (Hadith storytelling), script-conversion tracks
   Hindi/Urdu script-choice instability, code-switch tracks incidental English
   vocabulary (medical terms in SKD_0002, travel narrative in Hajj). TQ2005's
   content — Qur'an verse-by-verse recitation, translation, and brief
   explanation — has essentially none of these register elements to begin
   with.

2. **Every TQ2005 recording is structurally "neutral" — zero splitting.** All
   six sit at segment ratio 1.00–1.03 and word ratio 1.00–1.01 (see structural
   table). No other series is clean across the board: Hajj has 2/4 split-
   dominant recordings, SKD2025 has 2/4 (at 5.5×, the most extreme splitting
   in the whole set), HEA has 1/4 with combined structure-and-content drift
   (the other 3 are neutral, same as TQ2005's own pattern).
   Verse-recitation-then-explanation creates natural pause boundaries that
   line up with where an ASR segmenter would already cut — free-flowing
   narrative speech (Hajj's travelogue, HEA's discursive ethics lectures) runs
   on past natural ASR segment boundaries, forcing the reviewer to split
   during review instead.

3. **Recordings are shorter, which compounds rather than solely explains the
   above.** TQ2005 averages ~21 minutes/recording vs. ~46–58 minutes for the
   other three series. Less cumulative audio means less opportunity for ASR
   drift and less content variety per recording to trip up correction — but
   given the 3–4× *density* gap above, length alone is a contributing factor,
   not the primary one.

4. **Tested and refined: it is not literal content repetition across the six
   recordings.** An initial hypothesis was that TQ2005's six recordings — all
   part of one Surah Al-Fatiha lesson, split into parts — succeed because the
   same small set of verses and vocabulary recurs across all six, narrowing
   the space for errors to appear in. This was checked directly by computing
   cross-recording vocabulary overlap (average pairwise Jaccard similarity of
   each series' gold-text word sets) and does **not** hold up:

   | Series | Avg. pairwise vocabulary overlap (Jaccard) |
   |---|---:|
   | **TQ2005** | **0.181 (lowest)** |
   | Hajj | 0.288 |
   | SKD2025 | 0.278 |
   | HEA | 0.297 |

   TQ2005's six recordings share *less* vocabulary with each other than the
   other series' recordings do — the opposite of what literal content
   repetition would predict. The reason: the six recordings' titles are
   **Recap, Introduction, Translation, How to Learn Quran, Word Analysis,
   Tafsir** — six different *pedagogical passes* over the same handful of
   verses, each using register-specific vocabulary (a translation-focused
   session reads differently from a word-analysis session), which is exactly
   why overall lexical overlap is low.

   What *does* recur verbatim is the underlying Qur'anic anchor text itself —
   confirmed by finding the exact ta'awwudh/basmalah opening formula
   (`اَعُوْذُ بِاللّٰهِ مِنَ الشَّیْطَانِ الرَّجِیْمِ، بِسْمِ اللّٰهِ الرَّحْمٰنِ
   الرَّحِیْمِ`) quoted identically across L001C, L001E, and L001F. **This is
   the real mechanism:** Al-Fatiha is one of the shortest, most universally
   memorized and precisely attested surahs in Islam, so the pipeline's
   canonical Quran-text substitution step (V1→V2) has about as easy a
   validation target as exists in the entire corpus — a tiny, unambiguous,
   near-identically-recited text — which directly suppresses
   `quranic_hadith_wording`-category errors specifically. The *surrounding*
   commentary varies lesson-to-lesson in register and vocabulary, but stays
   within one consistent domain (tafsir/translation discourse) that never
   touches Hadith-narration proper nouns, travel narrative, or incidental
   English code-switching — the sources of the other error categories
   elsewhere in the corpus.

**Net read for the paper:** TQ2005's outlier-free performance is not caused by
narrow/repetitive lexical content (that hypothesis was tested and rejected —
its vocabulary overlap is actually the lowest of the four series). It is
better explained by two independent, converging factors: (a) an unusually easy
corpus-grounding target — a short, famous, precisely-attested surah, quoted
near-verbatim each time it recurs, which suppresses the Quranic-wording error
category specifically — and (b) a consistently narrow discourse *register*
(tafsir/translation pedagogy) that structurally excludes the content types
(Hadith-narration proper nouns, travel narrative, code-switched technical
vocabulary) responsible for most residual errors elsewhere, even though the
explanatory vocabulary itself varies considerably pass-to-pass. This is itself
a relevant RQ1 finding: residual error rate is genre- and corpus-grounding-
difficulty-dependent, not simply a function of topical repetition, and a pilot
evaluation skewed toward one genre (or drawing conclusions from it alone)
would over- or under-state the pipeline's general reliability.

## Reproduce

```bash
python evaluation/rq1_transcripts/classify_errors.py
```

Writes the per-recording and pooled counts these tables are built from (word-diff category counts,
affected-segment counts and the segment/word structural numbers) to
`evaluation/rq1_transcripts/results/rq1_error_taxonomy.json`.
