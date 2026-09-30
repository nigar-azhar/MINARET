#!/usr/bin/env python3
"""RQ5 -- RAG retrieval and answer quality.

1. Re-scores every graded trace (<artifacts>/rag/graded_trace_index.json) against the gold
   questions and checks that the automatic retrieval/citation metrics equal the ones stored in
   the human-graded review files (reviews/<scope>__<model>.json). Answer verdicts are human
   judgments and are read, never recomputed.
2. Aggregates the reviews: lecture scope (18 recordings x 3 models) and series scope (4 series x
   3 models), written to results/lecture_scope.* and results/series_scope.*.

    python evaluation/rq5_rag/compute.py [--artifacts runs/]

To grade a new run: `python -m minaret.cli rag query ...`, then evaluate_rag.py score, fill in
answer_verdict by hand, then evaluate_rag.py aggregate.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluation.common.artifacts import REPO_ROOT, arg_parser, load_json  # noqa: E402
import evaluate_rag as er  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL_SUFFIX = {"qwen3.5-9b-mlx": "qwen35", "gemma-4-e4b-it": "gemma4e4b",
                "meta-llama-3.1-8b-instruct@q6_k": "llama31_8b"}


def gold_file(scope: str) -> Path:
    if scope.startswith("series_"):
        return HERE / "questions" / "series" / f"{scope[len('series_'):]}.json"
    return HERE / "questions" / f"{scope}.json"


def verify(artifacts: Path) -> list[str]:
    index = load_json(Path(artifacts) / "rag" / "graded_trace_index.json")
    problems, checked = [], 0
    for scope, per_model in index.items():
        gold = {g["question_id"]: g for g in load_json(gold_file(scope))}
        for model, trace_rel in per_model.items():
            review_path = HERE / "reviews" / f"{scope}__{MODEL_SUFFIX[model]}.json"
            reviews = {r["question_id"]: r for r in load_json(review_path)}
            # index entries are "artifacts/rag/traces/..."; resolve them inside --artifacts
            trace_path = Path(artifacts) / Path(trace_rel).relative_to("artifacts")
            for rec in load_json(trace_path):
                qid = rec["question_id"]
                if qid not in reviews:
                    continue
                g = gold[qid]
                ids = g.get("gold_chunk_ids", [])
                ret = er.retrieval_metrics(ids, rec["initial_retrieved"], rec["reranked"], rec["chunks_sent_to_model"])
                cit = er.citation_metrics(ids, rec["generated_answer"], rec["chunks_sent_to_model"])
                if ret != reviews[qid]["retrieval"] or cit != reviews[qid]["citation"]:
                    problems.append(f"{review_path.name} {qid}: recomputed metrics differ from stored review")
                checked += 1
    print(f"[rq5] re-scored {checked} graded question(s) from traces; {len(problems)} mismatch(es)")
    return problems


def aggregate(review_files: list[Path], out: Path) -> None:
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)  # keeps source paths in the summary repo-relative
    try:
        er.cmd_aggregate(SimpleNamespace(reviews=[str(f.relative_to(REPO_ROOT)) for f in review_files], out=str(out)))
    finally:
        os.chdir(cwd)


def main():
    args = arg_parser(__doc__).parse_args()
    out = (args.out or HERE / "results").resolve()
    out.mkdir(parents=True, exist_ok=True)
    problems = verify(args.artifacts)
    for p in problems:
        print("  " + p)
    reviews = sorted((HERE / "reviews").glob("*__*.json"))
    lecture = [p for p in reviews if not p.name.startswith("series_")]
    series = [p for p in reviews if p.name.startswith("series_")]
    aggregate(lecture, out / "lecture_scope.md")
    aggregate(series, out / "series_scope.md")
    print(f"[rq5] aggregated {len(lecture)} lecture-scope and {len(series)} series-scope review files")
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
