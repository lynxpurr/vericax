#!/usr/bin/env python3
"""P5 conformance: one real episode per new agent stack (spec/10 section 7).

The contract test is the same for every stack: the adapter launches, the
agent reaches the sandbox only through vericax-sh, the tier-1 verifier scores
the frozen artifacts, and the summary carries the three-way attribution.

Episodes are recorded with ``--kind test`` so a stack smoke run never moves a
capability mean. The model credential comes from the host environment
(``DEEPSEEK_API_KEY``, forwarded by each adapter's [container] env_from); it is
never printed or written by this script.

Usage:
    DEEPSEEK_API_KEY=... python3 tests/conformance_adapters.py
    DEEPSEEK_API_KEY=... python3 tests/conformance_adapters.py --adapter opencode
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERICAX = REPO / "bin" / "vericax"
DEFAULT_TASK = "cae--cli--calculix--task-0001"
DEFAULT_STACKS = ["opencode", "hermes", "openclaw"]


def run_one(adapter: str, task_id: str, time_limit: int) -> dict:
    started = time.monotonic()
    proc = subprocess.run(
        [str(VERICAX), "run", "--task", task_id, "--adapter", adapter,
         "--kind", "test", "--time-limit", str(time_limit)],
        cwd=str(REPO), capture_output=True, text=True, timeout=time_limit + 1800,
    )
    elapsed = time.monotonic() - started
    record: dict = {
        "adapter": adapter,
        "task_id": task_id,
        "rc": proc.returncode,
        "wall_seconds": round(elapsed, 1),
        "episode_id": None,
        "score": None,
        "scoring_basis": None,
        "error_category": None,
        "agent": None,
        "model": None,
        "cost": None,
        "challenge": None,
        "required_tool": None,
        "problems": [],
    }
    stdout = proc.stdout
    if proc.returncode != 0 and not stdout.strip().startswith("{"):
        record["problems"].append(f"vericax rc={proc.returncode}: {proc.stderr.strip()[-300:]}")
        return record
    try:
        block = json.loads(stdout[stdout.index("{"):])
        summary_path = REPO / "runs" / block["episode_id"] / "summary.json"
        record["episode_id"] = block["episode_id"]
        summary = json.loads(summary_path.read_text())
    except (ValueError, KeyError, OSError) as exc:
        record["problems"].append(f"cannot read summary: {exc}")
        return record
    record.update({
        "score": summary.get("score"),
        "scoring_basis": summary.get("scoring_basis"),
        "error_category": summary.get("error_category"),
        "agent": summary.get("agent"),
        "model": summary.get("model"),
        "cost": summary.get("cost"),
        "challenge": summary.get("challenge"),
        "required_tool": summary.get("required_tool"),
    })
    if summary.get("score") != 1.0:
        record["problems"].append(f"score={summary.get('score')} (need 1.0)")
    if summary.get("scoring_basis") != "native_evaluator":
        record["problems"].append(f"basis={summary.get('scoring_basis')}")
    if summary.get("error_category"):
        record["problems"].append(f"error_category={summary.get('error_category')}")
    if (summary.get("agent") or {}).get("name") != adapter:
        record["problems"].append(f"agent attribution={summary.get('agent')}")
    if not (summary.get("model") or {}).get("name"):
        record["problems"].append("missing model attribution")
    if not summary.get("image_sha256"):
        record["problems"].append("missing image_sha256")
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", default=DEFAULT_TASK)
    ap.add_argument("--adapter", action="append", default=[])
    ap.add_argument("--time-limit", type=int, default=1800)
    args = ap.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not set; the new adapters forward it from the host.",
              file=sys.stderr)
        return 2

    stacks = args.adapter or DEFAULT_STACKS
    rows = []
    for adapter in stacks:
        print(f"[conformance] {adapter}: {args.task}", flush=True)
        rows.append(run_one(adapter, args.task, args.time_limit))

    failed = [row for row in rows if row["problems"]]
    print("\nstack | score | basis | wall_s | agent | model | problems")
    print("---|---|---|---|---|---|---")
    for row in rows:
        agent = (row.get("agent") or {}).get("name")
        model = (row.get("model") or {}).get("name")
        print(f"{row['adapter']} | {row['score']} | {row['scoring_basis']} | "
              f"{row['wall_seconds']} | {agent} | {model} | "
              f"{'; '.join(row['problems']) or '-'}")
    print(f"\nconformance: {len(rows) - len(failed)}/{len(rows)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())