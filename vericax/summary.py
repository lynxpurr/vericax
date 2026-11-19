"""summary.json assembly (spec/03 section 2 + spec/08 attributions).

The three-way attribution (agent/harness/model) always describes one stack
configuration; infra failures carry score 0 with ``scoring_basis="infra"``
and are excluded from capability aggregation upstream.
"""
from __future__ import annotations

import json
from pathlib import Path

SCORING_BASIS_NATIVE = "native_evaluator"
SCORING_BASIS_TIME_BUDGET = "active_time_budget"
SCORING_BASIS_INFRA = "infra"

RUN_MODES = ("rerun", "rescore")
RUN_MODE_RERUN = "rerun"
EPISODE_KINDS = ("capability", "test", "debug")


def build_summary(
    *,
    task_id: str,
    episode_id: str,
    run_index: int,
    run_total: int,
    agent: dict,
    harness: dict,
    model: dict,
    score: float | None,
    scoring_basis: str,
    native_evaluator_executed: bool,
    error: str | None,
    error_category: str | None,
    result_dir: str,
    artifact_uri: str | None,
    cost: dict | None,
    wall_duration_seconds: float,
    active_duration_seconds: float,
    active_time_limit_seconds: int | None,
    split_version: str | None,
    image_sha256: str,
    run_mode: str = RUN_MODE_RERUN,
    tree_version: str | None = None,
    reference_selfcheck: str = "not_run",
    kind: str = "capability",
    verifier_sha256: str | None = None,
    adapter_name: str | None = None,
    adapter_version: str | None = None,
    solver_version: str | None = None,
    agent_exit_code: int | None = None,
    killed_by_deadline: bool = False,
    deadline_epoch: float | None = None,
    sandbox_network_isolated: bool | None = None,
    scoring_network_isolated: bool | None = None,
) -> dict:
    return {
        "task_id": task_id,
        "episode_id": episode_id,
        "agent": agent,
        "harness": harness,
        "model": model,
        "score": score,
        "scoring_basis": scoring_basis,
        "native_evaluator_executed": native_evaluator_executed,
        "error": error,
        "error_category": error_category,
        "result_dir": result_dir,
        "artifact_uri": artifact_uri,
        "cost": cost,
        "wall_duration_seconds": round(wall_duration_seconds, 3),
        "paused_seconds": 0.0,
        "active_duration_seconds": round(active_duration_seconds, 3),
        "active_time_limit_seconds": active_time_limit_seconds,
        "split_version": split_version,
        "run_index": run_index,
        "run_total": run_total,
        # ---- benchmark validity (spec/02 L0, spec/03 section 1)
        "run_mode": run_mode,
        "tree_version": tree_version,
        "reference_selfcheck": reference_selfcheck,
        "kind": kind,
        # ---- VeriCAx Phase 1 provenance extensions (spec/09 section 7.3)
        "image_sha256": image_sha256,
        "verifier_sha256": verifier_sha256,
        "adapter": {"name": adapter_name, "version": adapter_version},
        "solver_version": solver_version,
        "agent_exit_code": agent_exit_code,
        "killed_by_deadline": killed_by_deadline,
        "deadline_epoch": deadline_epoch,
        "network_isolation": {
            "sandbox": sandbox_network_isolated,
            "scoring": scoring_network_isolated,
        },
    }


def write_summary(episode_dir: Path, summary: dict) -> Path:
    path = Path(episode_dir) / "summary.json"
    path.write_text(json.dumps(summary, indent=2) + "\n")
    return path
