#!/usr/bin/env python3
"""Recompute every RQ result from an artifact tree.

    python evaluation/run_all.py                    # the paper's released artifacts/
    python evaluation/run_all.py --artifacts runs   # your own pipeline outputs, same layout

RQ3 reads evaluation/rq3_review_effort/review_effort.csv (review time is not a pipeline output).
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = [
    ("RQ1 transcript improvement", "rq1_transcripts/compute.py", True),
    ("RQ1 residual error taxonomy", "rq1_transcripts/classify_errors.py", True),
    ("RQ1 V2-vs-V3 diff listings", "rq1_transcripts/export_diffs.py", True),
    ("RQ2 entity accuracy", "rq2_entities/compute.py", True),
    ("RQ3 review effort", "rq3_review_effort/compute.py", False),
    ("RQ4 KG statistics + competency questions", "rq4_kg/compute.py", True),
    ("RQ5 RAG retrieval + answer quality", "rq5_rag/compute.py", True),
    ("ASR model selection", "asr_model_selection/compute.py", True),
]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--artifacts", type=Path, default=None)
    args = p.parse_args()
    failed = []
    for label, script, takes_artifacts in STEPS:
        print(f"\n=== {label} ===", flush=True)
        cmd = [sys.executable, str(HERE / script)]
        if takes_artifacts and args.artifacts:
            cmd += ["--artifacts", str(args.artifacts.resolve())]
        if subprocess.run(cmd).returncode != 0:
            failed.append(label)
    print("\nAll RQs recomputed." if not failed else f"\nFAILED: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
