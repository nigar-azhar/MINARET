#!/usr/bin/env python3
"""RQ2 entity-accuracy metrics: E1 (automated) vs E2 (reviewer-validated), per recording and
pooled, from <artifacts>/recordings/*/*/{e1,e2}.json.

Matching key per entity type:
  ayat:   (surah_number, ayah_number, round(start,1))
  hadith: (reference, round(start,1))
  dua:    (reference, round(start,1))
An E1 item matched to an E2 item at the same key is a true positive (retained if text identical,
corrected if text differs). An E1 item with no match in E2 is a rejection (false positive). An E2
item with no match in E1 is an addition/omission from E1's perspective (false negative).

Entity-level = distinct identity values per lecture (ignoring start/multiple mentions).
Occurrence-level = every individual grounded mention.

Run: python evaluation/rq2_entities/compute.py [--artifacts runs/]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.common.artifacts import arg_parser, load_json, recordings, write_results  # noqa: E402

TYPES = ["ayat", "hadith", "dua"]


def key_for(item, etype):
    start = round(float(item.get("start", 0)), 1)
    if etype == "ayat":
        return (str(item.get("surah_number")), str(item.get("ayah_number")), start)
    return (str(item.get("reference")), start)


def score(e1_items, e2_items, etype):
    e1_keys = [key_for(it, etype) for it in e1_items]
    e2_keys = [key_for(it, etype) for it in e2_items]
    e1_by_key = dict(zip(e1_keys, e1_items))
    e2_by_key = dict(zip(e2_keys, e2_items))
    e1_set, e2_set = set(e1_keys), set(e2_keys)

    matched = e1_set & e2_set
    rejected = e1_set - e2_set
    added = e2_set - e1_set

    retained = sum(1 for k in matched if e1_by_key[k].get("text", "").strip() == e2_by_key[k].get("text", "").strip())
    corrected = len(matched) - retained

    tp = len(matched)
    fp = len(rejected)
    fn = len(added)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall) > 0) else None

    # entity-level: distinct identity ignoring start
    e1_entities = {k[:-1] for k in e1_keys}
    e2_entities = {k[:-1] for k in e2_keys}
    ent_matched = e1_entities & e2_entities
    ent_p = len(ent_matched) / len(e1_entities) if e1_entities else None
    ent_r = len(ent_matched) / len(e2_entities) if e2_entities else None
    ent_f1 = (2 * ent_p * ent_r / (ent_p + ent_r)) if (ent_p and ent_r and (ent_p + ent_r) > 0) else None

    return {
        "e1_occurrence_count": len(e1_items), "e2_occurrence_count": len(e2_items),
        "e1_entity_count": len(e1_entities), "e2_entity_count": len(e2_entities),
        "entity_matched": len(ent_matched),
        "occurrence_precision": precision, "occurrence_recall": recall, "occurrence_f1": f1,
        "entity_precision": ent_p, "entity_recall": ent_r, "entity_f1": ent_f1,
        "retained": retained, "corrected": corrected, "rejected": len(rejected), "added_by_reviewer": len(added),
        "retention_rate": retained / len(e1_items) if e1_items else None,
        "correction_rate": corrected / len(e1_items) if e1_items else None,
        "rejection_rate": len(rejected) / len(e1_items) if e1_items else None,
        "omission_rate": len(added) / len(e2_items) if e2_items else None,
    }


def main():
    args = arg_parser(__doc__).parse_args()
    out = args.out or Path(__file__).resolve().parent / "results"
    per_recording = {}
    grand = {t: {"e1": 0, "e2": 0, "tp": 0, "fp": 0, "fn": 0, "retained": 0, "corrected": 0} for t in TYPES}

    series_of = {}
    for series, rid, d in recordings(args.artifacts):
        series_of[rid] = series
        e1 = load_json(d / "e1.json")
        e2 = load_json(d / "e2.json")
        per_recording[rid] = {}
        for t in TYPES:
            e1_items = e1.get(t, [])
            e2_items = e2.get(t, [])
            s = score(e1_items, e2_items, t)
            per_recording[rid][t] = s
            grand[t]["e1"] += s["e1_occurrence_count"]
            grand[t]["e2"] += s["e2_occurrence_count"]
            grand[t]["tp"] += s["retained"] + s["corrected"]
            grand[t]["fp"] += s["rejected"]
            grand[t]["fn"] += s["added_by_reviewer"]
            grand[t]["retained"] += s["retained"]
            grand[t]["corrected"] += s["corrected"]

    grand_summary = {}
    for t in TYPES:
        g = grand[t]
        p = g["tp"] / (g["tp"] + g["fp"]) if (g["tp"] + g["fp"]) else None
        r = g["tp"] / (g["tp"] + g["fn"]) if (g["tp"] + g["fn"]) else None
        f1 = (2 * p * r / (p + r)) if (p and r and (p + r) > 0) else None
        grand_summary[t] = {
            "e1_total": g["e1"], "e2_total": g["e2"],
            "precision": p, "recall": r, "f1": f1,
            "retention_rate": g["retained"] / g["e1"] if g["e1"] else None,
            "correction_rate": g["corrected"] / g["e1"] if g["e1"] else None,
            "rejection_rate": g["fp"] / g["e1"] if g["e1"] else None,
            "omission_rate": g["fn"] / g["e2"] if g["e2"] else None,
        }

    by_series = pooled_by_series(per_recording, series_of)
    write_results(out, "rq2_entity_accuracy",
                  {"per_recording": per_recording, "by_series": by_series, "grand_total": grand_summary},
                  render_markdown(by_series))


def _prf(tp, n_pred, n_gold):
    p = tp / n_pred if n_pred else None
    r = tp / n_gold if n_gold else None
    f1 = 2 * p * r / (p + r) if (p and r) else None
    return {"precision": p, "recall": r, "f1": f1}


def pooled_by_series(per_recording, series_of):
    """Entity- and occurrence-level P/R/F1 pooled per series and over all recordings (the paper's
    RQ2 tables), plus occurrence-level intervention rates."""
    groups = {}
    for rid, per_type in per_recording.items():
        for key in (series_of[rid], "ALL"):
            for t, s in per_type.items():
                g = groups.setdefault(key, {}).setdefault(t, dict.fromkeys(
                    ["ent_tp", "ent_e1", "ent_e2", "occ_tp", "occ_e1", "occ_e2",
                     "retained", "corrected", "rejected", "added"], 0))
                g["ent_tp"] += s["entity_matched"]; g["ent_e1"] += s["e1_entity_count"]; g["ent_e2"] += s["e2_entity_count"]
                g["occ_tp"] += s["retained"] + s["corrected"]; g["occ_e1"] += s["e1_occurrence_count"]
                g["occ_e2"] += s["e2_occurrence_count"]
                for k_src, k in (("retained", "retained"), ("corrected", "corrected"),
                                 ("rejected", "rejected"), ("added_by_reviewer", "added")):
                    g[k] += s[k_src]
    out = {}
    for key in [k for k in groups if k != "ALL"] + ["ALL"]:
        per_type = groups[key]
        out[key] = {}
        for t, g in per_type.items():
            out[key][t] = {
                "entity": _prf(g["ent_tp"], g["ent_e1"], g["ent_e2"]),
                "occurrence": _prf(g["occ_tp"], g["occ_tp"] + g["rejected"], g["occ_tp"] + g["added"]),
                "retention_rate": g["retained"] / g["occ_e1"] if g["occ_e1"] else None,
                "correction_rate": g["corrected"] / g["occ_e1"] if g["occ_e1"] else None,
                "rejection_rate": g["rejected"] / g["occ_e1"] if g["occ_e1"] else None,
                "omission_rate": g["added"] / g["occ_e2"] if g["occ_e2"] else None,
            }
    return out


def render_markdown(by_series):
    def f(x):
        return "--" if x is None else f"{100 * x:.1f}"
    md = ["# RQ2 -- entity accuracy (E1 vs E2)", ""]
    for level in ("entity", "occurrence"):
        md += [f"## {level.capitalize()}-level P / R / F1 (%)", "",
               "| Series | Ayat P | Ayat R | Ayat F1 | Hadith P | Hadith R | Hadith F1 | Dua P | Dua R | Dua F1 |",
               "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for key, per_type in by_series.items():
            cells = [f(per_type[t][level][m]) for t in TYPES for m in ("precision", "recall", "f1")]
            md.append(f"| {'**Pooled**' if key == 'ALL' else key} | " + " | ".join(cells) + " |")
        md.append("")
    md += ["## Occurrence-level intervention rates (%)", "",
           "| Series | Type | Retention | Correction | Rejection | Omission |", "|---|---|---:|---:|---:|---:|"]
    for key, per_type in by_series.items():
        for t in TYPES:
            r = per_type[t]
            md.append(f"| {key} | {t} | {f(r['retention_rate'])} | {f(r['correction_rate'])} | "
                      f"{f(r['rejection_rate'])} | {f(r['omission_rate'])} |")
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    main()
