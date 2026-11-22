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

from . import batch as batch_mod
from . import config, lifecycle, scoring, validity


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

    p = sub.add_parser("audit", help="benchmark-validity gate: L0 reference self-check")
    p.add_argument("--task", required=True)
    p.add_argument("--group", default="reference", choices=["reference"])
    p.add_argument("--keep-vm", action="store_true")

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
    p.add_argument("--run-mode", default="rerun", choices=["rerun", "rescore"],
                   help="provenance label; a fresh agent run is always rerun")
    p.add_argument("--kind", default="capability", choices=["capability", "test", "debug"],
                   help="aggregate only capability episodes; tests are excluded by default")
    p.add_argument("--tree-version", default=None,
                   help="override the package-manifest tree version")
    p.add_argument("--image", default=None,
                   help="override the qcow2 path for this episode (batch image maps)")

    p = sub.add_parser("batch", help="run episodes in parallel (P4: default 2 VMs)")
    p.add_argument("--task", action="append", default=[],
                   help="task id (repeatable)")
    p.add_argument("--split", default=None,
                   help="split name under splits/ (mutually exclusive with --task)")
    p.add_argument("--adapter", required=True,
                   help="adapter name under adapters/ or a TOML path")
    p.add_argument("--runs", type=int, default=1,
                   help="runs per task (run_index 1..N, run_total=N)")
    p.add_argument("--parallel", type=int, default=2,
                   help="episodes in flight (P4 validated 2)")
    p.add_argument("--time-limit", type=int, default=None)
    p.add_argument("--payload-dir", type=Path, default=None,
                   help="payload dir applied to every task")
    p.add_argument("--payload-dir-map", action="append", default=[],
                   metavar="TASK=DIR", help="per-task payload dir (repeatable)")
    p.add_argument("--image", action="append", default=[], metavar="SNAPSHOT=PATH",
                   help="per-snapshot qcow2 override (repeatable)")
    p.add_argument("--no-score", action="store_true")
    p.add_argument("--run-mode", default="rerun", choices=["rerun", "rescore"])
    p.add_argument("--kind", default="capability", choices=["capability", "test", "debug"])
    p.add_argument("--tree-version", default=None)

    p = sub.add_parser("score", help="tier-1 score an existing episode's frozen artifacts")
    p.add_argument("--task", required=True)
    p.add_argument("--episode", default=None, help="episode dir with artifacts/")
    p.add_argument("--from-dir", type=Path, default=None,
                   help="score artifacts from an arbitrary directory instead "
                        "(gold-consistency regression)")
    p.add_argument("--image", default=None,
                   help="override the qcow2 path for the scoring instance")

    p = sub.add_parser("verify-overlay", help="prove per-episode disk isolation (spec/09 section 8)")
    p.add_argument("--snapshot", default="CalculiX-2.21")

    p = sub.add_parser("report", help="aggregate recorded episodes")
    p.add_argument("--runs-dir", type=Path, default=None)
    p.add_argument("--include-tests", action="store_true",
                   help="include test/debug episodes (cheat suite) in the table")

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

    if args.command == "audit":
        record = lifecycle.run_reference_selfcheck(args.task, keep_vm=args.keep_vm)
        print(json.dumps(record, indent=2))
        return 0 if record["passed"] else 1

    if args.command == "run":
        summary, _dir = lifecycle.run_episode(
            task_id=args.task,
            adapter_spec=args.adapter,
            run_index=args.run_index,
            run_total=args.run_total,
            time_limit=args.time_limit,
            payload_dir=args.payload_dir,
            do_score=not args.no_score,
            run_mode=args.run_mode,
            kind=args.kind,
            tree_version=args.tree_version,
            image_override=args.image,
        )
        print(json.dumps({k: summary[k] for k in
                          ("task_id", "episode_id", "score", "scoring_basis",
                           "error_category", "error", "run_mode", "tree_version",
                           "kind", "challenge", "required_tool")}, indent=2))
        return 0 if summary["scoring_basis"] != "infra" else 3

    if args.command == "batch":
        if args.split and args.task:
            parser.error("batch takes --split or --task, not both")
        task_ids = list(args.task) or (
            batch_mod.tasks_from_split(args.split) if args.split else [])
        payload_map = {}
        for item in args.payload_dir_map:
            if "=" not in item:
                parser.error(f"--payload-dir-map needs TASK=DIR, got {item!r}")
            task, raw = item.split("=", 1)
            payload_map[task] = Path(raw)
        image_map = {}
        for item in args.image:
            if "=" not in item:
                parser.error(f"--image needs SNAPSHOT=PATH, got {item!r}")
            snapshot, raw = item.split("=", 1)
            image_map[snapshot] = Path(raw)
        result = batch_mod.run_batch(
            task_ids=task_ids,
            adapter_spec=args.adapter,
            runs=args.runs,
            parallel=args.parallel,
            time_limit=args.time_limit,
            payload_dir=args.payload_dir,
            payload_dir_map=payload_map,
            do_score=not args.no_score,
            run_mode=args.run_mode,
            kind=args.kind,
            tree_version=args.tree_version,
            image_overrides=image_map,
        )
        return 0 if result["verdict"] == "pass" else 3

    if args.command == "score":
        if not args.episode and not args.from_dir:
            parser.error("score needs --episode or --from-dir")
        task_dir = lifecycle._task_dir(args.task)
        task_json = lifecycle._load_task(task_dir, args.task)
        artifacts = Path(args.from_dir) if args.from_dir else \
            Path(args.episode) / "artifacts"
        # Re-scoring must reproduce the episode's L6 binding: the token and
        # required tool are recorded in summary.json. A bare --from-dir is the
        # gold-consistency regression and keeps the audit token.
        challenge = required_tool = None
        if args.episode:
            summary_path = Path(args.episode) / "summary.json"
            if summary_path.is_file():
                episode_summary = json.loads(summary_path.read_text())
                challenge = episode_summary.get("challenge")
                required_tool = episode_summary.get("required_tool")
        result = scoring.run_scoring(
            task_dir=task_dir,
            evaluator_func=task_json.get("evaluator", {}).get("func", "exact_match"),
            frozen_artifacts_dir=artifacts,
            snapshot=task_json.get("snapshot", "CalculiX-2.21"),
            cache_dir=(Path(args.episode) / "scoring-cache") if args.episode
            else config.CACHE_DIR / "score-adhoc",
            challenge=challenge,
            required_tool=required_tool,
            image_override=args.image,
        )
        print(json.dumps({
            "verdict": result.verdict_text,
            "score": result.score,
            "infra": result.infra,
            "detail": result.detail,
            "pins_baked": result.pins_baked,
            "network_isolated": result.network_isolated,
            "verifier_sha256": result.verifier_sha256,
            "run_mode": "rescore",
            "tree_version": validity.tree_version(task_dir),
        }, indent=2))
        return 0 if not result.infra else 3

    if args.command == "verify-overlay":
        result = lifecycle.verify_overlay(args.snapshot)
        print(json.dumps(result, indent=2))
        return 0 if result["verdict"] == "pass" else 4

    if args.command == "report":
        lifecycle.report(args.runs_dir, include_tests=args.include_tests)
        return 0

    parser.error("unknown command")
    return 2


def _version() -> str:
    from . import __version__
    return f"vericax {__version__}"


if __name__ == "__main__":
    sys.exit(main())
