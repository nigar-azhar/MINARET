#!/usr/bin/env python3
"""RQ1 residual-error-taxonomy classifier for all 16 recordings' V2-vs-V3 (gold) diffs.

Traceable, rule-based categorization into an extended error taxonomy (see
error_taxonomy.md, in this same directory, for full category descriptions). Reports both
raw diff-entry counts (word-level edit operations) and affected-segment counts
(distinct gold/V2 segments touched by at least one diff of that category) per
category, per recording. Also reports a segment structural (split/merge)
analysis separate from the word-diff classification.

Input: <artifacts>/recordings/<series>/<recording>/{v2,v3}.json; word-level diffs are computed
       here (profile = relaxed_without_diacritics, comparison = v2 vs gold v3).
Output: results/rq1_error_taxonomy.json. error_taxonomy.md describes the categories.

Run: python evaluation/rq1_transcripts/classify_errors.py [--artifacts runs/]
"""
import bisect
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.common import transcript_metrics as ev  # noqa: E402
from evaluation.common.artifacts import arg_parser, load_segments as _load, recordings, write_results  # noqa: E402


# Curated from manual inspection of the highest-frequency diffs. Extend
# and re-run if a recording's formula/name vocabulary differs from what's here.
FORMULA_WORDS = {
    "الله", "اللہ", "اله", "إله", "له", "لله", "وهو", "لا", "الا", "إلا",
    "سبحان", "سبحانه", "وحده", "شريك", "اكبر", "أكبر", "حمد", "للہ", "الحليم",
    "صلى", "صلي", "صل", "عليه", "عليہ", "وسلم", "رسول", "اللهم",
}

# Names of Prophets, companions, and other Islamic historical figures observed
# (or plausible near-misses of observed forms) in this corpus. A substitution
# or deletion touching one of these is flagged as a proper-noun/identity error
# rather than generic wrong/missing text, since confusing one valid name for
# another (or dropping one) is a distinct, higher-stakes failure mode.
PROPER_NOUNS = {
    "محمد", "ابرهيم", "ابراهيم", "علي", "عمر", "عمرو", "عثمان", "عائشہ", "عائشة",
    "بلال", "خالد", "ابوبكر", "ابو", "هريرہ", "ہريرہ", "حرارہ", "حريرہ",
    "ابرهيم", "اسماعيل", "موسى", "موسي", "عيسى", "عيسي", "يوسف", "يعقوب",
}

PUNCT_CHARS = set("،۔؟!.,?:;؛-")


def script_of(ch):
    name = unicodedata.name(ch, "")
    if "ARABIC" in name:
        return "arabic"
    if "DEVANAGARI" in name:
        return "devanagari"
    if ch.isascii() and ch.isalpha():
        return "latin"
    return None


def dominant_script(text):
    scripts = [script_of(c) for c in text if c.isalpha()]
    scripts = [s for s in scripts if s]
    # Deterministic tie-break: a token with as many Latin as non-Latin letters (e.g. "HRكو")
    # counts as the non-Latin script; any other tie goes to the alphabetically first script.
    return max(sorted(set(scripts)), key=lambda sc: (scripts.count(sc), sc != "latin")) if scripts else None


def is_punct_only(text):
    stripped = text.strip()
    return stripped != "" and all(c in PUNCT_CHARS for c in stripped)


