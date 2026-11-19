#!/usr/bin/env python3
"""Phase 2 precondition soak: two sandbox VMs at the same time (D3, spec/09 §8).

Phase 1 ran serially on one VM. Before any parallel scheduling, the runtime's
two-VM behavior must be observed on this host: port allocation under the
provider lock, independent readiness, independent disk state, clean shutdown.

Each VM gets its own cache dir and the pilot task's init files, then proves
the control plane answers and the guest network isolation applies. Results
are printed as one JSON document; exit code 1 if either VM failed.

Usage (runtime venv python):
    <runtime-venv>/bin/python tests/soak_two_vms.py [--vms 2] [--task <task id>]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from vericax import lifecycle  # noqa: E402
from vericax.sandbox_vm import SandboxVM  # noqa: E402


def _one_vm(index: int, task_id: str, task_dir: Path, task_json: dict, snapshot: str,
            out: dict) -> None:
    started = time.monotonic()
    vm = SandboxVM(snapshot, cache_dir=REPO / "runs" / f"soak-{index}" / "cache")
    record: dict = {"index": index}
    try:
        vm.boot(lifecycle._vm_task_config(task_dir, task_json))
        record["boot_seconds"] = round(time.monotonic() - started, 1)
        record["healthy"] = vm.wait_healthy()
        isolated, detail = vm.isolate_network()
        record["network_isolated"] = isolated
        record["network_isolation_detail"] = detail
        probe = vm.bash("cat /home/user/Desktop/uniform_beam.inp | head -1", timeout=60)
        record["init_file_probe"] = probe["output"].strip()[:60]
        record["probe_ok"] = probe["returncode"] == 0 and "Heading" in probe["output"]
    except Exception as exc:  # noqa: BLE001 - soak failures are data
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        closed = time.monotonic()
        vm.close()
        record["close_seconds"] = round(time.monotonic() - closed, 2)
        record["total_seconds"] = round(time.monotonic() - started, 1)
        out[index] = record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vms", type=int, default=2)
    ap.add_argument("--task", default="cae--cli--calculix--task-0001")
    args = ap.parse_args()

    task_dir = lifecycle._task_dir(args.task)
    task_json = lifecycle._load_task(task_dir, args.task)
    snapshot = task_json.get("snapshot", "CalculiX-2.21")

    results: dict[int, dict] = {}
    threads = [
        threading.Thread(target=_one_vm, args=(i, args.task, task_dir, task_json,
                                               snapshot, results))
        for i in range(1, args.vms + 1)
    ]
    wall_started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = round(time.monotonic() - wall_started, 1)

    ordered = [results[i] for i in sorted(results)]
    ok = all(rec.get("healthy") and rec.get("probe_ok") and not rec.get("error")
             for rec in ordered)
    print(json.dumps({
        "vms": args.vms,
        "task": args.task,
        "wall_seconds": wall,
        "verdict": "pass" if ok else "FAIL",
        "results": ordered,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())