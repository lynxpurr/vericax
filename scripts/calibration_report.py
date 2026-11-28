#!/usr/bin/env python3
"""Per-episode table and task x stack matrix for a calibration run.

    python3 scripts/calibration_report.py --worktree <repo> <batch.json> [<batch.json> ...]

Reads the batch records written by ``vericax batch`` and prints every
episode with its scoring basis, score, active time, tokens (prompt +
completion, the published basis; reasoning and cache reads are listed
separately), the verifier's first debug line for a zero, and the task x
stack matrix over the native episodes (n, mean, range, infra attempts).

``--worktree`` names the checkout whose ``tasks/`` holds the current
packages. An episode whose ``tree_version`` is not the task's current
manifest is then listed as excluded and left out of the matrix: a task that
changed after the run (a verifier fix, an instruction edit) no longer
describes those episodes. Without ``--worktree`` every episode counts.

Offline and read-only. It prints harness records only: no credentials and no
agent output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

STACK_ORDER = ["dsh", "opencode-bailian", "openclaw-bailian"]
NATIVE = "native_evaluator"
PANIC = re.compile(r"kernel panic|attempted to kill init|segfault at", re.I)
STAMP = re.compile(r"\[ +(\d+\.\d+)\]")


def load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def current_trees(worktree: Path) -> dict:
    """task id -> tree version (the manifest digest) of the package in ``worktree``."""
    trees = {}
    for manifest in sorted(worktree.glob("tasks/*/*/*/task-*/resources.sha256")):
        task_id = "--".join(manifest.parent.relative_to(worktree / "tasks").parts)
        trees[task_id] = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    return trees


def console_state(result_dir: Path) -> str:
    """``clean (<last kernel stamp> s)`` or ``PANIC: <first line>``."""
    path = result_dir / "logs" / "vm-console.log"
    if not path.is_file():
        return "no console"
    text = path.read_text(errors="ignore")
    hits = [line.strip()[:90] for line in text.splitlines() if PANIC.search(line)]
    if hits:
        return "PANIC: " + hits[0]
    stamps = STAMP.findall(text)
    return f"clean ({stamps[-1].split('.')[0] if stamps else '?'} s)"


def verifier_reason(result_dir: Path) -> str:
    """The verifier's first debug line: why a delivery was rejected."""
    path = result_dir / "logs" / "evaluator.stderr"
    if not path.is_file():
        return ""
    for line in path.read_text(errors="ignore").splitlines():
        if "debug:" in line:
            return line.split("debug:", 1)[1].strip()[:95]
    return ""


def episode_row(batch: dict, record: dict, batch_name: str) -> dict:
    summary = load(Path(record["result_dir"]) / "summary.json") if record.get("result_dir") else {}
    cost = summary.get("cost") or {}

    def name(field: str) -> str | None:
        value = summary.get(field)
        return value.get("name") if isinstance(value, dict) else value

    result_dir = Path(record["result_dir"]) if record.get("result_dir") else None
    return {
        "adapter": name("adapter") or batch.get("adapter", "?"),
        "model": name("model"),
        "task": record["task_id"],
        "run": record.get("run_index"),
        "attempt": record.get("attempt"),
        "basis": record.get("scoring_basis"),
        "score": record.get("score"),
        "category": record.get("error_category") or "",
        "active": summary.get("active_duration_seconds"),
        "prompt_completion": (cost.get("prompt_tokens") or 0) + (cost.get("completion_tokens") or 0),
        "reasoning": cost.get("reasoning_tokens") or 0,
        "cache_read": cost.get("cache_read_tokens") or 0,
        "calls": cost.get("llm_calls"),
        "tree": (summary.get("tree_version") or "")[7:19],
        "image": (summary.get("image_sha256") or "")[:12],
        "console": console_state(result_dir) if result_dir else "",
        "why": verifier_reason(result_dir) if result_dir else "",
        "batch": batch_name,
    }


def collect(batch_paths: list[Path], trees: dict) -> tuple[list[dict], list[dict]]:
    """Rows of every episode, split into those on the current tree and the rest."""
    rows, excluded = [], []
    for path in batch_paths:
        batch = load(path)
        if not batch:
            print(f"skip {path}: no batch record", file=sys.stderr)
            continue
        for record in batch.get("episodes", []):
            row = episode_row(batch, record, path.parent.name)
            if trees and row["tree"] != trees.get(row["task"], "")[7:19]:
                excluded.append(row)
            else:
                rows.append(row)
    return rows, excluded


