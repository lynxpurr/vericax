"""Parallel episode scheduling (P4, spec/09 section 11).

Two episodes run concurrently, each with its own sandbox overlay, agent
container, proxy socket, cache directory and scoring instance. The lifecycle
closes the sandbox before scoring (E5), so N parallel episodes hold at most N
VMs at any moment; the acceptance scope validated N=2.

The scheduler is deliberately a thin thread pool over ``run_episode``: every
per-episode artifact already lives under ``runs/<episode>/``, so the only
shared state is the image-hash cache (made atomic in config.py) and stdout.

Reliability rules (2026-11-26, from the B2 run; spec/11 section 3.4):

- an episode that ends ``scoring_basis="infra"`` is retried with a NEW episode
  once the pass has drained, at most ``infra_retries`` times per
  (task, run_index). Native scores, including 0.0, are never retried.
- ``infra_breaker`` infra results in a row stop the batch: the host is sick,
  so the remaining jobs are skipped instead of feeding it more VMs.
- before the first VM boots, every task passes the offline package check and
  the VeriCAx VM containers already running are reported; before each launch
  the batch waits for free memory.
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

from . import adapters as adapters_mod
from . import config, host, lifecycle, summary as summary_mod
from .errors import CAT_INFRA_INCOMPLETE

MAX_VALIDATED_PARALLEL = 2
DEFAULT_INFRA_RETRIES = 2      # spec/11 section 3.4: at most two retries per job
DEFAULT_INFRA_BREAKER = 3      # consecutive infra results that stop the batch
DEFAULT_RETRY_COOLDOWN = 60    # seconds between a pass and its retry pass
DEFAULT_MIN_FREE_MB = 6144     # per in-flight episode: VM RAM, qemu, agent container
DEFAULT_MEMORY_WAIT = 600      # seconds a launch waits for that memory


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


def preflight(task_ids: list[str], adapter_spec: str,
              image_overrides: dict[str, Path]) -> dict:
    """Offline checks that must stop the batch before any VM boots.

    A stale manifest, a missing image or a broken adapter is a configuration
    error. Left to the jobs it would be recorded as infra and retried.
    """
    adapter = adapters_mod.load_adapter(adapters_mod.resolve_adapter(adapter_spec))
    images: dict[str, str] = {}
    for task_id in task_ids:
        task_dir = lifecycle._task_dir(task_id)
        task_json = lifecycle._load_task(task_dir, task_id)
        lifecycle._verify_task_package(task_dir)
        snapshot = task_json.get("snapshot", "CalculiX-2.21")
        images[task_id] = str(config.image_path(
            snapshot, override=image_overrides.get(snapshot)))
    return {"adapter": adapter.name, "images": images}


def is_infra(record: dict) -> bool:
    """True for an attempt that produced no capability result."""
    return record["scoring_basis"] == summary_mod.SCORING_BASIS_INFRA or (
        record["scoring_basis"] is None
        and record["error_category"] == CAT_INFRA_INCOMPLETE)


def _latest(records: list[dict]) -> dict[tuple[str, int], dict]:
    """The last attempt of every (task, run_index)."""
    latest: dict[tuple[str, int], dict] = {}
    for record in records:
        latest[(record["task_id"], record["run_index"])] = record
    return latest


def _wait_for_memory(need_mb: int, wait_seconds: int, poll: float = 15.0) -> bool:
    """Block until the host has ``need_mb`` available; False when it never does.

    MemAvailable rather than "free": the page cache is reclaimable and the VMs
    need it. Without a readable ``/proc/meminfo`` the gate lets the job through.
    """
    if need_mb <= 0:
        return True
    deadline = time.monotonic() + wait_seconds
    while True:
        available = host.mem_available_mb()
        if available is None or available >= need_mb:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        print(f"batch: waiting for memory ({available} MB available, need {need_mb} MB)",
              flush=True)
        time.sleep(min(poll, remaining))


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
    infra_retries: int = DEFAULT_INFRA_RETRIES,
    infra_breaker: int = DEFAULT_INFRA_BREAKER,
    retry_cooldown: int = DEFAULT_RETRY_COOLDOWN,
    min_free_mb: int = DEFAULT_MIN_FREE_MB,
    memory_wait: int = DEFAULT_MEMORY_WAIT,
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
    check = preflight(task_ids, adapter_spec, image_overrides)
    images = set(check["images"].values())
    snapshots = {task: _snapshot_for(task) for task in task_ids}
    if len(set(snapshots.values())) > 1 and not image_overrides:
        if os.environ.get("VERICAX_IMAGE"):
            raise SystemExit(
                "batch spans multiple snapshots but VERICAX_IMAGE overrides all of "
                "them; pass --image SNAPSHOT=PATH for each instead")

    # Leftover VMs from earlier episodes are reported, never removed: the batch
    # only ever touches the containers it starts itself.
    before = host.vericax_vm_containers(config.images_dir(), extra_images=images)
    preflight_record = {
        "leftover_vms": before["containers"],
        "inventory_error": before["error"],
        "memory_mb": host.meminfo_mb(),
        "loadavg": host.loadavg(),
    }
    for leftover in before["containers"]:
        print(f"batch: WARNING - a VeriCAx VM is already running: {leftover['name']} "
              f"(created {leftover['created']}); it holds RAM and cores")
    if before["error"]:
        print(f"batch: WARNING - could not list running VM containers: {before['error']}")

    started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    batch_dir = config.REPO / "runs" / f"batch-{stamp}-{secrets.token_hex(2)}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    print_lock = threading.Lock()
    state_lock = threading.Lock()
    state = {"in_flight": 0, "consecutive_infra": 0, "stop": None}
    records: list[dict] = []

    def skipped(task_id: str, run_index: int, attempt: int, reason: str) -> dict:
        return {
            "task_id": task_id, "run_index": run_index, "attempt": attempt,
            "snapshot": snapshots[task_id], "episode_id": None, "score": None,
            "scoring_basis": None, "error_category": None, "error": None,
            "wall_seconds": 0.0, "skipped": reason,
        }

    def one(task_id: str, run_index: int, attempt: int) -> dict:
        with state_lock:
            if state["stop"] is not None:
                return skipped(task_id, run_index, attempt, state["stop"])
            state["in_flight"] += 1
        try:
            # Each episode needs its own share before it adds a VM to the host.
            with state_lock:
                need_mb = state["in_flight"] * min_free_mb
            if not _wait_for_memory(need_mb, memory_wait):
                with state_lock:
                    state["stop"] = state["stop"] or "memory_gate"
                return skipped(task_id, run_index, attempt, "memory_gate")

            started_job = time.monotonic()
            record: dict = {
                "task_id": task_id,
                "run_index": run_index,
                "attempt": attempt,
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
            except SystemExit as exc:
                # A harness or configuration error is not an infra result: it is
                # recorded, it stops the batch, and nothing retries it.
                with state_lock:
                    state["stop"] = state["stop"] or f"error: {exc}"
                return skipped(task_id, run_index, attempt, f"error: {exc}")
            except Exception as exc:  # noqa: BLE001 - one job must not sink the batch
                record["error_category"] = CAT_INFRA_INCOMPLETE
                record["error"] = f"{type(exc).__name__}: {exc}"
            record["wall_seconds"] = round(time.monotonic() - started_job, 3)
            with state_lock:
                if is_infra(record):
                    state["consecutive_infra"] += 1
                    if (infra_breaker and state["consecutive_infra"] >= infra_breaker
                            and state["stop"] is None):
                        state["stop"] = "infra_breaker"
                else:
                    state["consecutive_infra"] = 0
            with print_lock:
                print(f"batch: {task_id} run {run_index}/{runs} attempt {attempt} -> "
                      f"score={record['score']} basis={record['scoring_basis']} "
                      f"error={record['error']}", flush=True)
            return record
        finally:
            with state_lock:
                state["in_flight"] -= 1

    def run_pass(jobs: list[tuple[str, int, int]]) -> list[dict]:
        done: list[dict] = []
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(one, task, index, attempt) for task, index, attempt in jobs]
            for future in as_completed(futures):
                done.append(future.result())
        return done

    jobs = [(task, index, 1) for task in task_ids for index in range(1, runs + 1)]
    records += run_pass(jobs)
    first_pass_infra = sum(1 for record in records if is_infra(record))

    rounds = 0
    while infra_retries and state["stop"] is None and rounds < infra_retries:
        pending = [(task, index) for (task, index), record in _latest(records).items()
                   if is_infra(record)]
        if not pending:
            break
        rounds += 1
        print(f"batch: retrying {len(pending)} infra job(s) "
              f"(retry {rounds}/{infra_retries}) after a {retry_cooldown}s cooldown", flush=True)
        if retry_cooldown:
            time.sleep(retry_cooldown)
        records += run_pass([(task, index, rounds + 1) for task, index in pending])

    wall = round(time.monotonic() - started, 1)
    records.sort(key=lambda row: (row["task_id"], row["run_index"], row["attempt"]))

    after = host.vericax_vm_containers(config.images_dir(), extra_images=images)
    known = {leftover["name"] for leftover in before["containers"]}
    leaked = [item for item in after["containers"] if item["name"] not in known]
    for item in leaked:
        print(f"batch: WARNING - VM container left behind: {item['name']}")

    latest = _latest(records)
    still_infra = sum(1 for record in latest.values() if is_infra(record))
    skipped_jobs = sum(1 for record in latest.values() if record.get("skipped"))
    retried_jobs = sum(1 for record in latest.values() if record["attempt"] > 1)
    infra_attempts = sum(1 for record in records if is_infra(record))
    if still_infra or skipped_jobs:
        verdict = "FAIL"
    elif retried_jobs:
        verdict = "pass_after_retry"
    else:
        verdict = "pass"
    payload = {
        "started_at": stamp,
        "adapter": adapter_spec,
        "parallel": parallel,
        "runs": runs,
        "kind": kind,
        "wall_seconds": wall,
        "jobs": len(jobs),
        "attempts": len(records),
        "infra_failures": still_infra,
        "infra_attempts": infra_attempts,
        "first_pass_infra": first_pass_infra,
        "infra_rate": round(infra_attempts / len(records), 4) if records else 0.0,
        "retried_jobs": retried_jobs,
        "infra_retries": infra_retries,
        "infra_breaker": infra_breaker,
        "min_free_mb": min_free_mb,
        "stopped": state["stop"],
        "preflight": preflight_record,
        "leaked_vms": leaked,
        "verdict": verdict,
        "episodes": records,
    }
    (batch_dir / "batch.json").write_text(json.dumps(payload, indent=2) + "\n")

    print("\nbatch summary")
    print("task | run | attempt | episode | score | basis | error | wall_s")
    print("---|---|---|---|---|---|---|---")
    for row in records:
        if row.get("skipped"):
            print(f"{row['task_id']} | {row['run_index']} | {row['attempt']} | "
                  f"- | - | skipped | {row['skipped']} | 0")
            continue
        print(f"{row['task_id']} | {row['run_index']} | {row['attempt']} | "
              f"{row['episode_id'] or '-'} | "
              f"{row['score'] if row['score'] is not None else '-'} | "
              f"{row['scoring_basis'] or '-'} | "
              f"{(row['error'] or '-')[:160]} | "
              f"{row['wall_seconds']}")
    print(f"\nbatch: {len(jobs)} job(s), {len(records)} attempt(s), parallel={parallel}, "
          f"wall={wall}s, infra_failures={still_infra}, "
          f"retried_jobs={retried_jobs} -> {batch_dir / 'batch.json'}")
    if state["stop"]:
        print(f"batch: stopped early ({state['stop']})")
    return payload
