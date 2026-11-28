#!/usr/bin/env python3
"""Re-audit every task package against the configured images.

The default-image switch (spec/10 section 3) changes which qcow2 each
``snapshot`` resolves to. Pinned references are image-bound, so every package
must be re-audited in this order:

    audit_task.py --repeat 10   # regenerate pins + audit.md
    pack_task.py                # write the new manifest (L0 gate still holds)
    vericax audit               # L0 on the new image, refresh tree_version
    pack_task.py --check        # manifest must match

A package that does not carry a passing L0 record cannot be packed first: the
pack gate refuses, and ``vericax audit`` accepts a package that has no
manifest, or whose record did not pass. There the first L0 runs before the
pack, and a second L0 after it gives the record the final ``tree_version``:

    new package, no manifest:        audit, L0, pack, L0, check
    manifest, record did not pass:   L0, audit, pack, L0, check

Run with the runtime venv python and ``VERICAX_IMAGE_DIR`` pointing at a
directory that contains ``CalculiX-2.21.qcow2``, ``FEniCS.qcow2`` and
``VeriCAx-merged.qcow2``. Two tasks are in flight (one VM each); each task has
its own audit cache directory.

    VERICAX_IMAGE_DIR=~/vericax-image-build/suite \
      <runtime-venv>/bin/python scripts/audit_suite.py [--parallel 2]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERICAX = REPO / "bin" / "vericax"
sys.path.insert(0, str(REPO))

from vericax import validity  # noqa: E402


def task_dir_for(task_id: str) -> Path:
    domain, iface, software, task = task_id.split("--")
    return REPO / "tasks" / domain / iface / software / task


def steps_for(task_id: str, repeat: int, has_manifest: bool, l0_passed: bool) -> list:
    """The pipeline of one package, in the order its gates allow (see the module docstring)."""
    audit = ("audit", [sys.executable, str(REPO / "scripts/audit_task.py"),
                       "--task", task_id, "--repeat", str(repeat)])
    pack = ("pack", [sys.executable, str(REPO / "scripts/pack_task.py"), "--task", task_id])
    l0 = ("l0", [str(VERICAX), "audit", "--task", task_id])
    l0_first = ("l0_first", [str(VERICAX), "audit", "--task", task_id])
    check = ("check", [sys.executable, str(REPO / "scripts/pack_task.py"),
                       "--task", task_id, "--check"])
    if l0_passed:
        return [audit, pack, l0, check]
    if has_manifest:
        # `vericax audit` refuses a stale manifest, so L0 has to see the
        # package as it was packed, before the audit rewrites its records.
        return [l0_first, audit, pack, l0, check]
    return [audit, l0_first, pack, l0, check]


def task_ids() -> list[str]:
    ids = []
    for path in sorted((REPO / "tasks").glob("*/*/*/task-*")):
        if not path.is_dir():
            continue
        rel = path.relative_to(REPO / "tasks").as_posix()
        ids.append(rel.replace("/", "--"))
    return ids


def run_step(argv: list[str], log, env: dict) -> tuple[bool, str]:
    proc = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True, env=env)
    log.write(f"$ {' '.join(argv)}\n")
    if proc.stdout:
        log.write(proc.stdout)
    if proc.stderr:
        log.write(proc.stderr)
    log.flush()
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip().splitlines()[-1] if (
        proc.stdout or proc.stderr) else ""


def one(task_id: str, out_dir: Path, repeat: int, env: dict) -> dict:
    started = time.monotonic()
    record = {"task_id": task_id, "steps": {}, "ok": False, "seconds": None}
    log_path = out_dir / f"{task_id}.log"
    with log_path.open("w") as log:
        task_dir = task_dir_for(task_id)
        steps = steps_for(
            task_id, repeat,
            has_manifest=(task_dir / "resources.sha256").is_file(),
            l0_passed=validity.reference_selfcheck_state(
                validity.load_reference_selfcheck(task_dir)) == "pass")
        for name, argv in steps:
            ok, tail = run_step(argv, log, env)
            record["steps"][name] = {"ok": ok, "tail": tail[-200:]}
            if not ok:
                break
        record["ok"] = all(step["ok"] for step in record["steps"].values()) and \
            len(record["steps"]) == len(steps)
    record["seconds"] = round(time.monotonic() - started, 1)
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", action="append", default=[], help="limit to task ids")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--repeat", type=int, default=10)
    args = ap.parse_args()

    if not os.environ.get("VERICAX_IMAGE_DIR"):
        print("VERICAX_IMAGE_DIR must point at the directory with the three "
              "self-built qcow2 files", file=sys.stderr)
        return 2
    ids = args.task or task_ids()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_dir = REPO / "runs" / f"suite-audit-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)

    print(f"audit_suite: {len(ids)} task(s), parallel={args.parallel}, repeat={args.repeat}")
    print(f"audit_suite: images {env['VERICAX_IMAGE_DIR']}")
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futures = {pool.submit(one, task, out_dir, args.repeat, env): task for task in ids}
        for future in as_completed(futures):
            record = future.result()
            results.append(record)
            status = "PASS" if record["ok"] else "FAIL"
            print(f"[{status}] {record['task_id']} ({record['seconds']}s)", flush=True)

    results.sort(key=lambda row: row["task_id"])
    failed = [row for row in results if not row["ok"]]
    (out_dir / "suite-audit.json").write_text(json.dumps({
        "image_dir": env["VERICAX_IMAGE_DIR"],
        "repeat": args.repeat,
        "parallel": args.parallel,
        "verdict": "pass" if not failed else "FAIL",
        "tasks": results,
    }, indent=2) + "\n")
    print(f"\naudit_suite: {len(results) - len(failed)}/{len(results)} passed -> "
          f"{out_dir / 'suite-audit.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())