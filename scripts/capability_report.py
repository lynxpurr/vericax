#!/usr/bin/env python3
"""Aggregate capability episodes into the spec/11 report matrix.

Reads ``runs/ep-*/summary.json`` (or the episode list of one or more
``runs/batch-*/batch.json``) and joins each episode with its task package to get
the capability and solver. Emits a capability x solver x stack table plus a
per-task table.

    python3 scripts/capability_report.py --require-n 3
    python3 scripts/capability_report.py \
        --batch-dir runs/batch-20261122T... --batch-dir runs/batch-... \
        --require-n 3 --out docs/results/2026-11-22-b2.md

Exit codes: 0 ok; 1 no capability episodes or an n gate failed; 2 a task has
mixed tree_version values (or no episodes after filtering). ``tree_version`` is
the per-task manifest digest, so different tasks normally have different
values; only episodes of the *same* task must agree.

Only ``kind=capability`` episodes enter the means by default; ``kind=test`` and
``kind=debug`` are excluded unless ``--include-tests`` is given. ``infra``
scoring failures are counted and reported, but never scored.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = REPO / "runs"
DEFAULT_TASKS = REPO / "tasks"
NATIVE = "native_evaluator"


def task_registry(tasks_dir: Path) -> dict[str, dict]:
    """Map task id -> capability/snapshot from the task packages."""
    registry: dict[str, dict] = {}
    for path in sorted(Path(tasks_dir).glob("*/*/*/task-*/task-*.json")):
        data = json.loads(path.read_text())
        registry[data["id"]] = {
            "capability": data.get("capability", "?"),
            "snapshot": data.get("snapshot", "?"),
        }
    return registry


def episode_kind(row: dict) -> str:
    """Older unlabelled records are capability episodes (lifecycle.report)."""
    return row.get("kind") or "capability"


def load_rows(runs_dir: Path, batch_dirs: list[Path] | None = None):
    """Return (summary rows, batch metadata)."""
    wanted: set[str] | None = None
    batches: list[dict] = []
    if batch_dirs:
        wanted = set()
        for batch_dir in batch_dirs:
            data = json.loads((Path(batch_dir) / "batch.json").read_text())
            batches.append({
                "dir": str(batch_dir),
                "adapter": data.get("adapter"),
                "runs": data.get("runs"),
                "kind": data.get("kind"),
                "jobs": data.get("jobs"),
                "verdict": data.get("verdict"),
                "attempts": data.get("attempts"),
                "infra_attempts": data.get("infra_attempts"),
                "retried_jobs": data.get("retried_jobs"),
            })
            for episode in data.get("episodes", []):
                if episode.get("episode_id"):
                    wanted.add(episode["episode_id"])
    rows: list[dict] = []
    for path in sorted(Path(runs_dir).glob("ep-*/summary.json")):
        row = json.loads(path.read_text())
        if wanted is not None and row.get("episode_id") not in wanted:
            continue
        rows.append(row)
    return rows, {"batches": batches}


def reextract_cost(rows: list[dict], mode: str = "missing") -> dict:
    """Re-derive ``cost`` from the episodes' stored agent streams.

    The agent streams under ``logs/`` are the primary record and the summary's
    ``cost`` is derived from them, so an extractor that learned a new output
    shape (openclaw's envelope behind log lines) or a new field (cache reads)
    can be applied to episodes recorded before the change. This is a cost
    re-score: scores are not touched and no file is written. The caller states
    it in the report.

    ``mode="missing"`` fills only episodes without a cost record. ``mode="all"``
    re-derives every episode whose streams are still available and counts the
    ones whose recorded token totals differ, so a drift is reported rather than
    silently replaced. Returns ``{"filled", "refreshed", "changed"}``.
    """
    sys.path.insert(0, str(REPO))
    from vericax import adapters, lifecycle  # offline: no VM, docker or model

    counted = ("llm_calls", "prompt_tokens", "completion_tokens", "reasoning_tokens")
    counts = {"filled": 0, "refreshed": 0, "changed": 0}
    adapters_by_name: dict[str, object] = {}
    for row in rows:
        recorded = row.get("cost")
        if mode == "missing" and recorded is not None:
            continue
        name = row.get("adapter_name") or (row.get("agent") or {}).get("name")
        result_dir = row.get("result_dir")
        if not name or not result_dir or not Path(result_dir).is_dir():
            continue
        if name not in adapters_by_name:
            try:
                adapters_by_name[name] = adapters.load_adapter(
                    adapters.resolve_adapter(name))
            except SystemExit:
                adapters_by_name[name] = None
        adapter = adapters_by_name[name]
        if adapter is None:
            continue
        # Same order as the episode lifecycle: stdout first, then stderr.
        for stream in ("agent.stdout", "agent.stderr"):
            path = Path(result_dir) / "logs" / stream
            if not path.is_file():
                continue
            cost = lifecycle._extract_cost(adapter, path.read_text(errors="ignore"))
            if not cost:
                continue
            if recorded is None:
                counts["filled"] += 1
            else:
                counts["refreshed"] += 1
                if any(recorded.get(key) != cost.get(key) for key in counted):
                    counts["changed"] += 1
            row["cost"] = cost
            break
    return counts


def _usd(row: dict) -> float | None:
    cost = row.get("cost")
    return cost.get("usd_estimate") if isinstance(cost, dict) else None


def _tokens(row: dict, key: str) -> int:
    cost = row.get("cost")
    return int(cost.get(key) or 0) if isinstance(cost, dict) else 0


def _active(row: dict) -> float | None:
    """Active time lives in ``active_duration_seconds`` (older rows differ)."""
    value = row.get("active_duration_seconds")
    if value is None:
        value = row.get("active_time_seconds")
    return value


def _median(values) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


def _fmt(value, digits=3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def short_tree(tree: str | None) -> str:
    if not tree:
        return "-"
    if tree.startswith("sha256:"):
        return f"sha256:{tree[7:19]}…"
    return tree[:20]


def aggregate(rows: list[dict], registry: dict[str, dict], *,
              include_tests: bool = False,
              allow_mixed_tree: bool = False,
              require_n: int = 0) -> dict:
    """Group episodes into cells and per-task rows, and collect gate checks."""
    selected: list[tuple[dict, dict]] = []
    excluded = 0
    for row in rows:
        if not include_tests and episode_kind(row) != "capability":
            excluded += 1
            continue
        info = registry.get(row["task_id"],
                            {"capability": "?", "snapshot": "?"})
        selected.append((row, info))

    task_groups: dict[tuple, list[dict]] = defaultdict(list)
    cell_groups: dict[tuple, list[dict]] = defaultdict(list)
    for row, info in selected:
        agent = (row.get("agent") or {}).get("name", "?")
        model = (row.get("model") or {}).get("name") or "-"
        tree = row.get("tree_version") or "-"
        mode = row.get("run_mode") or "-"
        task_groups[(row["task_id"], agent, model, tree, mode)].append(row)
        cell_groups[(info["capability"], info["snapshot"], agent, model)].append(row)

    tasks = []
    for (task_id, agent, model, tree, mode), items in sorted(task_groups.items()):
        scored = [it["score"] for it in items
                  if it.get("scoring_basis") == NATIVE and it.get("score") is not None]
        n = len(scored)
        tasks.append({
            "task_id": task_id,
            "capability": registry.get(task_id, {}).get("capability", "?"),
            "solver": registry.get(task_id, {}).get("snapshot", "?"),
            "adapter": agent,
            "model": model,
            "tree_version": tree,
            "run_mode": mode,
            "episodes": len(items),
            "n": n,
            "mean": sum(scored) / n if n else None,
            "min": min(scored) if scored else None,
            "max": max(scored) if scored else None,
            "split_version": items[0].get("split_version") or "-",
        })

    cells = []
    for (capability, solver, agent, model), items in sorted(cell_groups.items()):
        scored = [it["score"] for it in items
                  if it.get("scoring_basis") == NATIVE and it.get("score") is not None]
        n = len(scored)
        infra = sum(1 for it in items if it.get("scoring_basis") == "infra")
        errors = Counter(it.get("error_category") for it in items
                         if it.get("error_category"))
        usd_values = [_usd(it) for it in items]
        usd_ok = bool(scored) and all(value is not None for value in usd_values)
        active = [_active(it) for it in items]
        prompt_tokens = sum(_tokens(it, "prompt_tokens") for it in items)
        completion_tokens = sum(_tokens(it, "completion_tokens") for it in items)
        tokens_total = prompt_tokens + completion_tokens
        # Cache reads sit outside token/task (prompt + completion); dsh and
        # openclaw report them separately, and they were the large majority of
        # what the gateway served in B2.
        cache_read = sum(_tokens(it, "cache_read_tokens") for it in items)
        cache_write = sum(_tokens(it, "cache_write_tokens") for it in items)
        versions = sorted({(it.get("agent") or {}).get("version")
                           for it in items if (it.get("agent") or {}).get("version")})
        cells.append({
            "capability": capability,
            "solver": solver,
            "adapter": agent,
            "agent_versions": versions,
            "model": model,
            "tree_versions": sorted({it.get("tree_version") or "-" for it in items}),
            "split_versions": sorted({it.get("split_version") or "-" for it in items}),
            "episodes": len(items),
            "n": n,
            "mean": sum(scored) / n if n else None,
            "min": min(scored) if scored else None,
            "max": max(scored) if scored else None,
            "infra": infra,
            "errors": dict(errors),
            "tokens_prompt": prompt_tokens,
            "tokens_completion": completion_tokens,
            "tokens_total": tokens_total,
            "tokens_per_task": (tokens_total / n) if n else None,
            "cache_read": cache_read,
            "cache_write": cache_write,
            "cache_read_per_task": (cache_read / n) if n else None,
            "usd_total": sum(usd_values) if usd_ok else None,
            "usd_per_task": (sum(usd_values) / n) if usd_ok and n else None,
            "active_median": _median(active),
            "active_coverage": f"{sum(1 for v in active if v is not None)}/{len(items)}",
        })

    checks: list[dict] = []
    trees_by_task: dict[str, set[str]] = defaultdict(set)
    unknown_tasks: set[str] = set()
    for row, _info in selected:
        tree = row.get("tree_version")
        if tree:
            trees_by_task[row["task_id"]].add(tree)
        else:
            unknown_tasks.add(row["task_id"])
    mixed = {task: sorted(trees) for task, trees in trees_by_task.items()
             if len(trees) > 1}
    if mixed:
        level = "warning" if allow_mixed_tree else "error"
        checks.append({"level": level,
                       "message": f"task(s) with mixed tree_version: {mixed}"})
    if unknown_tasks:
        checks.append({"level": "warning",
                       "message": f"{len(unknown_tasks)} task(s) have episodes "
                                  "without tree_version"})
    if require_n:
        short = [t for t in tasks if t["n"] < require_n]
        for task in short:
            checks.append({
                "level": "gate",
                "message": (f"{task['task_id']} / {task['adapter']} has n={task['n']} "
                            f"(need {require_n})"),
            })

    return {
        "summary_rows": len(rows),
        "selected": len(selected),
        "excluded": excluded,
        "trees": sorted({tree for trees in trees_by_task.values() for tree in trees}),
        "cells": cells,
        "tasks": tasks,
        "checks": checks,
    }


def _errors_text(errors: dict) -> str:
    if not errors:
        return "-"
    return ", ".join(f"{name}:{count}" for name, count in sorted(errors.items()))


def render_markdown(report: dict, meta: dict) -> str:
    lines = [
        "# Capability report",
        "",
        f"- summaries scanned: {report['summary_rows']}",
        f"- capability episodes: {report['selected']} "
        f"(excluded test/debug: {report['excluded']})",
        f"- task trees: {len(report['trees'])} distinct (one per task package)",
        "- cost basis: $/task only when every episode has usd_estimate; "
        "token/task is always reported (prompt + completion); cache-read/task "
        "is shown where the stack reports cache reads",
    ]
    reextract = meta.get("cost_reextract") or {}
    if reextract.get("filled"):
        lines.append(f"- cost re-extracted from the stored agent streams of "
                     f"{reextract['filled']} episode(s) that had none; scores unchanged")
    if reextract.get("refreshed"):
        lines.append(f"- cost re-derived from the stored agent streams of "
                     f"{reextract['refreshed']} episode(s) (`--reextract-cost all`); "
                     f"{reextract['changed']} differ from the recorded values")
    for batch in meta.get("batches", []):
        # retries=/infra= come from batches that retry infra jobs themselves;
        # older records only have jobs= and verdict=.
        retries = "" if batch.get("retried_jobs") is None else (
            f" retries={batch['retried_jobs']} infra_attempts={batch['infra_attempts']}")
        lines.append(
            f"- batch: `{batch['dir']}` adapter={batch['adapter']} "
            f"runs={batch['runs']} kind={batch['kind']} "
            f"jobs={batch['jobs']} verdict={batch['verdict']}{retries}")
    lines += [
        "",
        "## Capability × solver × stack",
        "",
        "| capability | solver | stack | model | n | mean | min | max | infra | tokens/task | cache-read/task | $/task | active med (s) | errors |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cell in report["cells"]:
        active = ("-" if cell["active_median"] is None
                  else f"{cell['active_median']:.0f}")
        tokens = ("-" if not cell["tokens_total"] or cell["tokens_per_task"] is None
                  else f"{cell['tokens_per_task']:.0f}")
        cached = ("-" if not cell["cache_read"] or cell["cache_read_per_task"] is None
                  else f"{cell['cache_read_per_task']:.0f}")
        lines.append(
            f"| {cell['capability']} | {cell['solver']} | {cell['adapter']} | "
            f"{cell['model']} | {cell['n']} | {_fmt(cell['mean'])} | "
            f"{_fmt(cell['min'])} | {_fmt(cell['max'])} | {cell['infra']} | "
            f"{tokens} | {cached} | {_fmt(cell['usd_per_task'], 4)} | "
            f"{active} ({cell['active_coverage']}) | "
            f"{_errors_text(cell['errors'])} |")
    lines += [
        "",
        "## Per task",
        "",
        "| task | capability | solver | stack | split | tree | n | mean | min | max |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for task in report["tasks"]:
        lines.append(
            f"| {task['task_id']} | {task['capability']} | {task['solver']} | "
            f"{task['adapter']} | {task['split_version']} | "
            f"{short_tree(task['tree_version'])} | "
            f"{task['n']} | {_fmt(task['mean'])} | "
            f"{_fmt(task['min'])} | {_fmt(task['max'])} |")
    if report["checks"]:
        lines += ["", "## Checks", ""]
        for check in report["checks"]:
            lines.append(f"- **{check['level']}**: {check['message']}")
    lines += ["", "Generated by `scripts/capability_report.py`.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--batch-dir", type=Path, action="append", default=[],
                        help="restrict to the episodes recorded in batch.json; repeatable")
    parser.add_argument("--include-tests", action="store_true",
                        help="include kind=test/debug episodes (not for publication)")
    parser.add_argument("--allow-mixed-tree", action="store_true",
                        help="warn instead of failing on mixed tree_version values")
    parser.add_argument("--require-n", type=int, default=0,
                        help="fail when a (task, stack) cell has fewer scored episodes")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    parser.add_argument("--reextract-cost", nargs="?", const="missing", default=None,
                        choices=["missing", "all"],
                        help="re-derive cost from each episode's stored agent streams: "
                             "'missing' fills only episodes without a cost record, 'all' "
                             "re-derives every episode (a cost re-score; scores and files "
                             "are untouched)")
    parser.add_argument("--out", type=Path, default=None,
                        help="write the report to this path")
    args = parser.parse_args()

    rows, meta = load_rows(args.runs_dir, args.batch_dir)
    if args.reextract_cost:
        meta["cost_reextract"] = reextract_cost(rows, mode=args.reextract_cost)
    registry = task_registry(args.tasks_dir)
    report = aggregate(rows, registry,
                       include_tests=args.include_tests,
                       allow_mixed_tree=args.allow_mixed_tree,
                       require_n=args.require_n)
    changed = meta.get("cost_reextract", {}).get("changed")
    if changed:
        report["checks"].append({
            "level": "warning",
            "message": (f"{changed} episode(s) have token totals that differ between the "
                        "recorded cost and the stored agent streams")})

    if not report["cells"]:
        print("capability_report: no capability episodes selected", file=sys.stderr)
        return 1

    if args.json:
        text = json.dumps({"meta": meta, **report}, indent=2) + "\n"
    else:
        text = render_markdown(report, meta)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"report -> {args.out}")
    else:
        print(text, end="")

    levels = {check["level"] for check in report["checks"]}
    if "error" in levels:
        return 2
    if "gate" in levels:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())