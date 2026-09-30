#!/usr/bin/env python3
"""ASR model selection (REPORT.md in this directory): CER/WER and global deletion counts of four
Whisper variants (OpenAI Whisper and faster-whisper, each turbo and large-v3; medium runs kept for
completeness but excluded from selection as incomplete) on two SKD2025 recordings, against the
reviewed V3. This is the comparison behind the pipeline's choice of faster-whisper
large-v3-turbo for V0.

Input: <artifacts>/asr_model_selection/<recording>/<backend>/<model>.json
       <artifacts>/recordings/SKD2025/<recording>/v3.json

    python evaluation/asr_model_selection/compute.py [--artifacts runs/]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.common import transcript_metrics as tm  # noqa: E402
from evaluation.common.artifacts import arg_parser, load_json, write_results  # noqa: E402

EXCLUDED = {"medium"}  # hypothesis word counts far below gold: incomplete outputs, see REPORT.md


def main():
    args = arg_parser(__doc__).parse_args()
    out = args.out or Path(__file__).resolve().parent / "results"
    root = Path(args.artifacts) / "asr_model_selection"
    rows = []
    for rec_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        gold = tm.read_text(Path(args.artifacts) / "recordings" / "SKD2025" / rec_dir.name / "v3.json")
        for f in sorted(rec_dir.glob("*/*.json")):
            d = load_json(f)
            hyp = " ".join(s["text"].strip() for s in d["segments"])
            scores = tm.compare(gold, hyp)
            rows.append({
                "recording": rec_dir.name, "backend": d["backend"], "model": d["model"],
                "excluded_from_selection": d["model"] in EXCLUDED,
                "elapsed_seconds": (d.get("runtime") or {}).get("elapsed_seconds"),
                **{f"{p}_{m}": scores[p][m]["error_rate"] for p in ("without_diacritics", "with_diacritics")
                   for m in ("cer", "wer")},
                "char_deletions": scores["without_diacritics"]["cer"]["deletions"],
                "word_deletions": scores["without_diacritics"]["wer"]["deletions"],
            })

    agg = {}
    for r in rows:
        if r["excluded_from_selection"]:
            continue
        a = agg.setdefault((r["backend"], r["model"]), {"cer": [], "wer": [], "cdel": 0, "wdel": 0})
        a["cer"].append(r["without_diacritics_cer"]); a["wer"].append(r["without_diacritics_wer"])
        a["cdel"] += r["char_deletions"]; a["wdel"] += r["word_deletions"]
    aggregate = sorted(({"backend": b, "model": m, "mean_cer": sum(a["cer"]) / len(a["cer"]),
                         "mean_wer": sum(a["wer"]) / len(a["wer"]), "total_char_deletions": a["cdel"],
                         "total_word_deletions": a["wdel"]} for (b, m), a in agg.items()),
                       key=lambda x: x["mean_cer"])

    md = ["# ASR model selection -- recomputed", "",
          "Diacritics removed. CER/WER in %. Mean = unweighted mean of the two recordings (as in REPORT.md).", "",
          "| Recording | Backend | Model | CER | WER | Char del. | Word del. | CER (diacritics kept) |",
          "|---|---|---|---:|---:|---:|---:|---:|"]
    for r in sorted(rows, key=lambda r: (r["recording"], r["without_diacritics_cer"])):
        tag = " (excluded)" if r["excluded_from_selection"] else ""
        md.append(f"| {r['recording']} | {r['backend']} | {r['model']}{tag} | {100 * r['without_diacritics_cer']:.2f} | "
                  f"{100 * r['without_diacritics_wer']:.2f} | {r['char_deletions']:,} | {r['word_deletions']:,} | "
                  f"{100 * r['with_diacritics_cer']:.2f} |")
    md += ["", "| Backend | Model | Mean CER | Mean WER | Total char del. | Total word del. |", "|---|---|---:|---:|---:|---:|"]
    for a in aggregate:
        md.append(f"| {a['backend']} | {a['model']} | {100 * a['mean_cer']:.2f} | {100 * a['mean_wer']:.2f} | "
                  f"{a['total_char_deletions']:,} | {a['total_word_deletions']:,} |")
    write_results(out, "asr_model_selection", {"per_run": rows, "aggregate": aggregate}, "\n".join(md) + "\n")


if __name__ == "__main__":
    main()