def median(values: list) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else float("nan")


def cell_text(cell: list[dict]) -> str:
    native = [r for r in cell if r["basis"] == NATIVE]
    infra = len(cell) - len(native)
    if not cell:
        return "-"
    if not native:
        return f"n=0 infra={infra}"
    low, high = min(r["score"] for r in native), max(r["score"] for r in native)
    mean = sum(r["score"] for r in native) / len(native)
    return f"n={len(native)} mean={mean:.3f} [{low:.2f}-{high:.2f}] infra={infra}"


def render(rows: list[dict], excluded: list[dict]) -> str:
    out = []
    if excluded:
        out.append(f"== excluded: {len(excluded)} episode(s) not on the task's current tree ==")
        for r in excluded:
            out.append(f"{r['adapter']:16s} {r['task']} run {r['run']} try {r['attempt']} "
                       f"tree {r['tree']} score {r['score']:.3f} ({r['batch']})")
        out.append("")
    stacks = [s for s in STACK_ORDER if any(r["adapter"] == s for r in rows)]
    stacks += sorted({r["adapter"] for r in rows} - set(stacks))
    tasks = sorted({r["task"] for r in rows})

    out.append("== episodes ==")
    for task in tasks:
        for stack in stacks:
            for r in sorted((r for r in rows if r["task"] == task and r["adapter"] == stack),
                            key=lambda r: (r["run"] or 0, r["attempt"] or 0)):
                if r["basis"] == NATIVE and (r["score"] or 0) < 1.0:
                    out.append(f"{'':16s} {'':10s} verifier: {r['why']}")
                active = f"{r['active']:.0f}" if isinstance(r["active"], (int, float)) else "-"
                out.append(f"{stack:16s} {task.rsplit('--', 1)[-1]} run {r['run']} try {r['attempt']} | "
                           f"{r['basis'] or '-':16s} score {r['score']:.3f} | active {active:>5} s | "
                           f"{r['prompt_completion']:>8} tok (cache {r['cache_read']:>8}) calls {r['calls']} | "
                           f"{r['category'] or '-'} | console {r['console']}")

    out.append("")
    out.append("== task x stack matrix (native episodes only; infra attempts excluded) ==")
    width = max([len(cell_text([r for r in rows if r["task"] == t and r["adapter"] == s]))
                 for t in tasks for s in stacks] + [34]) if rows else 34
    out.append(f"{'task':28s} " + " ".join(f"{s:>{width}s}" for s in stacks))
    for task in tasks:
        cells = [cell_text([r for r in rows if r["task"] == task and r["adapter"] == s]) for s in stacks]
        out.append(f"{task:28s} " + " ".join(f"{c:>{width}s}" for c in cells))

    out.append("")
    out.append("== totals per stack ==")
    for stack in stacks:
        cell = [r for r in rows if r["adapter"] == stack]
        native = [r for r in cell if r["basis"] == NATIVE]
        actives = [r["active"] for r in native if isinstance(r["active"], (int, float))]
        out.append(f"{stack:16s} attempts {len(cell):2d} native {len(native):2d} infra {len(cell) - len(native):2d} | "
                   f"prompt+completion {sum(r['prompt_completion'] for r in cell):>9} "
                   f"reasoning {sum(r['reasoning'] for r in cell):>8} "
                   f"cache-read {sum(r['cache_read'] for r in cell):>9} | "
                   f"native active median {median(actives):.0f} s | model {cell[0]['model']}")

    out.append("")
    out.append("== fingerprints ==")
    for task in tasks:
        cell = [r for r in rows if r["task"] == task]
        out.append(f"{task:28s} tree {sorted({r['tree'] for r in cell})} "
                   f"image {sorted({r['image'] for r in cell})}")
    panics = [r for r in rows if r["console"].startswith("PANIC")]
    out.append("")
    out.append(f"episodes with a guest panic in the console: {len(panics)} of {len(rows)}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worktree", type=Path, help="checkout whose tasks/ hold the current packages")
    ap.add_argument("batch", nargs="+", type=Path, help="batch.json files")
    args = ap.parse_args()
    trees = current_trees(args.worktree) if args.worktree else {}
    rows, excluded = collect(args.batch, trees)
    if not rows:
        print("no episodes on the current tree", file=sys.stderr)
        return 1
    print(render(rows, excluded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
