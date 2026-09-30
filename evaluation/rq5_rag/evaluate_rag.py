#!/usr/bin/env python3
"""RQ5 scoring harness: retrieval + citation metrics computed automatically
from a query.py trace and a human-curated gold-question file; answer
correctness is left as a human judgment call, filled into the review file
this produces before running --aggregate.

Gold question file (you write this, per lecture or per series - see
evaluation/rq5_rag/questions/README.md): a list of
    {"question_id": "Q1", "question": "...", "answerable": true,
     "gold_chunk_ids": ["<chunk_id>", ...]}
Use artifacts/rag/index/<recording>/chunks.json (or the series index) to pick
gold_chunk_ids by reading the chunk text yourself. A deliberately
unanswerable question (content this lecture doesn't cover) gets
"answerable": false and "gold_chunk_ids": [] - this tests whether the system
correctly refuses instead of guessing.

Step 1 - score (automatic retrieval/citation metrics + blank fields for you
to fill in by hand):
    python evaluation/rq5_rag/evaluate_rag.py score \\
        --gold evaluation/rq5_rag/questions/SKD_U001_S001_0001.json \\
        --trace runs/rag/traces/SKD_U001_S001_0001/<timestamp>.json \\
        --out runs/rag/reviews/SKD_U001_S001_0001.json

Then open the --out file and fill in "answer_verdict" (and optionally
"grader_notes") for every question - see VERDICTS below for the allowed
values per answerable/unanswerable question.

Step 2 - aggregate one or more completed review files into the final RQ5
numbers:
    python evaluation/rq5_rag/evaluate_rag.py aggregate \\
        --reviews runs/rag/reviews/*.json \\
        --out runs/rag/evaluation.md
"""
import argparse
import glob
import json
import statistics
from pathlib import Path

VERDICTS_ANSWERABLE = ["correct_grounded", "partially_correct", "incorrect", "hallucinated"]
VERDICTS_UNANSWERABLE = ["correctly_refused", "incorrectly_answered"]


def retrieval_metrics(gold_ids, initial, reranked, sent):
    gold = set(gold_ids)

    def rank_of_first_gold(items):
        for item in items:
            if item["chunk_id"] in gold:
                return item["rank"]
        return None

    initial_ids = {i["chunk_id"] for i in initial}
    reranked_ids = {i["chunk_id"] for i in reranked}
    sent_ids = {i["chunk_id"] for i in sent}

    sent_hit_count = len(gold & sent_ids)
    return {
        "initial_hit": bool(gold & initial_ids) if gold else None,
        "initial_rank_of_first_gold": rank_of_first_gold(initial) if gold else None,
        "reranked_hit": bool(gold & reranked_ids) if gold else None,
        "reranked_rank_of_first_gold": rank_of_first_gold(reranked) if gold else None,
        "sent_hit": bool(gold & sent_ids) if gold else None,
        "sent_precision": (sent_hit_count / len(sent_ids)) if (gold and sent_ids) else None,
        "sent_recall": (sent_hit_count / len(gold)) if gold else None,
    }


def citation_metrics(gold_ids, generated_answer, sent):
    gold = set(gold_ids)
    sent_ids = {c["chunk_id"] for c in sent}
    cited = {cid for cid in sent_ids if cid in generated_answer}
    no_citation = len(cited) == 0
    return {
        "cited_chunk_ids": sorted(cited),
        "citation_precision": (len(cited & gold) / len(cited)) if (gold and cited) else None,
        "citation_recall": (len(cited & gold) / len(gold)) if gold else None,
        "no_citation_found": no_citation,
    }


def cmd_score(args):
    gold_items = {g["question_id"]: g for g in json.loads(Path(args.gold).read_text(encoding="utf-8"))}
    trace = json.loads(Path(args.trace).read_text(encoding="utf-8"))

    reviews = []
    for rec in trace:
        qid = rec["question_id"]
        if qid not in gold_items:
            print(f"[evaluate_rag] WARNING: {qid} in trace has no gold entry, skipping")
            continue
        gold = gold_items[qid]
        answerable = gold["answerable"]
        gold_ids = gold.get("gold_chunk_ids", [])

        rmetrics = retrieval_metrics(gold_ids, rec["initial_retrieved"], rec["reranked"], rec["chunks_sent_to_model"])
        cmetrics = citation_metrics(gold_ids, rec["generated_answer"], rec["chunks_sent_to_model"])

        reviews.append({
            "question_id": qid,
            "question": rec["question"],
            "question_language": gold.get("question_language"),
            "search_scope": rec.get("search_scope"),
            "scope_label": rec.get("scope_label"),
            "answerable": answerable,
            "gold_chunk_ids": gold_ids,
            "rerank_status": rec["rerank_status"],
            "retrieval": rmetrics,
            "citation": cmetrics,
            "generated_answer": rec["generated_answer"],
            "generation_model": rec.get("generation_model"),
            "system_prompt_used": rec.get("system_prompt_used"),
            "finish_reason": rec.get("finish_reason"),
            "reasoning_content_length": rec.get("reasoning_content_length"),
            "elapsed_seconds": rec.get("elapsed_seconds"),
            "generated_at": rec.get("generated_at"),
            "answer_verdict": None,  # FILL IN: see VERDICTS_ANSWERABLE / VERDICTS_UNANSWERABLE
            "grader_notes": "",
        })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[evaluate_rag] wrote {len(reviews)} review record(s) -> {out_path}")
    print(f"[evaluate_rag] fill in 'answer_verdict' for each (answerable: {VERDICTS_ANSWERABLE}, "
          f"unanswerable: {VERDICTS_UNANSWERABLE}), then run 'aggregate'")