def levenshtein(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def classify(entry):
    g, c = entry["gold_text"], entry["candidate_text"]
    t = entry["type"]

    if (g and is_punct_only(g)) or (c and is_punct_only(c)):
        return "punctuation"

    if g in PROPER_NOUNS or c in PROPER_NOUNS:
        return "proper_noun_identity"

    if g in FORMULA_WORDS or c in FORMULA_WORDS:
        return "quranic_hadith_wording"

    if t == "substitution" and g and c:
        sg, sc = dominant_script(g), dominant_script(c)
        if sg and sc and sg != sc:
            if sg == "latin" or sc == "latin":
                return "code_switch_transliteration"
            return "script_conversion"

    if t == "substitution" and g and c:
        dist = levenshtein(g, c)
        if dist <= 2 and max(len(g), len(c)) >= 2:
            return "spelling_typographical"

    return "wrong_missing_text"


def load_segments(path):
    return [s["text"].strip() for s in _load(path)]


def cumulative_offsets(segments, mode="relaxed", strip_diacritics=True):
    """Word-count offset table: offsets[i] = total normalized words before segment i."""
    offsets = [0]
    for text in segments:
        words = ev.normalize(text, strip_diacritics, mode).split()
        offsets.append(offsets[-1] + len(words))
    return offsets


def segment_of(word_index, offsets):
    return bisect.bisect_right(offsets, word_index) - 1


def main():
    args = arg_parser(__doc__).parse_args()
    out = args.out or Path(__file__).resolve().parent / "results"
    grand_diff_counts = {}
    grand_segment_counts = {}
    per_recording = {}

    for series, rid, folder in recordings(args.artifacts):
        v2_path, gold_path = folder / "v2.json", folder / "v3.json"
        entries = ev.word_differences(ev.read_text(gold_path), ev.read_text(v2_path), True, "relaxed")
        v2_segments = load_segments(v2_path)
        gold_segments = load_segments(gold_path)
        v2_offsets = cumulative_offsets(v2_segments)
        gold_offsets = cumulative_offsets(gold_segments)

        diff_counts = {}
        affected_gold_segments = {}
        affected_v2_segments = {}
        for e in entries:
            cat = classify(e)
            diff_counts[cat] = diff_counts.get(cat, 0) + 1
            grand_diff_counts[cat] = grand_diff_counts.get(cat, 0) + 1

            g0, g1 = e["gold_word_range"]
            c0, c1 = e["candidate_word_range"]
            if g1 > g0:
                seg_i = segment_of(g0, gold_offsets)
                affected_gold_segments.setdefault(cat, set()).add(seg_i)
            elif c1 > c0:
                seg_i = segment_of(c0, v2_offsets)
                affected_v2_segments.setdefault(cat, set()).add(seg_i)

        affected_counts = {
            cat: len(affected_gold_segments.get(cat, set()) | affected_v2_segments.get(cat, set()))
            for cat in diff_counts
        }
        for cat, n in affected_counts.items():
            grand_segment_counts.setdefault(cat, 0)

        v2_words = v2_offsets[-1]
        gold_words = gold_offsets[-1]
        seg_ratio = round(len(gold_segments) / len(v2_segments), 2) if v2_segments else None
        word_ratio = round(gold_words / v2_words, 2) if v2_words else None
        if seg_ratio is None:
            structure = "n/a"
        elif abs(seg_ratio - 1.0) <= 0.1:
            structure = "neutral (segment count ~matches)"
        elif seg_ratio > 1.1 and word_ratio and abs(word_ratio - 1.0) <= 0.15:
            structure = "split-dominant (more, smaller gold segments; word count matches V2 closely)"
        elif seg_ratio < 0.9 and word_ratio and abs(word_ratio - 1.0) <= 0.15:
            structure = "merge-dominant (fewer, larger gold segments; word count matches V2 closely)"
        else:
            structure = "structure + content both changed (word count diverges from segment-count ratio)"

        per_recording[rid] = {
            "series": series,
            "total_diffs": len(entries),
            "diff_counts_by_category": diff_counts,
            "affected_segments_by_category": affected_counts,
            "v2_segments": len(v2_segments),
            "gold_segments": len(gold_segments),
            "segment_ratio": seg_ratio,
            "v2_words": v2_words,
            "gold_words": gold_words,
            "word_ratio": word_ratio,
            "structure_classification": structure,
        }

    write_results(out, "rq1_error_taxonomy", {
        "per_recording": per_recording,
        "grand_total_diff_counts": grand_diff_counts,
    })


if __name__ == "__main__":
    main()
