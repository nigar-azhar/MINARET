"""Sweeps alpha/tau/delta (Eq. 1 / Eq. 4 in corpus_validate.py) over the gold set built by
build_gold_set.py, against the Quran and Dua corpora (corpora.quran_db / dua_db), and recommends a value.

Performance note: lexical and semantic scores for a given (query, corpus_row) pair do not depend
on alpha/tau/delta at all - only their *combination* does (Eq. 1), and only the accept/reject
*decision* depends on tau/delta (Eq. 4). So the expensive part (6,236-row Levenshtein/token-F1 per
ayah query; one embedding pass over every corpus row and every query) is computed exactly once and
cached to calibration/cache/*.npy (gitignored - large, regenerable, not real project state); the
alpha/tau/delta grid itself is then just cheap numpy re-combination and thresholding, so the grid
can be as fine as wanted without re-touching the model or the Levenshtein routine.

ayat and dua candidates go through the SAME alpha/tau/delta in the real pipeline (run_e1_v2 passes
one triple to both corpus_validate.validate() calls) - so this script always evaluates a triple
against both corpora together and sums the confusion counts, never tunes them separately, even
though the two per-type breakdowns are also reported for transparency.

Run: python3 -m minaret.calibration.sweep [--quran-db PATH] [--dua-db PATH]
Writes: minaret/calibration/sweep_results.json, minaret/calibration/CALIBRATION_RESULTS.md
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from minaret.pipeline.corpus_validate import (
    default_embed_fn, lexical_score, load_dua_corpus, load_quran_corpus, normalize_for_matching,
)

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "cache"
GOLD_PATH = HERE / "gold_set.json"

# Corpora are not redistributed; defaults come from minaret.yaml (corpora.quran_db / dua_db).
def _config_path(key):
    from minaret import config as config_mod
    p = config_mod.load().path(key)
    return str(p) if p else None


QURAN_DB_DEFAULT = _config_path("corpora.quran_db")
DUA_DB_DEFAULT = _config_path("corpora.dua_db")

ALPHAS = [round(x, 1) for x in np.arange(0.0, 1.01, 0.1)]
TAUS = [round(x, 2) for x in np.arange(0.50, 0.96, 0.05)]
DELTAS = [0.0, 0.02, 0.05, 0.08, 0.12, 0.18, 0.25]


def _embed_cached(texts: list[str], cache_path: Path, embed_fn) -> np.ndarray:
    if cache_path.exists():
        return np.load(cache_path)
    print(f"  embedding {len(texts)} texts -> {cache_path.name} ...", flush=True)
    t0 = time.time()
    vecs = np.array(embed_fn(texts), dtype=np.float32)
    print(f"  done in {time.time() - t0:.0f}s", flush=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, vecs)
    return vecs


def _lexical_matrix_cached(queries_norm: list[str], corpus_norm: list[str], cache_path: Path) -> np.ndarray:
    if cache_path.exists():
        return np.load(cache_path)
    print(f"  computing {len(queries_norm)}x{len(corpus_norm)} lexical matrix -> {cache_path.name} ...", flush=True)
    mat = np.zeros((len(queries_norm), len(corpus_norm)), dtype=np.float32)
    t0 = time.time()
    for i, q in enumerate(queries_norm):
        for j, c in enumerate(corpus_norm):
            mat[i, j] = lexical_score(q, c)
        if i % 25 == 0:
            print(f"    row {i}/{len(queries_norm)} ({time.time() - t0:.0f}s elapsed)", flush=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, mat)
    print(f"  done in {time.time() - t0:.0f}s", flush=True)
    return mat


def build_matrices(gold: list[dict], corpus_rows, etype: str, embed_fn):
    examples = [g for g in gold if g["type"] == etype]
    queries = [e["query_text"] for e in examples]
    queries_norm = [normalize_for_matching(q) for q in queries]
    corpus_texts = [r.text for r in corpus_rows]
    corpus_norm = [normalize_for_matching(t) for t in corpus_texts]
    corpus_keys = np.array([r.key for r in corpus_rows])

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lex_mat = _lexical_matrix_cached(queries_norm, corpus_norm, CACHE_DIR / f"{etype}_lexical.npy")
    corpus_vecs = _embed_cached(corpus_texts, CACHE_DIR / f"{etype}_corpus_emb.npy", embed_fn)
    query_vecs = _embed_cached(queries, CACHE_DIR / f"{etype}_query_emb.npy", embed_fn)
    sem_mat = query_vecs @ corpus_vecs.T  # both L2-normalized by encode(normalize_embeddings=True)

    return examples, corpus_keys, lex_mat, sem_mat


def _filter_quotation(examples: list[dict], keys: np.ndarray, lex: np.ndarray, sem: np.ndarray):
    """Restricts to usage == "quotation" - the only usage the paper's corpus-match formula is
    designed for (q_e is meant to be the Arabic recitation itself, matched against an Arabic
    canonical corpus; "translation"/"explicit
    paraphrase" entities, ~28% of real ayah E1 items, cannot be meaningfully lexically matched
    against an Arabic-only corpus no matter how alpha/tau/delta are set)."""
    mask = np.array([ex.get("usage") == "quotation" for ex in examples])
    filtered_examples = [ex for ex, m in zip(examples, mask) if m]
    return filtered_examples, keys, lex[mask], sem[mask]


def evaluate(examples: list[dict], accept_mask: np.ndarray, top1_key: np.ndarray) -> dict:
    correct_accept = wrong_accept = missed_positive = true_reject = false_accept_neg = 0
    for ex, acc, key in zip(examples, accept_mask, top1_key):
        gold_label = ex["gold_label"]
        if gold_label in ("accept", "accept_different"):
            if acc and key == ex["gold_key"]:
                correct_accept += 1
            elif acc:
                wrong_accept += 1
            else:
                missed_positive += 1
        else:
            if acc:
                false_accept_neg += 1
            else:
                true_reject += 1
    return dict(correct_accept=correct_accept, wrong_accept=wrong_accept, missed_positive=missed_positive,
                true_reject=true_reject, false_accept_neg=false_accept_neg,
                n_pos=correct_accept + wrong_accept + missed_positive,
                n_neg=true_reject + false_accept_neg)


def sweep_type(examples, corpus_keys, lex_mat, sem_mat) -> dict:
    """Returns {(alpha,tau,delta): evaluate(...)} for every grid point, for this one entity type."""
    n = len(examples)
    out = {}
    for alpha in ALPHAS:
        combined = alpha * lex_mat + (1 - alpha) * sem_mat
        order = np.argsort(-combined, axis=1)
        top1_idx, top2_idx = order[:, 0], order[:, 1]
        rows = np.arange(n)
        top1_score, top2_score = combined[rows, top1_idx], combined[rows, top2_idx]
        top1_key = corpus_keys[top1_idx]
        for tau in TAUS:
            for delta in DELTAS:
                accept_mask = (top1_score >= tau) & (top1_score - top2_score >= delta)
                out[(alpha, tau, delta)] = evaluate(examples, accept_mask, top1_key)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quran-db", default=QURAN_DB_DEFAULT)
    parser.add_argument("--dua-db", default=DUA_DB_DEFAULT)
    args = parser.parse_args()

    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(gold)} gold examples", flush=True)

    quran_corpus = load_quran_corpus(args.quran_db)
    dua_corpus = load_dua_corpus(args.dua_db)
    print(f"Corpus: {len(quran_corpus)} ayat, {len(dua_corpus)} dua", flush=True)

    print("Building ayah matrices...", flush=True)
    ayah_examples, ayah_keys, ayah_lex, ayah_sem = build_matrices(gold, quran_corpus, "ayah", default_embed_fn)
    print("Building dua matrices...", flush=True)
    dua_examples, dua_keys, dua_lex, dua_sem = build_matrices(gold, dua_corpus, "dua", default_embed_fn)

    # Primary calibration target: usage == "quotation" only (see _filter_quotation docstring for
    # why translation/paraphrase entities are excluded from tuning, not just from this filter's mask).
    ayah_q_ex, ayah_q_keys, ayah_q_lex, ayah_q_sem = _filter_quotation(ayah_examples, ayah_keys, ayah_lex, ayah_sem)
    dua_q_ex, dua_q_keys, dua_q_lex, dua_q_sem = _filter_quotation(dua_examples, dua_keys, dua_lex, dua_sem)
    print(f"Quotation-only subset: {len(ayah_q_ex)}/{len(ayah_examples)} ayah, {len(dua_q_ex)}/{len(dua_examples)} dua", flush=True)

    def full_grid(label, ayah_ex, ayah_k, ayah_l, ayah_s, dua_ex, dua_k, dua_l, dua_s):
        print(f"Sweeping {label} grid...", flush=True)
        a_grid = sweep_type(ayah_ex, ayah_k, ayah_l, ayah_s)
        d_grid = sweep_type(dua_ex, dua_k, dua_l, dua_s)
        out = []
        for alpha in ALPHAS:
            for tau in TAUS:
                for delta in DELTAS:
                    a, d = a_grid[(alpha, tau, delta)], d_grid[(alpha, tau, delta)]
                    total_correct = a["correct_accept"] + d["correct_accept"]
                    total_wrong = a["wrong_accept"] + d["wrong_accept"]
                    total_missed = a["missed_positive"] + d["missed_positive"]
                    total_true_reject = a["true_reject"] + d["true_reject"]
                    total_false_accept_neg = a["false_accept_neg"] + d["false_accept_neg"]
                    n_pos = a["n_pos"] + d["n_pos"]
                    n_neg = a["n_neg"] + d["n_neg"]
                    recall = total_correct / n_pos if n_pos else None
                    precision = total_correct / (total_correct + total_wrong) if (total_correct + total_wrong) else None
                    f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall) > 0) else 0.0
                    out.append({
                        "alpha": alpha, "tau": tau, "delta": delta, "ayah": a, "dua": d,
                        "total_correct_accept": total_correct, "total_wrong_accept": total_wrong,
                        "total_missed_positive": total_missed, "total_true_reject": total_true_reject,
                        "total_false_accept_neg": total_false_accept_neg, "n_pos": n_pos, "n_neg": n_neg,
                        "grounding_recall": recall, "grounding_precision": precision,
                        "grounding_f1": f1,
                        "specificity": total_true_reject / n_neg if n_neg else None,
                    })
        return out

    quotation_results = full_grid("quotation-only", ayah_q_ex, ayah_q_keys, ayah_q_lex, ayah_q_sem,
                                   dua_q_ex, dua_q_keys, dua_q_lex, dua_q_sem)
    all_usage_results = full_grid("all-usages", ayah_examples, ayah_keys, ayah_lex, ayah_sem,
                                   dua_examples, dua_keys, dua_lex, dua_sem)

    (HERE / "sweep_results.json").write_text(
        json.dumps({"quotation_only": quotation_results, "all_usages": all_usage_results}, indent=2),
        encoding="utf-8")
    print(f"Wrote {HERE / 'sweep_results.json'} ({len(quotation_results)} grid points x 2 scopes)")

    # Recommendation: maximize F1 (precision and recall both matter - a wrong-accept silently
    # writes the WRONG verse into V2, a missed positive just falls back to human review, so this
    # isn't a case for optimizing recall alone) over the quotation-only grid, tie-broken toward
    # fewer wrong-accepts, then higher tau (stricter/simpler to reason about), then lower delta.
    top = sorted(quotation_results,
                 key=lambda r: (-r["grounding_f1"], r["total_wrong_accept"], -r["tau"], r["delta"]))[:15]

    all_by_key = {(r["alpha"], r["tau"], r["delta"]): r for r in all_usage_results}

    lines = []
    lines.append("# alpha/tau/delta calibration results\n")
    lines.append(f"Gold set: {len(gold)} examples ({len(ayah_examples)} ayah, {len(dua_examples)} dua) from "
                  f"`minaret/calibration/gold_set.json`, built by `build_gold_set.py` from the E1-vs-E2 "
                  f"pairs of the 18 released recordings (the pairing RQ2 uses).\n")
    lines.append(f"**Primary scope: usage == \"quotation\" only** ({len(ayah_q_ex)}/{len(ayah_examples)} ayah, "
                  f"{len(dua_q_ex)}/{len(dua_examples)} dua) - "
                  f"translation/paraphrase-usage entities are excluded from tuning (structurally unmatchable "
                  f"against an Arabic-only corpus via lexical scoring, not a threshold problem). The same triples' "
                  f"performance against *all* usages (including translation/paraphrase) is shown alongside for "
                  f"transparency, not used to pick the recommendation.\n")
    lines.append(f"Grid: alpha in {[float(a) for a in ALPHAS]}, tau in {[float(t) for t in TAUS]}, "
                  f"delta in {DELTAS} ({len(quotation_results)} points).\n")
    lines.append("## Top candidates by F1 on the quotation-only scope\n")
    lines.append("| alpha | tau | delta | correct | wrong | missed | recall | precision | F1 "
                  "|| all-usages recall | all-usages precision |")
    lines.append("|---|---|---|---|---|---|---|---|---" "||---|---|")
    for r in top:
        a = all_by_key[(r["alpha"], r["tau"], r["delta"])]
        lines.append(
            f"| {r['alpha']} | {r['tau']} | {r['delta']} | {r['total_correct_accept']} | "
            f"{r['total_wrong_accept']} | {r['total_missed_positive']} | {r['grounding_recall']:.3f} | "
            f"{(r['grounding_precision'] or float('nan')):.3f} | {r['grounding_f1']:.3f} "
            f"|| {(a['grounding_recall'] or float('nan')):.3f} | {(a['grounding_precision'] or float('nan')):.3f} |"
        )

    (HERE / "CALIBRATION_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {HERE / 'CALIBRATION_RESULTS.md'}")
    print("\nTop 5 (quotation-only F1):")
    for r in top[:5]:
        print(r["alpha"], r["tau"], r["delta"], "correct=", r["total_correct_accept"],
              "wrong=", r["total_wrong_accept"], "missed=", r["total_missed_positive"],
              "recall=", r["grounding_recall"], "precision=", r["grounding_precision"], "f1=", r["grounding_f1"])


if __name__ == "__main__":
    main()
