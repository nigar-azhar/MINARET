#!/usr/bin/env python3
"""RQ1 -- transcript improvement: CER/WER of V0, V1, V2 against reviewed V3, relative error
reduction (paper Eq. 14: RER(Va,Vb) = (ER(Va) - ER(Vb)) / ER(Va) x 100) for V0->V1, V1->V2,
V0->V2, and changed-segment rate between adjacent versions.

Headline numbers use the `without_diacritics` profile; every profile is kept in the JSON.

    python evaluation/rq1_transcripts/compute.py [--artifacts runs/]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.common import transcript_metrics as tm  # noqa: E402
from evaluation.common.artifacts import arg_parser, load_segments, recordings, write_results  # noqa: E402

HEADLINE = "without_diacritics"


def rer(er_a, er_b):
    return (er_a - er_b) / er_a * 100 if er_a else None


def changed_segment_rate(a_texts, b_texts):
    if len(a_texts) != len(b_texts):
        return None  # segment count differs -- not a like-for-like comparison
    changed = sum(1 for a, b in zip(a_texts, b_texts)
                  if tm.normalize(a, True, "relaxed") != tm.normalize(b, True, "relaxed"))
    return changed / len(a_texts) if a_texts else None


def pooled(rows):
    """Series and corpus pooling from total edit counts (paper: a series' figure reflects its total
    transcribed content, not an unweighted mean of recording rates)."""
    groups = {}
    for r in rows:
        for key in (r["series"], "ALL"):
            g = groups.setdefault(key, {m: {v: [0, 0] for v in ("v0", "v1", "v2")} for m in ("cer", "wer")})
            for m in ("cer", "wer"):
                for v in ("v0", "v1", "v2"):
                    meas = r["all_profiles"][v][HEADLINE][m]
                    g[m][v][0] += meas["substitutions"] + meas["deletions"] + meas["insertions"]
                    g[m][v][1] += meas["reference_units"]
    out = {}
    for key in [k for k in groups if k != "ALL"] + ["ALL"]:
        g = groups[key]
        er = {m: {v: g[m][v][0] / g[m][v][1] for v in g[m]} for m in g}
        out[key] = {"cer": er["cer"], "wer": er["wer"],
                    "rer_cer": {"v0_v1": rer(er["cer"]["v0"], er["cer"]["v1"]), "v1_v2": rer(er["cer"]["v1"], er["cer"]["v2"]),
                                "v0_v2": rer(er["cer"]["v0"], er["cer"]["v2"])},
                    "rer_wer": {"v0_v1": rer(er["wer"]["v0"], er["wer"]["v1"]), "v1_v2": rer(er["wer"]["v1"], er["wer"]["v2"]),
                                "v0_v2": rer(er["wer"]["v0"], er["wer"]["v2"])}}
    return out


def pct(x):
    return "n/a" if x is None else f"{x:.1f}"


def main():
    args = arg_parser(__doc__).parse_args()
    out = args.out or Path(__file__).resolve().parent / "results"
    rows = []
    for series, rid, d in recordings(args.artifacts):
        gold = tm.read_text(d / "v3.json")
        texts = {v: [s["text"].strip() for s in load_segments(d / f"{v}.json")] for v in ("v0", "v1", "v2")}
        scores = {v: tm.compare(gold, tm.read_text(d / f"{v}.json")) for v in ("v0", "v1", "v2")}
        cer = {v: scores[v][HEADLINE]["cer"]["error_rate"] for v in scores}
        wer = {v: scores[v][HEADLINE]["wer"]["error_rate"] for v in scores}
        rows.append({
            "series": series, "recording": rid, "cer": cer, "wer": wer,
            "rer_cer_v0_v1": rer(cer["v0"], cer["v1"]), "rer_cer_v1_v2": rer(cer["v1"], cer["v2"]),
            "rer_cer_v0_v2": rer(cer["v0"], cer["v2"]),
            "rer_wer_v0_v1": rer(wer["v0"], wer["v1"]), "rer_wer_v1_v2": rer(wer["v1"], wer["v2"]),
            "rer_wer_v0_v2": rer(wer["v0"], wer["v2"]),
            "changed_segment_rate_v0_v1": changed_segment_rate(texts["v0"], texts["v1"]),
            "changed_segment_rate_v1_v2": changed_segment_rate(texts["v1"], texts["v2"]),
            "segment_counts": {v: len(t) for v, t in texts.items()},
            "all_profiles": scores,
        })

    by_series = pooled(rows)
    md = ["# RQ1 -- transcript improvement", "",
          f"Profile: `{HEADLINE}`. CER/WER in %, RER in % (paper Eq. 14). Reference: reviewed V3.", "",
          "## Pooled by series (from total edit counts)", "",
          "| Series | CER V0 | CER V1 | CER V2 | RER V0→V1 | RER V1→V2 | RER V0→V2 | WER V0 | WER V1 | WER V2 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, g in by_series.items():
        md.append(f"| {'**All (pooled)**' if key == 'ALL' else key} | "
                  + " | ".join(f"{g['cer'][v] * 100:.2f}" for v in ("v0", "v1", "v2")) + " | "
                  + " | ".join(pct(g["rer_cer"][k]) for k in ("v0_v1", "v1_v2", "v0_v2")) + " | "
                  + " | ".join(f"{g['wer'][v] * 100:.2f}" for v in ("v0", "v1", "v2")) + " |")
    md += ["", "## Per recording", "",
          "| Series | Recording | CER V0 | CER V1 | CER V2 | WER V0 | WER V1 | WER V2 | RER-CER V0→V2 | RER-WER V0→V2 |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        md.append(f"| {r['series']} | {r['recording']} | "
                  + " | ".join(pct(r["cer"][v] * 100) for v in ("v0", "v1", "v2")) + " | "
                  + " | ".join(pct(r["wer"][v] * 100) for v in ("v0", "v1", "v2")) + " | "
                  + f"{pct(r['rer_cer_v0_v2'])} | {pct(r['rer_wer_v0_v2'])} |")
    write_results(out, "rq1_metrics", {"by_series": by_series, "per_recording": rows}, "\n".join(md) + "\n")


if __name__ == "__main__":
    main()
