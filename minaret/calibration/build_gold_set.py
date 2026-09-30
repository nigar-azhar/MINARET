"""Builds a gold calibration set for corpus_validate.py's alpha/tau/delta from the E1-vs-E2
entity pairs of the 18 released recordings (artifacts/recordings/*/*/e1.json, e2.json), matched
with the same identity keys RQ2 uses (evaluation/rq2_entities/compute.py, key_for).

The query is E1's own text: the quoted span the extraction step proposed, before any corpus
grounding (plain-keyboard Arabic, not the Uthmani corpus form or the reviewed Indo-Pak form). Whole
V1 segments are not used as queries, because segment boundaries do not line up with entity spans.

Gold label, per E1 ayah/dua item (key = (surah, ayah, start) or (reference, start), start rounded
to 0.1s):
  - "accept"           - the same key is in E2: the reviewer confirmed this reference.
  - "accept_different" - no exact match, but E2 has a different surah/ayah (or dua reference) at
                          the same start: the reviewer corrected the reference. The gold target is
                          E2's key.
  - "reject"           - no E2 item at that start: the reviewer discarded the candidate (a
                          hallucinated quotation, or a real one dropped rather than corrected; the
                          two cannot be told apart from E1/E2 alone).

Excluded: ayat whose surah_number/ayah_number is a multi-verse range ("25-28", "1-7", ...), since
the corpus has one row per verse and such a quotation has no single row to match.

Run: python -m minaret.calibration.build_gold_set
Writes: minaret/calibration/gold_set.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from evaluation.common.artifacts import load_json, recordings  # noqa: E402
from evaluation.rq2_entities.compute import key_for  # noqa: E402
OUT_PATH = Path(__file__).resolve().parent / "gold_set.json"

_RANGE_RE = re.compile(r"^\d+$")


def _pairs():
    """recording_id -> (e1.json, e2.json) for every released recording, in paper order."""
    return {rec_id: (d / "e1.json", d / "e2.json") for _series, rec_id, d in recordings(ROOT / "artifacts")}


def _ayah_key(surah: str, ayah: str) -> str:
    return f"CH{int(surah):03d}_V{int(ayah):03d}"


def build() -> list[dict]:
    gold: list[dict] = []
    skipped_ranges = 0
    ambiguous_corrections = 0

    for recording_id, (e1_path, e2_path) in _pairs().items():
        e1 = load_json(e1_path)
        e2 = load_json(e2_path)

        for etype, gold_type in (("ayat", "ayah"), ("dua", "dua")):
            e1_items = e1.get(etype, [])
            e2_items = e2.get(etype, [])

            e2_by_full_key = {}
            e2_by_start = {}
            for it in e2_items:
                full_key = key_for(it, etype)
                e2_by_full_key[full_key] = it
                e2_by_start.setdefault(full_key[-1], []).append((full_key, it))

            for it in e1_items:
                text = (it.get("text") or "").strip()
                if not text:
                    continue

                if etype == "ayat":
                    surah, ayah = str(it.get("surah_number")), str(it.get("ayah_number"))
                    if not (_RANGE_RE.match(surah) and _RANGE_RE.match(ayah)):
                        skipped_ranges += 1
                        continue
                    proposed_key = _ayah_key(surah, ayah)
                else:
                    proposed_key = str(it.get("reference"))
                    if not proposed_key or proposed_key == "None":
                        continue

                full_key = key_for(it, etype)
                start = full_key[-1]

                entry = {
                    "recording_id": recording_id,
                    "type": gold_type,
                    "query_text": text,
                    "e1_proposed_key": proposed_key,
                    "start": start,
                    "usage": it.get("usage"),
                }

                if full_key in e2_by_full_key:
                    entry["gold_label"] = "accept"
                    entry["gold_key"] = proposed_key
                else:
                    same_start = [(k, v) for k, v in e2_by_start.get(start, []) if k != full_key]
                    if same_start:
                        if len(same_start) > 1:
                            ambiguous_corrections += 1
                        alt_key, alt_item = same_start[0]
                        if gold_type == "ayah":
                            alt_surah, alt_ayah = alt_key[0], alt_key[1]
                            if not (_RANGE_RE.match(alt_surah) and _RANGE_RE.match(alt_ayah)):
                                skipped_ranges += 1
                                continue
                            gold_key = _ayah_key(alt_surah, alt_ayah)
                        else:
                            gold_key = alt_key[0]
                        entry["gold_label"] = "accept_different"
                        entry["gold_key"] = gold_key
                    else:
                        entry["gold_label"] = "reject"
                        entry["gold_key"] = None

                gold.append(entry)

    print(f"Built {len(gold)} gold examples "
          f"({sum(1 for g in gold if g['type']=='ayah')} ayah, {sum(1 for g in gold if g['type']=='dua')} dua). "
          f"Skipped {skipped_ranges} multi-verse-range items. "
          f"{ambiguous_corrections} ambiguous same-start corrections (first alt used).")
    label_counts = {}
    for g in gold:
        label_counts[g["gold_label"]] = label_counts.get(g["gold_label"], 0) + 1
    print("Label distribution:", label_counts)
    return gold


def main() -> None:
    gold = build()
    OUT_PATH.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
