#!/usr/bin/env python3
"""RQ3 -- human review effort: end-to-end review time per recording, normalised by audio duration.

RTF (real-time factor) = review hours / audio hours; minutes of review per audio hour = RTF x 60.
Pooled figures divide total review time by total audio time (not a mean of per-recording ratios).

Input: review_effort.csv in this directory (one self-reported end-to-end review time per recording,
recorded by the reviewers; durations cross-checked against the ASR manifests).

    python evaluation/rq3_review_effort/compute.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.common.artifacts import write_results  # noqa: E402

HERE = Path(__file__).resolve().parent


def row_stats(audio_min, review_h):
    rtf = review_h / (audio_min / 60)
    return {"audio_minutes": audio_min, "review_hours": review_h, "rtf": rtf, "review_min_per_audio_hour": rtf * 60}


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=HERE / "review_effort.csv")
    p.add_argument("--out", type=Path, default=HERE / "results")
    args = p.parse_args()

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    per_recording, groups = {}, {}
    for r in rows:
        audio, review = float(r["Audio Duration (min)"]), float(r["Self-Reported Review Time (hours)"])
        per_recording[r["Recording"]] = {"series": r["Series"], **row_stats(audio, review)}
        for key in (r["Series"], "ALL"):
            g = groups.setdefault(key, [0.0, 0.0])
            g[0] += audio
            g[1] += review
    by_series = {k: row_stats(*groups[k]) for k in [k for k in groups if k != "ALL"] + ["ALL"]}

    md = ["# RQ3 -- human review effort", "",
          "| Recording | Audio (min) | Review (h) | RTF | Min. review / audio-hr |", "|---|---:|---:|---:|---:|"]
    for rid, s in per_recording.items():
        md.append(f"| {rid} | {s['audio_minutes']:.1f} | {s['review_hours']:.2f} | {s['rtf']:.2f} | "
                  f"{s['review_min_per_audio_hour']:.1f} |")
    md += ["", "| Series | Review (h) | Audio (h) | RTF | Min. review / audio-hr |", "|---|---:|---:|---:|---:|"]
    for key, s in by_series.items():
        md.append(f"| {'**Pooled**' if key == 'ALL' else key} | {s['review_hours']:.2f} | "
                  f"{s['audio_minutes'] / 60:.2f} | {s['rtf']:.2f} | {s['review_min_per_audio_hour']:.1f} |")
    write_results(args.out, "rq3_review_effort", {"per_recording": per_recording, "by_series": by_series},
                  "\n".join(md) + "\n")


if __name__ == "__main__":
    main()
