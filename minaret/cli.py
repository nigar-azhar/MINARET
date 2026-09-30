"""MINARET command line. Defaults come from minaret.yaml (see minaret/config.py); flags override.

Automatic pipeline (writes under <runs_dir>/recordings/[<series>/]<recording>/):
    python -m minaret.cli transcribe <path-or-url> --series-id S --recording-id R   # V0 + V1
    python -m minaret.cli validate-entities runs/recordings/S/R                     # E1 + V2

Human review hand-off (the reviewer application itself is not part of this release):
    python -m minaret.cli ingest-reviewed runs/recordings/S/R --v3 reviewed_v3.json --e2 reviewed_e2.json

Downstream (read <recordings_root>/<series>/<recording>/{v3,e2}.json):
    python -m minaret.cli kg build [--series TQ2005 ...]        # -> <runs_dir>/kg/instances/*.ttl
    python -m minaret.cli kg combine                            # -> <runs_dir>/kg/minaret_combined.ttl
    python -m minaret.cli rag index --series SKD2025 [--recording SKD_U001_S001_0001]
    python -m minaret.cli rag query --scope lecture --recording SKD_U001_S001_0001 --question "..."
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from minaret import config as config_mod

SERIES_BUILD_ORDER = ["TQ2005", "HAJJLT22", "SKD2025", "HUSN_AKHL"]


def _llm_flags(p: argparse.ArgumentParser, stage: str) -> None:
    flag = stage.replace("_", "-")
    p.add_argument(f"--{flag}-base-url", dest=f"{stage}_base_url")
    p.add_argument(f"--{flag}-model", dest=f"{stage}_model")
    p.add_argument(f"--{flag}-api-key", dest=f"{stage}_api_key",
                   help="Prefer the env var named in minaret.yaml; a key on the command line lands in shell history")
    p.add_argument(f"--{flag}-prompt", dest=f"{stage}_prompt", help="Alternate system-prompt file")


def _endpoint(cfg, args, stage):
    return cfg.llm(stage, base_url=getattr(args, f"{stage}_base_url"), model=getattr(args, f"{stage}_model"),
                   api_key=getattr(args, f"{stage}_api_key"), prompt=getattr(args, f"{stage}_prompt"))


def _pick(value, cfg, key, cast=None):
    if value is not None:
        return value
    v = cfg.get(key)
    return cast(v) if (cast and v is not None) else v


def _series_config_paths(cfg, args) -> list[Path]:
    """Explicit --series order, else the paper's build order followed by any other configs."""
    root = Path(args.series_configs) if args.series_configs else cfg.path("paths.series_configs")
    if args.series:
        return [root / f"{c}.json" for c in args.series]
    configs = {p.stem for p in root.glob("*.json") if not p.stem.endswith("_topic_proposals")}
    ordered = [c for c in SERIES_BUILD_ORDER if c in configs] + sorted(configs - set(SERIES_BUILD_ORDER))
    return [root / f"{c}.json" for c in ordered]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=None, help="Path to minaret.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("transcribe", help="V0 (+ V1 unless --skip-correction) for one audio source")
    t.add_argument("source", help="Local audio path or an HTTP(S) URL")
    t.add_argument("--series-id")
    t.add_argument("--recording-id")
    t.add_argument("--language", help="Force a language code, e.g. ur; default from minaret.yaml")
    t.add_argument("--output-root", type=Path, help="Default <runs_dir>/recordings")
    t.add_argument("--skip-correction", action="store_true")
    _llm_flags(t, "correction")

    v = sub.add_parser("validate-entities", help="Entity extraction + corpus validation on <dir>/v1.json -> e1.json, v2.json")
    v.add_argument("recording_dir", type=Path)
    v.add_argument("--quran-corpus-db")
    v.add_argument("--dua-corpus-db")
    v.add_argument("--alpha", type=float)
    v.add_argument("--tau", type=float)
    v.add_argument("--delta", type=float)
    _llm_flags(v, "extraction")

    r = sub.add_parser("ingest-reviewed", help="Validate externally-reviewed V3/E2 and place them in a recording dir")
    r.add_argument("recording_dir", type=Path)
    r.add_argument("--v3", type=Path, required=True)
    r.add_argument("--e2", type=Path, required=True)
    r.add_argument("--series-id")

    kg = sub.add_parser("kg", help="Knowledge-graph construction").add_subparsers(dest="kg_command", required=True)
    kb = kg.add_parser("build", help="Build per-series instance TTLs from v3.json + e2.json")
    kb.add_argument("--series", nargs="*", help="Series codes, in build order (default: all configs)")
    kb.add_argument("--series-configs", help="Directory of <SERIES>.json (default paths.series_configs)")
    kb.add_argument("--recordings-root", type=Path)
    kb.add_argument("--out", type=Path, help="Default <runs_dir>/kg")
    kb.add_argument("--keep-registry", action="store_true",
                    help="Extend an existing topic_registry.json instead of starting fresh")
    kc = kg.add_parser("combine", help="Schema + every instance TTL -> one combined TTL")
    kc.add_argument("--kg-dir", type=Path, help="Default <runs_dir>/kg")

    rag = sub.add_parser("rag", help="Retrieval-augmented QA").add_subparsers(dest="rag_command", required=True)
    ri = rag.add_parser("index", help="Build lecture indices (and the series index) for one series")
    ri.add_argument("--series", required=True, help="Series folder name under recordings_root, e.g. SKD2025")
    ri.add_argument("--recording", nargs="*", help="Default: every recording of the series")
    ri.add_argument("--recordings-root", type=Path)
    ri.add_argument("--index-root", type=Path, help="Default <runs_dir>/rag/index")
    rq = rag.add_parser("query", help="Answer questions over a lecture or series index")
    rq.add_argument("--scope", choices=["lecture", "series"], default="lecture")
    rq.add_argument("--recording")
    rq.add_argument("--series")
    rq.add_argument("--question")
    rq.add_argument("--question-id", default="Q1")
    rq.add_argument("--questions-file", type=Path, help="JSON list of {question_id, question}")
    rq.add_argument("--index-root", type=Path, help="Default <runs_dir>/rag/index; artifacts/rag/index for the paper's")
    rq.add_argument("--trace-root", type=Path, help="Default <runs_dir>/rag/traces")
    rq.add_argument("--max-tokens", type=int)
    rq.add_argument("--mock", action="store_true", help="Skip the LLM call (retrieval + rerank still run)")
    _llm_flags(rq, "rag_answer")

    args = parser.parse_args(argv)
    cfg = config_mod.load(args.config)
    runs_dir = cfg.path("paths.runs_dir", "runs")

    if args.command == "transcribe":
        from minaret.pipeline.run import run_v0_v1
        ep = None if args.skip_correction else _endpoint(cfg, args, "correction")
        directory = run_v0_v1(
            args.source, output_root=args.output_root or runs_dir / "recordings",
            recording_id=args.recording_id, series_id=args.series_id,
            language=_pick(args.language, cfg, "asr.language"),
            correction_base_url=ep.base_url if ep else "", correction_api_key=ep.api_key if ep else "",
            correction_model=ep.model if ep else "", correction_prompt=ep.prompt if ep else None,
            skip_correction=args.skip_correction,
        )
        print(f"Wrote output to {directory}")

    elif args.command == "validate-entities":
        from minaret.pipeline.run import run_e1_v2
        ep = _endpoint(cfg, args, "extraction")
        directory = run_e1_v2(
            args.recording_dir,
            quran_corpus_db=str(args.quran_corpus_db or cfg.path("corpora.quran_db")),
            dua_corpus_db=str(args.dua_corpus_db or cfg.path("corpora.dua_db")),
            extraction_base_url=ep.base_url, extraction_api_key=ep.api_key, extraction_model=ep.model,
            extraction_prompt=ep.prompt,
            alpha=_pick(args.alpha, cfg, "validation.alpha", float),
            tau=_pick(args.tau, cfg, "validation.tau", float),
            delta=_pick(args.delta, cfg, "validation.delta", float),
        )
        print(f"Wrote e1.json/v2.json to {directory}")

    elif args.command == "ingest-reviewed":
        from minaret.pipeline.ingest_reviewed import ingest
        result = ingest(args.recording_dir, v3_path=args.v3, e2_path=args.e2, series_id=args.series_id)
        for w in result.warnings:
            print(f"WARNING: {w}")
        print(f"Wrote {result.v3_path} and {result.e2_path}")

    elif args.command == "kg" and args.kg_command == "build":
        from minaret.downstream.kg.build import build_all
        builders = build_all(
            _series_config_paths(cfg, args),
            recordings_root=args.recordings_root or cfg.path("paths.recordings_root"),
            out_dir=args.out or runs_dir / "kg",
            quran_csv=cfg.path("corpora.quran_csv"), duas_csv=cfg.path("corpora.duas_csv"),
            hadith_dump=cfg.path("corpora.semantic_hadith_dump"), cache_dir=cfg.path("corpora.cache_dir"),
            fresh_registry=not args.keep_registry,
        )
        for b in builders:
            print(f"{b.series_code}: {len(b.g)} triples")

    elif args.command == "kg" and args.kg_command == "combine":
        from minaret.downstream.kg.combine import combine
        kg_dir = args.kg_dir or runs_dir / "kg"
        combine(kg_dir / "instances", kg_dir / "minaret_combined.ttl")

    elif args.command == "rag" and args.rag_command == "index":
        from minaret.downstream.rag.index import build_lecture_index, build_series_index
        root = (args.recordings_root or cfg.path("paths.recordings_root")) / args.series
        index_root = args.index_root or runs_dir / "rag" / "index"
        recordings = args.recording or sorted(p.name for p in root.iterdir() if (p / "v3.json").exists())
        for rec in recordings:
            build_lecture_index(root / rec / "v3.json", series=args.series, recording_id=rec,
                                index_root=index_root, target_seconds=float(cfg.get("rag.target_seconds", 30)))
        build_series_index(args.series, index_root=index_root)

    elif args.command == "rag" and args.rag_command == "query":
        from minaret.downstream.rag.query import DEFAULT_MAX_TOKENS, load_index, run_questions
        if args.scope == "lecture" and not args.recording:
            parser.error("--scope lecture requires --recording")
        if args.scope == "series" and not args.series:
            parser.error("--scope series requires --series")
        ep = None if args.mock else _endpoint(cfg, args, "rag_answer")
        if args.rag_answer_prompt:
            prompt_path = Path(args.rag_answer_prompt)
        elif ep and ep.prompt:
            prompt_path = ep.prompt
        else:
            prompt_path = cfg.path("llm.rag_answer.prompt") or config_mod.REPO_ROOT / "minaret/prompts/rag_answer_v1.txt"
        manifest, embeddings = load_index(args.index_root or runs_dir / "rag" / "index", scope=args.scope,
                                          recording_id=args.recording, series=args.series)
        if args.questions_file:
            items = json.loads(args.questions_file.read_text(encoding="utf-8"))
        elif args.question:
            items = [{"question_id": args.question_id, "question": args.question}]
        else:
            parser.error("pass --question or --questions-file")
        run_questions(
            items, scope=args.scope, scope_label=args.recording if args.scope == "lecture" else args.series,
            manifest=manifest, embeddings=embeddings, trace_root=args.trace_root or runs_dir / "rag" / "traces",
            endpoint=ep, system_prompt=Path(prompt_path).read_text(encoding="utf-8"), mock=args.mock,
            max_tokens=args.max_tokens or (ep.max_tokens if ep and ep.max_tokens else DEFAULT_MAX_TOKENS),
            top_k_initial=int(cfg.get("rag.top_k_initial", 10)), top_k_final=int(cfg.get("rag.top_k_final", 4)),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
