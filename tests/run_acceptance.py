#!/usr/bin/env python3
"""Phase 1 acceptance runner (spec/08 section 10, spec/09 section 10).

Covers the scripted-agent portion of the Phase 1 acceptance:
  1. contract purity   - no stack branching in lifecycle/freeze/score/record
  2. fake agent x3     - full episode (sandbox -> proxy -> freeze -> tier-1)
                         for tasks 0001/0002/0003
  3. cheat rejections  - empty delivery, fabricated summary, tampered summary
  4. background writer - tier-1 score identical with a VM-side writer alive

Real-stack runs (dsh x3, pi x1) go through the same `vericax run` entry and
are executed separately; this script stays model-free.

Usage: python3 tests/run_acceptance.py [--quick]  (--quick: task-0001 only)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERICAX = REPO / "bin" / "vericax"
TASKS = [
    "cae--cli--calculix--task-0001",
    "cae--cli--calculix--task-0002",
    "cae--cli--calculix--task-0003",
]

# P3c software-selection tasks: run on the merged image (set VERICAX_IMAGE to
# VeriCAx-merged.qcow2 when invoking the acceptance runner for these).
MERGED_TASKS = [
    "cae--cli--cross-solver--task-0002",
    "cae--cli--cross-solver--task-0003",
    "cae--cli--cross-solver--task-0004",
    "cae--cli--cross-solver--task-0005",
]
PURITY_TARGETS = [
    "vericax/lifecycle.py", "vericax/freeze.py", "vericax/scoring.py",
    "vericax/summary.py", "vericax/cli.py", "vericax/proxy.py",
    "vericax/agent_runner.py", "vericax/adapters.py", "vericax/batch.py",
]
PURITY_PATTERNS = [
    (r"\bstack\s*==", "stack equality"),
    (r"(?:adapter|stack)\.name\s*==", "adapter-name equality"),
    (r"==\s*['\"](dsh|pi|fake|opencode|hermes|openclaw)['\"]", "stack literal comparison"),
]

results: list[tuple[str, bool, str]] = []


def record(label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}", flush=True)


def gold_script(task_id: str) -> str:
    task_dir = REPO / "tasks" / task_id.replace("--", "/")
    spec = importlib.util.spec_from_file_location("audit_cases", task_dir / "audit_cases.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CASES[0][1]


def build_payload(mode: str, task_id: str) -> Path:
    """Assemble the harness-owned payload dir mounted at /vericax/payload."""
    payload = Path(tempfile.mkdtemp(prefix="vcax-payload-"))
    shutil.copy2(REPO / "tests" / "fake_agent.py", payload / "fake_agent.py")
    config: dict = {"mode": mode, "task_id": task_id}
    task_dir = REPO / "tasks" / task_id.replace("--", "/")
    task_json = json.loads((task_dir / f"{task_dir.name}.json").read_text())
    config["audit_token"] = (task_json.get("provenance") or {}).get("challenge")
    if mode in ("solve", "tamper", "background", "wrong_challenge"):
        (payload / "recipe.sh").write_text(gold_script(task_id))
    if mode == "summary_only":
        config["fabricate"] = {
            "path": "/home/user/Desktop/summary.txt",
            "line": "-0.01, -0.10",
        }
    if mode == "tamper":
        config["tamper"] = {
            "path": "/home/user/Desktop/summary.txt",
            "line": "-0.01, -0.10",
        }
    if mode == "background":
        config["noise_file"] = "/home/user/Desktop/_noise.txt"
    (payload / "config.json").write_text(json.dumps(config))
    return payload


def run_cli(args: list[str], timeout: int = 3600) -> tuple[int, str, str]:
    print(f"$ vericax {' '.join(args)}", flush=True)
    proc = subprocess.run([str(VERICAX), *args], capture_output=True, text=True,
                          timeout=timeout, cwd=str(REPO))
    if proc.stdout.strip():
        tail = proc.stdout.strip().splitlines()[-1]
        print(f"  -> rc={proc.returncode} {tail[:200]}", flush=True)
    return proc.returncode, proc.stdout, proc.stderr


def read_summary(stdout: str) -> dict:
    """The CLI prints a reduced block; the full record lives on disk."""
    start = stdout.index("{")
    block = json.loads(stdout[start:])
    return json.loads((REPO / "runs" / block["episode_id"] / "summary.json").read_text())


def check_contract_purity() -> None:
    violations = []
    for rel in PURITY_TARGETS:
        text = (REPO / rel).read_text()
        for line_no, line in enumerate(text.splitlines(), 1):
            for pattern, label in PURITY_PATTERNS:
                if re.search(pattern, line):
                    violations.append(f"{rel}:{line_no} {label}: {line.strip()[:80]}")
    record("contract purity (A1: no stack branching)", not violations,
           "; ".join(violations[:3]))


def run_fake(mode: str, task_id: str, expect: dict) -> dict:
    payload = build_payload(mode, task_id)
    try:
        rc, out, err = run_cli(["run", "--task", task_id, "--adapter", "fake",
                                "--kind", "test",
                                "--payload-dir", str(payload)])
        if rc != 0:
            record(f"fake[{mode}] {task_id.rsplit('--', 1)[-1]}", False,
                   f"vericax run rc={rc}: {err.strip()[-300:]}")
            return {}
        summary = read_summary(out)
        problems = []
        if expect.get("score") is not None and summary["score"] < expect["score"] - 1e-9:
            problems.append(f"score {summary['score']} < {expect['score']}")
        if expect.get("verdict_false") and summary["score"] != 0.0:
            problems.append(f"expected rejection, got score {summary['score']}")
        if summary["scoring_basis"] != "native_evaluator":
            problems.append(f"basis={summary['scoring_basis']}")
        if summary.get("error_category") not in (expect.get("error_category"), None):
            problems.append(f"category={summary['error_category']}")
        for field in ("image_sha256", "split_version"):
            if not summary.get(field):
                problems.append(f"missing {field}")
        manifest = json.loads((Path(summary["result_dir"]) / "artifacts" / "artifacts.json")
                              .read_text())
        if manifest["task_id"] != task_id or manifest["episode_id"] != summary["episode_id"]:
            problems.append("artifacts.json mismatch")
        if expect.get("expect_accept") and not all(a.get("present") for a in manifest["artifacts"]):
            problems.append("artifacts missing in manifest")
        record(f"fake[{mode}] {task_id.rsplit('--', 1)[-1]}", not problems,
               f"score={summary['score']} " + "; ".join(problems))
        return summary
    finally:
        shutil.rmtree(payload, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="task-0001 only")
    args = ap.parse_args()

    started = time.monotonic()
    check_contract_purity()

    tasks = TASKS[:1] if args.quick else TASKS
    for task_id in tasks:
        # task-0002 is quantified: the audited gold optimum scores 0.35 and the
        # audit's acceptance floor is ge 0.34 (audit_cases.py P1).
        floor = 0.34 if "0002" in task_id else 1.0
        run_fake("solve", task_id, {"score": floor, "expect_accept": True})

    t1 = TASKS[0]
    baseline = run_fake("solve", t1, {"score": 1.0, "expect_accept": True})
    run_fake("empty", t1, {"verdict_false": True, "error_category": None})
    run_fake("summary_only", t1, {"verdict_false": True})
    run_fake("tamper", t1, {"verdict_false": True})
    background = run_fake("background", t1, {"score": 1.0, "expect_accept": True})
    if baseline and background:
        record("background writer does not change the tier-1 verdict",
               background["score"] == baseline["score"],
               f"{background['score']} vs {baseline['score']}")

    elapsed = time.monotonic() - started
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n===== ACCEPTANCE: {len(results) - failed}/{len(results)} passed "
          f"({elapsed / 60:.1f} min) =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
