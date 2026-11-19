"""Benchmark-validity helpers (spec/02 L0, spec/03 section 1).

Two facts travel with every episode and are recorded in ``summary.json``:

* ``tree_version`` - a digest of the task package manifest. Rebuilding the
  manifest (any task/verifier/GT edit) changes the version; comparing runs
  from different versions is forbidden.
* ``reference_selfcheck`` - the L0 record produced by ``vericax audit``: the
  shipped reference deck was replayed and reproduced the shipped GT summary.

The L0 record lives next to the ground truth but is a derived audit artifact,
not a package resource, so ``scripts/pack_task.py`` excludes it from the
manifest and ``tree_version`` stays stable across audit reruns.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

MANIFEST = "resources.sha256"
L0_RECORD = "reference_selfcheck.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_version(task_dir: Path) -> str:
    """Digest of the package manifest; fails when the package is unpacked."""
    manifest = Path(task_dir) / MANIFEST
    if not manifest.is_file():
        raise SystemExit(f"task package has no {MANIFEST}: {task_dir}")
    return "sha256:" + sha256_bytes(manifest.read_bytes())


def short_tree_version(version: str | None) -> str:
    if not version:
        return "-"
    return version.split(":", 1)[-1][:12]


def reference_selfcheck_path(task_dir: Path) -> Path:
    return Path(task_dir) / "ground_truth" / L0_RECORD


def load_reference_selfcheck(task_dir: Path) -> dict | None:
    path = reference_selfcheck_path(task_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def reference_selfcheck_state(record: dict | None) -> str:
    """Spec/03 state: ``pass`` / ``fail`` / ``not_run``."""
    if not record or not record.get("performed"):
        return "not_run"
    return "pass" if record.get("passed") else "fail"


def parse_summary(text: str | None) -> list[float] | None:
    if text is None:
        return None
    parts = [part.strip() for part in text.strip().split(",")]
    if not parts:
        return None
    try:
        return [float(part) for part in parts]
    except ValueError:
        return None


def compare_summaries(
    observed: str | None,
    expected: str | None,
    rel_tol: float = 1e-6,
    abs_tol: float = 1e-9,
) -> bool:
    """L0 comparison: numeric when both sides are numeric, else exact text."""
    if observed is None or expected is None:
        return False
    left, right = parse_summary(observed), parse_summary(expected)
    if left is None or right is None:
        return observed.strip() == expected.strip()
    if len(left) != len(right):
        return False
    return all(
        math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)
        for a, b in zip(left, right)
    )