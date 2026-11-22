"""Parallel episode scheduling (P4, spec/09 section 11).

Two episodes run concurrently, each with its own sandbox overlay, agent
container, proxy socket, cache directory and scoring instance. The lifecycle
closes the sandbox before scoring (E5), so N parallel episodes hold at most N
VMs at any moment; the acceptance scope validated N=2.

The scheduler is deliberately a thin thread pool over ``run_episode``: every
per-episode artifact already lives under ``runs/<episode>/``, so the only
shared state is the image-hash cache (made atomic in config.py) and stdout.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import config, lifecycle

MAX_VALIDATED_PARALLEL = 2


def tasks_from_split(split: str) -> list[str]:
    """Read ``splits/<version>.txt`` (one task id per line, ``#`` comments)."""
    path = config.REPO / "splits" / f"{split}.txt"
    if not path.is_file():
        raise SystemExit(f"split not found: {path}")
    tasks = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            tasks.append(line)
    return tasks


def _snapshot_for(task_id: str) -> str:
    task_dir = lifecycle._task_dir(task_id)
    return lifecycle._load_task(task_dir, task_id).get("snapshot", "CalculiX-2.21")


def run_batch(
    task_ids: list[str],
    adapter_spec: str,
    *,
    runs: int = 1,
    parallel: int = 2,
    time_limit: int | None = None,
    payload_dir: Path | None = None,
    payload_dir_map: dict[str, Path] | None = None,
    do_score: bool = True,
    run_mode: str = "rerun",
    kind: str = "capability",
    tree_version: str | None = None,
    image_overrides: dict[str, Path] | None = None,
) -> dict:
    """Run every (task, run_index) job with at most ``parallel`` in flight."""
    if not task_ids:
        raise SystemExit("batch needs at least one task (--task or --split)")
    if runs < 1:
        raise SystemExit("--runs must be >= 1")
    if parallel < 1:
        raise SystemExit("--parallel must be >= 1")
    if parallel > MAX_VALIDATED_PARALLEL:
        print(f"batch: WARNING - P4 validated {MAX_VALIDATED_PARALLEL} parallel "
              f"episodes; --parallel {parallel} increases VM load and is unverified")

    image_overrides = dict(image_overrides or {})
    payload_dir_map = dict(payload_dir_map or {})
    snapshots = {task: _snapshot_for(task) for task in task_ids}
    if len(set(snapshots.values())) > 1 and not image_overrides:
        if os.environ.get("VERICAX_IMAGE"):
            raise SystemExit(
                "batch spans multiple snapshots but VERICAX_IMAGE overrides all of "
                "them; pass --image SNAPSHOT=PATH for each instead")

    started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    batch_dir = config.REPO / "runs" / f"batch-{stamp}-{secrets.token_hex(2)}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    print_lock = threading.Lock()
    records: list[dict] = []

    def one(task_id: str, run_index: int) -> dict:
        started_job = time.monotonic()
        record: dict = {
            "task_id": task_id,
            "run_index": run_index,
            "snapshot": snapshots[task_id],
            "episode_id": None,
            "score": None,
            "scoring_basis": None,
            "error_category": None,
            "error": None,
            "wall_seconds": None,
        }
        try:
            summary, episode_dir = lifecycle.run_episode(
                task_id=task_id,
                adapter_spec=adapter_spec,
                run_index=run_index,
                run_total=runs,
                time_limit=time_limit,
                payload_dir=payload_dir_map.get(task_id, payload_dir),
                do_score=do_score,
                run_mode=run_mode,
                kind=kind,
                tree_version=tree_version,
                image_override=image_overrides.get(snapshots[task_id]),
            )
            record.update({
                "episode_id": summary["episode_id"],
                "score": summary["score"],
                "scoring_basis": summary["scoring_basis"],
                "error_category": summary.get("error_category"),
                "error": summary.get("error"),
                "result_dir": summary.get("result_dir"),
            })
        except BaseException as exc:  # noqa: BLE001 - one job must not sink the batch
            record["error_category"] = "infra_incomplete"
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["wall_seconds"] = round(time.monotonic() - started_job, 3)
        with print_lock:
            print(f"batch: {task_id} run {run_index}/{runs} -> "
                  f"score={record['score']} basis={record['scoring_basis']} "
                  f"error={record['error']}", flush=True)
        return record

    jobs = [(task, index) for task in task_ids for index in range(1, runs + 1)]
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(one, task, index) for task, index in jobs]
        for future in as_completed(futures):
            records.append(future.result())

    wall = round(time.monotonic() - started, 1)
    records.sort(key=lambda row: (row["task_id"], row["run_index"]))
    infra = [row for row in records if row["scoring_basis"] == "infra"]
    payload = {
        "started_at": stamp,
        "adapter": adapter_spec,
        "parallel": parallel,
        "runs": runs,
        "kind": kind,
        "wall_seconds": wall,
        "jobs": len(records),
        "infra_failures": len(infra),
        "verdict": "pass" if not infra else "FAIL",
        "episodes": records,
    }
    (batch_dir / "batch.json").write_text(json.dumps(payload, indent=2) + "\n")

    print("\nbatch summary")
    print("task | run | episode | score | basis | error | wall_s")
    print("---|---|---|---|---|---|---")
    for row in records:
        print(f"{row['task_id']} | {row['run_index']} | {row['episode_id'] or '-'} | "
              f"{row['score'] if row['score'] is not None else '-'} | "
              f"{row['scoring_basis'] or '-'} | {row['error'] or '-'} | "
              f"{row['wall_seconds']}")
    print(f"\nbatch: {len(records)} episode(s), parallel={parallel}, wall={wall}s, "
          f"infra_failures={len(infra)} -> {batch_dir / 'batch.json'}")
    return payload