def mean_or_none(values):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 3) if values else None


def cmd_aggregate(args):
    review_paths = []
    for pattern in args.reviews:
        review_paths.extend(glob.glob(pattern))
    all_reviews = []
    for p in sorted(set(review_paths)):
        items = json.loads(Path(p).read_text(encoding="utf-8"))
        for it in items:
            it["_source_file"] = p
        all_reviews.extend(items)

    if not all_reviews:
        raise SystemExit("No review records found")

    unfilled = [r["question_id"] for r in all_reviews if r["answer_verdict"] is None]
    if unfilled:
        print(f"[evaluate_rag] WARNING: {len(unfilled)} question(s) have no answer_verdict yet: {unfilled}")

    answerable = [r for r in all_reviews if r["answerable"]]
    unanswerable = [r for r in all_reviews if not r["answerable"]]

    def mrr(rank_field, items):
        vals = [1 / r["retrieval"][rank_field] if r["retrieval"][rank_field] else 0 for r in items]
        return round(statistics.mean(vals), 3) if vals else None

    CORRECT_VERDICTS = {"correct_grounded", "correctly_refused"}

    def slice_summary(items):
        ans = [r for r in items if r["answerable"]]
        unans = [r for r in items if not r["answerable"]]
        graded = [r for r in items if r["answer_verdict"] is not None]
        n_correct = sum(1 for r in graded if r["answer_verdict"] in CORRECT_VERDICTS)
        return {
            "n": len(items),
            "answerable": len(ans),
            "unanswerable": len(unans),
            "graded": len(graded),
            "correct": n_correct,
            "accuracy": round(n_correct / len(graded), 3) if graded else None,
            "verdict_breakdown_answerable": {
                v: sum(1 for r in ans if r["answer_verdict"] == v) for v in VERDICTS_ANSWERABLE
            },
            "verdict_breakdown_unanswerable": {
                v: sum(1 for r in unans if r["answer_verdict"] == v) for v in VERDICTS_UNANSWERABLE
            },
        }

    by_model = {}
    for model in sorted({r.get("generation_model") or "unknown" for r in all_reviews}):
        by_model[model] = slice_summary([r for r in all_reviews if (r.get("generation_model") or "unknown") == model])

    by_language = {}
    for lang in sorted({r.get("question_language") or "unknown" for r in all_reviews}):
        by_language[lang] = slice_summary([r for r in all_reviews if (r.get("question_language") or "unknown") == lang])

    by_model_and_language = {}
    for model in by_model:
        for lang in by_language:
            key = f"{model} / {lang}"
            subset = [r for r in all_reviews
                      if (r.get("generation_model") or "unknown") == model
                      and (r.get("question_language") or "unknown") == lang]
            if subset:
                by_model_and_language[key] = slice_summary(subset)

    summary = {
        "total_questions": len(all_reviews),
        "answerable_questions": len(answerable),
        "unanswerable_questions": len(unanswerable),
        "retrieval": {
            "recall_at_10_initial": mean_or_none([1.0 if r["retrieval"]["initial_hit"] else 0.0 for r in answerable]),
            "recall_at_4_reranked": mean_or_none([1.0 if r["retrieval"]["reranked_hit"] else 0.0 for r in answerable]),
            "recall_at_4_sent": mean_or_none([1.0 if r["retrieval"]["sent_hit"] else 0.0 for r in answerable]),
            "mrr_initial": mrr("initial_rank_of_first_gold", answerable),
            "mrr_reranked": mrr("reranked_rank_of_first_gold", answerable),
            "mean_sent_precision": mean_or_none([r["retrieval"]["sent_precision"] for r in answerable]),
            "mean_sent_recall": mean_or_none([r["retrieval"]["sent_recall"] for r in answerable]),
        },
        "citation": {
            "mean_citation_precision": mean_or_none([r["citation"]["citation_precision"] for r in answerable]),
            "mean_citation_recall": mean_or_none([r["citation"]["citation_recall"] for r in answerable]),
            "no_citation_rate": mean_or_none([1.0 if r["citation"]["no_citation_found"] else 0.0 for r in all_reviews]),
        },
        "answer_verdict_breakdown_answerable": {
            v: sum(1 for r in answerable if r["answer_verdict"] == v) for v in VERDICTS_ANSWERABLE
        },
        "answer_verdict_breakdown_unanswerable": {
            v: sum(1 for r in unanswerable if r["answer_verdict"] == v) for v in VERDICTS_UNANSWERABLE
        },
        "rerank_status_breakdown": {
            status: sum(1 for r in all_reviews if r["rerank_status"] == status)
            for status in {r["rerank_status"] for r in all_reviews}
        },
        "by_model": by_model,
        "by_language": by_language,
        "by_model_and_language": by_model_and_language,
        "source_review_files": sorted({r["_source_file"] for r in all_reviews}),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# RQ5 evaluation — transcript-based RAG", "",
        f"Total questions: {summary['total_questions']} "
        f"({summary['answerable_questions']} answerable, {summary['unanswerable_questions']} unanswerable)", "",
        "## Retrieval", "",
        f"- Recall@10 (initial, pre-rerank): {summary['retrieval']['recall_at_10_initial']}",
        f"- Recall@4 (after rerank): {summary['retrieval']['recall_at_4_reranked']}",
        f"- Recall@4 (chunks actually sent to model): {summary['retrieval']['recall_at_4_sent']}",
        f"- MRR (initial): {summary['retrieval']['mrr_initial']}",
        f"- MRR (reranked): {summary['retrieval']['mrr_reranked']}",
        f"- Mean precision of sent chunks: {summary['retrieval']['mean_sent_precision']}",
        f"- Mean recall of sent chunks: {summary['retrieval']['mean_sent_recall']}", "",
        "## Citation / source attribution", "",
        f"- Mean citation precision: {summary['citation']['mean_citation_precision']}",
        f"- Mean citation recall: {summary['citation']['mean_citation_recall']}",
        f"- No-citation rate (all questions): {summary['citation']['no_citation_rate']}", "",
        "## Answer verdicts (human-graded)", "",
        "Answerable questions:",
    ]
    for v, n in summary["answer_verdict_breakdown_answerable"].items():
        lines.append(f"- {v}: {n}")
    lines.append("")
    lines.append("Unanswerable questions (refusal test):")
    for v, n in summary["answer_verdict_breakdown_unanswerable"].items():
        lines.append(f"- {v}: {n}")
    lines += ["", "## Rerank status", ""]
    for status, n in summary["rerank_status_breakdown"].items():
        lines.append(f"- {status}: {n}")

    lines += ["", "## Accuracy by generation model", "",
              "(\"correct\" = correct_grounded or correctly_refused, out of graded questions)", "",
              "| Model | Graded | Correct | Accuracy |", "|---|---:|---:|---:|"]
    for model, s in summary["by_model"].items():
        lines.append(f"| {model} | {s['graded']} | {s['correct']} | {s['accuracy']} |")

    lines += ["", "## Accuracy by question language", "",
              "| Language | Graded | Correct | Accuracy |", "|---|---:|---:|---:|"]
    for lang, s in summary["by_language"].items():
        lines.append(f"| {lang} | {s['graded']} | {s['correct']} | {s['accuracy']} |")

    lines += ["", "## Accuracy by model x language", "",
              "| Model | Language | Graded | Correct | Accuracy |", "|---|---|---:|---:|---:|"]
    for key, s in summary["by_model_and_language"].items():
        model, lang = key.split(" / ", 1)
        lines.append(f"| {model} | {lang} | {s['graded']} | {s['correct']} | {s['accuracy']} |")

    lines += ["", "## Source review files", ""]
    lines += [f"- {f}" for f in summary["source_review_files"]]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_path.with_suffix(".json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[evaluate_rag] wrote summary -> {out_path} (+ .json)")
    if unfilled:
        print(f"[evaluate_rag] NOTE: {len(unfilled)} question(s) were unscored (no answer_verdict) - re-run after filling them in")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score")
    s.add_argument("--gold", required=True)
    s.add_argument("--trace", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_score)

    a = sub.add_parser("aggregate")
    a.add_argument("--reviews", nargs="+", required=True)
    a.add_argument("--out", required=True)
    a.set_defaults(func=cmd_aggregate)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
