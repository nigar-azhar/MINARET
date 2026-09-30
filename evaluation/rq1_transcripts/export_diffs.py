#!/usr/bin/env python3
"""Per-recording listings of every V2-vs-V3 difference behind RQ1's residual-error taxonomy.

Default output, one CSV per recording (committed with the release):
    results/v2_v3_diffs/<recording>.csv
Each row is one word-level edit (relaxed_without_diacritics profile), with its taxonomy category
(the same classify() as classify_errors.py), where it falls (segment index and timestamps on the
V3 side, or the V2 side for pure insertions), and five words of context either side.

With --word-diffs, also writes the full word-level differences for V0, V1 and V2 against V3 under
every normalization profile, as JSON plus a browsable HTML page per recording:
    results/word_differences/<recording>.{json,html}
These are about 13 MB per recording, so they are generated on demand and gitignored.

    python evaluation/rq1_transcripts/export_diffs.py [--artifacts runs/] [--word-diffs]
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluation.common import transcript_metrics as tm  # noqa: E402
from evaluation.common.artifacts import arg_parser, load_segments, recordings  # noqa: E402
from classify_errors import classify, cumulative_offsets, segment_of  # noqa: E402

FIELDS = [
    "recording_id", "series", "diff_index", "type", "category",
    "location_side", "gold_segment_index", "gold_segment_start", "gold_segment_end",
    "v2_segment_index", "v2_segment_start", "v2_segment_end",
    "gold_word_range", "candidate_word_range",
    "gold_text", "candidate_text",
    "gold_context_before", "gold_context_after",
    "candidate_context_before", "candidate_context_after",
]


def export_csv(series, rid, folder, out_dir):
    gold_text, v2_text = tm.read_text(folder / "v3.json"), tm.read_text(folder / "v2.json")
    entries = tm.word_differences(gold_text, v2_text, True, "relaxed")
    v2_segments, gold_segments = load_segments(folder / "v2.json"), load_segments(folder / "v3.json")
    v2_offsets = cumulative_offsets([s["text"].strip() for s in v2_segments])
    gold_offsets = cumulative_offsets([s["text"].strip() for s in gold_segments])

    out_path = out_dir / f"{rid}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, e in enumerate(entries):
            g0, g1 = e["gold_word_range"]
            c0, c1 = e["candidate_word_range"]
            row = dict.fromkeys(FIELDS, "")
            row.update({
                "recording_id": rid, "series": series, "diff_index": i, "type": e["type"],
                "category": classify(e), "gold_word_range": f"{g0}-{g1}", "candidate_word_range": f"{c0}-{c1}",
                "gold_text": e["gold_text"], "candidate_text": e["candidate_text"],
                "gold_context_before": e["gold_before"], "gold_context_after": e["gold_after"],
                "candidate_context_before": e["candidate_before"], "candidate_context_after": e["candidate_after"],
            })
            if g1 > g0:
                gi = segment_of(g0, gold_offsets)
                row.update(location_side="gold", gold_segment_index=gi,
                           gold_segment_start=gold_segments[gi].get("start"), gold_segment_end=gold_segments[gi].get("end"))
            elif c1 > c0:
                vi = segment_of(c0, v2_offsets)
                row.update(location_side="v2", v2_segment_index=vi,
                           v2_segment_start=v2_segments[vi].get("start"), v2_segment_end=v2_segments[vi].get("end"))
            w.writerow(row)
    return len(entries)


def export_word_diffs(rid, folder, out_dir):
    gold = tm.read_text(folder / "v3.json")
    differences = {v: {profile: tm.word_differences(gold, tm.read_text(folder / f"{v}.json"), strip, mode)
                       for profile, strip, mode in tm.PROFILES}
                   for v in ("v0", "v1", "v2")}
    (out_dir / f"{rid}.json").write_text(json.dumps({
        "index_convention": "zero-based, end-exclusive normalized word ranges; empty range = insertion/deletion boundary",
        "differences": differences}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / f"{rid}.html").write_text(tm.difference_html(differences), encoding="utf-8")


def main():
    p = arg_parser(__doc__)
    p.add_argument("--word-diffs", action="store_true", help="Also write full word-level diff JSON/HTML")
    args = p.parse_args()
    out = args.out or Path(__file__).resolve().parent / "results"
    csv_dir = out / "v2_v3_diffs"
    csv_dir.mkdir(parents=True, exist_ok=True)
    for series, rid, folder in recordings(args.artifacts):
        n = export_csv(series, rid, folder, csv_dir)
        msg = f"{rid}: {n} V2-vs-V3 diffs -> {csv_dir / (rid + '.csv')}"
        if args.word_diffs:
            wd_dir = out / "word_differences"
            wd_dir.mkdir(parents=True, exist_ok=True)
            export_word_diffs(rid, folder, wd_dir)
            msg += f", word diffs -> {wd_dir / rid}.{{json,html}}"
        print(msg)


if __name__ == "__main__":
    main()
