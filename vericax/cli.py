"""``vericax`` command line: check / prepare / smoke / run / score / report.

spec/03 section 3 defines the three standard entries (prepare, check, smoke);
spec/08 section 3 defines the episode lifecycle driven by ``run``. ``score``
re-runs tier-1 scoring on an existing frozen episode (used by the Phase 1
regression: gold artifacts must score the same as the tier-0 audit verdict).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, lifecycle, scoring


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vericax",
        description="VeriCAx eval harness (spec/08-09). "
                    "Run with the runtime venv python for VM-capable commands.")
    parser.add_argument("--version", action="version", version=_version())
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="offline task/package/adapter verification")
    p.add_argument("--task", required=True)
    p.add_argument("--adapter", default=None)

    p = sub.add_parser("prepare", help="resolve image + hash + verify package")
    p.add_argument("--task", required=True)

    p = sub.add_parser("smoke", help="boot VM, inject init, screenshot - no model")
    p.add_argument("--task", required=True)

    p = sub.add_parser("run", help="one full episode: prepare run freeze score record")
    p.add_argument("--task", required=True)
    p.add_argument("--adapter", required=True, help="adapter name under adapters/ or a TOML path")
    p.add_argument("--run-index", type=int, default=1)
    p.add_argument("--run-total", type=int, default=1)
    p.add_argument("--time-limit", type=int, default=None,
                   help="override the task's active_time_seconds for this run")
    p.add_argument("--payload-dir", type=Path, default=None,
                   help="harness-owned dir mounted read-only at /vericax/payload "
                        "(used by scripted agents)")
    p.add_argument("--no-score", action="store_true",
                   help="stop after freeze (diagnostics only; no score is recorded)")

    p = sub.add_parser("score", help="tier-1 score an existing episode's frozen artifacts")
    p.add_argument("--task", required=True)
    p.add_argument("--episode", required=True, help="episode dir with artifacts/")
    p.add_argument("--from-dir", type=Path, default=None,
                   help="score artifacts from an arbitrary directory instead "
                        "(gold-consistency regression)")

    p = sub.add_parser("verify-overlay", help="prove per-episode disk isolation (spec/09 section 8)")
    p.add_argument("--snapshot", default="CalculiX-2.21")

    p = sub.add_parser("report", help="aggregate recorded episodes")
    p.add_argument("--runs-dir", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "check":
        result = lifecycle.check_task(args.task, args.adapter)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "prepare":
        task_dir = lifecycle._task_dir(args.task)
        task_json = lifecycle._load_task(task_dir, args.task)
        lifecycle.check_task(args.task)
        image = config.image_path(task_json.get("snapshot", "CalculiX-2.21"))
        sha = config.image_sha256(image)
        print(json.dumps({"task": args.task, "image": str(image),
                          "image_sha256": sha}, indent=2))
        return 0

    if args.command == "smoke":
        print(json.dumps(lifecycle.smoke(args.task), indent=2))
        return 0

    if args.command == "run":
        summary, _dir = lifecycle.run_episode(
            task_id=args.task,
            adapter_spec=args.adapter,
            run_index=args.run_index,
            run_total=args.run_total,
            time_limit=args.time_limit,
            payload_dir=args.payload_dir,
            do_score=not args.no_score,
        )
        print(json.dumps({k: summary[k] for k in
                          ("task_id", "episode_id", "score", "scoring_basis",
                           "error_category", "error")}, indent=2))
        return 0 if summary["scoring_basis"] != "infra" else 3

    if args.command == "score":
        task_dir = lifecycle._task_dir(args.task)
        task_json = lifecycle._load_task(task_dir, args.task)
        artifacts = Path(args.from_dir) if args.from_dir else \
            Path(args.episode) / "artifacts"
        result = scoring.run_scoring(
            task_dir=task_dir,
            evaluator_func=task_json.get("evaluator", {}).get("func", "exact_match"),
            frozen_artifacts_dir=artifacts,
            snapshot=task_json.get("snapshot", "CalculiX-2.21"),
            cache_dir=(Path(args.episode) / "scoring-cache") if args.episode
            else config.CACHE_DIR / "score-adhoc",
        )
        print(json.dumps({
            "verdict": result.verdict_text,
            "score": result.score,
            "infra": result.infra,
            "detail": result.detail,
            "pins_baked": result.pins_baked,
            "network_isolated": result.network_isolated,
            "verifier_sha256": result.verifier_sha256,
        }, indent=2))
        return 0 if not result.infra else 3

    if args.command == "verify-overlay":
        result = lifecycle.verify_overlay(args.snapshot)
        print(json.dumps(result, indent=2))
        return 0 if result["verdict"] == "pass" else 4

    if args.command == "report":
        lifecycle.report(args.runs_dir)
        return 0

    parser.error("unknown command")
    return 2


def _version() -> str:
    from . import __version__
    return f"vericax {__version__}"


if __name__ == "__main__":
    sys.exit(main())
