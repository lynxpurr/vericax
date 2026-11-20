#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0016 (open-environment mesh tool).

The agent installs trimesh from the local wheelhouse, loads the provided
square-tube STL, and reports its volume and surface area. Exact values:
volume 840, area 728 (outer 10x10, inner 4x4, height 10).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
REQUIRED_ARTIFACTS = ["solve.py", "summary.txt"]
EXPECTED_VOLUME, EXPECTED_AREA = 840.0, 728.0
REL_TOL = 1.0e-2


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float) -> bool:
    return abs(actual - target) <= REL_TOL * abs(target)


def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


def l2_script_uses_trimesh() -> bool:
    text = (AGENT_ROOT / "solve.py").read_text(errors="ignore")
    if "trimesh" not in text:
        return _fail("solve.py does not use trimesh (install it from the wheelhouse)")
    return True


def evaluate() -> bool:
    if not l1_completeness():
        return False
    if not l2_script_uses_trimesh():
        return False
    parts = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(parts) != 2:
        return _fail("summary.txt must be two comma-separated numbers: volume, area")
    try:
        volume, area = (float(x) for x in parts)
    except ValueError:
        return _fail("summary.txt values are not numbers")
    if not close_enough(volume, EXPECTED_VOLUME):
        return _fail(f"volume {volume:.4f} is not within 1% of the part volume")
    if not close_enough(area, EXPECTED_AREA):
        return _fail(f"area {area:.4f} is not within 1% of the part area")
    return True


def main() -> int:
    try:
        ok = evaluate()
    except Exception as exc:  # noqa: BLE001
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        ok = False
    print("True" if ok else "False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())