"""Deterministic transcript metrics: CER/WER under six normalization profiles, word-level diffs.

Carried over unchanged (apart from file handling) from the evaluation used for the paper's RQ1:
unit-cost Levenshtein via rapidfuzz, NFC, whitespace tokenization, Arabic combining marks removed
only in the *_without_diacritics profiles. The paper reports `without_diacritics`; the residual
error taxonomy uses `relaxed_without_diacritics`. Rates are fractions, not percentages.
"""
import html
import json
import re
import unicodedata

# Third element is the normalization mode: None (strict), "equivalent" (documented
# letterform policy), or "relaxed" (experimental — hamza/alef-maqsura/heh unification
# plus glued-punctuation detachment; see RELAXED_RULES and PUNCT_DETACH below).
PROFILES = [("with_diacritics", False, None), ("without_diacritics", True, None),
            ("equivalent_with_diacritics", False, "equivalent"), ("equivalent_without_diacritics", True, "equivalent"),
            ("relaxed_with_diacritics", False, "relaxed"), ("relaxed_without_diacritics", True, "relaxed")]
EQUIVALENCE_RULES = {"ی": "ي", "ک": "ك", "ٱ": "ا", "ـ": ""}
# Experimental, not the documented policy (README says hamza-bearing alefs and alef
# maqsura "remain distinct"). Adds: alef-maqsura -> yeh (unifies with the existing
# choti-ye rule), hamza-carrier unification (informal Urdu typing regularly drops
# hamza: "اما" for "أما"), and Urdu heh goal -> Arabic heh (same Urdu-glyph-variant
# category as the existing choti-ye/kaf rules, just missed originally).
RELAXED_RULES = {**EQUIVALENCE_RULES, "ى": "ي", "أ": "ا", "إ": "ا", "ء": "", "ؤ": "و", "ئ": "ي", "ہ": "ه"}
RULESETS = {"equivalent": EQUIVALENCE_RULES, "relaxed": RELAXED_RULES}
# Sentence punctuation glued directly to a word (no space) is tokenized as part of
# that word, so "ہے" and "ہے۔" count as a full substitution instead of a word match
# plus a punctuation insertion/deletion. Detach only in the relaxed profile.
PUNCT_DETACH = re.compile(r"(?<=\S)([۔،؟!.,?])")


def equivalent_characters(text, rules=EQUIVALENCE_RULES):
    counts, result = {}, []
    for char in unicodedata.normalize("NFC", text):
        code = ord(char)
        replacement = unicodedata.normalize("NFKC", char) if (
            0xFB50 <= code <= 0xFDFF or 0xFE70 <= code <= 0xFEFC) else char
        if replacement != char:
            key = f"presentation_form:{char}→{replacement}"
            counts[key] = counts.get(key, 0) + 1
        for c in replacement:
            mapped = rules.get(c, c)
            if mapped != c:
                key = f"{c}→{mapped or '[removed]'}"
                counts[key] = counts.get(key, 0) + 1
            result.append(mapped)
    return unicodedata.normalize("NFC", "".join(result)), counts


def equivalence_audit(gold, candidates):
    return {"policy_version": "equivalent-characters-v1", "rules": EQUIVALENCE_RULES,
            "relaxed_policy_version": "relaxed-v1 (experimental)", "relaxed_rules": RELAXED_RULES,
            "presentation_forms": "Targeted NFKC in Arabic Presentation Forms A/B only",
            "reference_mapping_counts": equivalent_characters(gold)[1],
            "candidate_mapping_counts": {v: equivalent_characters(t)[1] for v,t in candidates.items()},
            "note": "Counts are mapping applications, not errors forgiven; strict profiles unchanged."}


def read_text(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        if "segments" in data:
            data = data["segments"]
        elif isinstance(data.get("text"), str):
            return data["text"]
    if not isinstance(data, list) or not all(isinstance(x, dict) and isinstance(x.get("text"), str) for x in data):
        raise ValueError(f"{path}: expected segment list, object with segments, or object with text")
    return " ".join(x["text"].strip() for x in data)


def normalize(text, strip_diacritics, mode=None):
    text = unicodedata.normalize("NFC", text)
    if mode:
        text = equivalent_characters(text, RULESETS[mode])[0]
    if mode == "relaxed":
        text = PUNCT_DETACH.sub(r" \1", text)
    if strip_diacritics:
        # Remove Arabic-script combining marks only, not letters such as آ/أ.
        text = "".join(c for c in text if not (
            unicodedata.category(c).startswith("M") and
            "ARABIC" in unicodedata.name(c, "")))
    return re.sub(r"\s+", " ", text).strip()


def measure(reference, hypothesis):
    from rapidfuzz.distance import Levenshtein
    counts = {"substitutions": 0, "deletions": 0, "insertions": 0}
    names = {"replace": "substitutions", "delete": "deletions", "insert": "insertions"}
    for operation in Levenshtein.editops(reference, hypothesis):
        counts[names[operation.tag]] += 1
    n = len(reference)
    return {"reference_units": n, "hypothesis_units": len(hypothesis), **counts,
            "error_rate": sum(counts.values()) / n if n else None,
            **{name + "_rate": value / n if n else None for name, value in counts.items()}}


def compare(gold, hypothesis):
    result = {}
    for label, strip, mode in PROFILES:
        reference, candidate = normalize(gold, strip, mode), normalize(hypothesis, strip, mode)
        if not reference:
            raise ValueError(f"Gold is empty after normalization: {label}")
        result[label] = {"cer": measure(reference, candidate),
                         "wer": measure(reference.split(), candidate.split())}
    return result


def word_differences(gold, candidate, strip_diacritics, mode=None):
    """One record per WER edit, using the same alignment as the metrics."""
    from rapidfuzz.distance import Levenshtein
    reference = normalize(gold, strip_diacritics, mode).split()
    hypothesis = normalize(candidate, strip_diacritics, mode).split()
    differences = []
    for op in Levenshtein.editops(reference, hypothesis):
        i, j = op.src_pos, op.dest_pos
        r_end = i + (op.tag != "insert")
        h_end = j + (op.tag != "delete")
        differences.append({
            "type": {"replace": "substitution", "delete": "deletion", "insert": "insertion"}[op.tag],
            "gold_word_range": [i, r_end], "candidate_word_range": [j, h_end],
            "gold_text": " ".join(reference[i:r_end]),
            "candidate_text": " ".join(hypothesis[j:h_end]),
            "gold_before": " ".join(reference[max(0, i-5):i]),
            "gold_after": " ".join(reference[r_end:r_end+5]),
            "candidate_before": " ".join(hypothesis[max(0, j-5):j]),
            "candidate_after": " ".join(hypothesis[h_end:h_end+5])})
    return differences


def difference_html(data):
    def context(edit, side):
        before, changed, after = (html.escape(edit[side + suffix]) for suffix in ("_before", "_text", "_after"))
        return f'<span dir="auto">{before} <mark>{changed or "∅"}</mark> {after}</span>'
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Word differences</title>',
             '<style>body{font-family:system-ui;margin:2em}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.7em}mark{background:#ffe49a}td{vertical-align:top}</style>',
             '<h1>Word differences against provisional V3 gold</h1>',
             '<p>Each row is one WER edit. Highlighted ∅ means no word on that side. Positions are zero-based normalized word indices, not timestamps. Diacritic-stripped profiles display normalized text. Alignment can be ambiguous.</p>']
    for version, profiles in data.items():
        for profile, edits in profiles.items():
            parts.append(f'<h2>{html.escape(version)} — {html.escape(profile)} ({len(edits)} edits)</h2>')
            parts.append('<table><tr><th>Error</th><th>Gold position</th><th>Gold + context</th><th>Candidate position</th><th>Candidate + context</th></tr>')
            for edit in edits:
                parts.append(f'<tr><td>{edit["type"]}</td><td>{edit["gold_word_range"]}</td><td>{context(edit,"gold")}</td><td>{edit["candidate_word_range"]}</td><td>{context(edit,"candidate")}</td></tr>')
            parts.append('</table>')
    return '\n'.join(parts) + '</html>'
