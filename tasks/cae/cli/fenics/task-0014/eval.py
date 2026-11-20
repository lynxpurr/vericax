#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0014 (open-environment setup).

The agent must install scikit-fem from the local wheelhouse and use it to solve

    -Delta u = 2*pi^2 sin(pi x) sin(pi y)  on [0,1]^2,  u = 0 on the boundary,

whose exact maximum is 1. This verifier checks the delivered script uses
scikit-fem (L2) and the reported maximum (L3). It does not need scikit-fem in
the scoring VM.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
REQUIRED_ARTIFACTS = ["solve.py", "summary.txt"]
EXACT_MAX = 1.0
MAX_TOL = 2.0e-2


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


def l2_script_uses_skfem() -> bool:
    text = (AGENT_ROOT / "solve.py").read_text(errors="ignore")
    if "skfem" not in text:
        return _fail("solve.py does not use scikit-fem (install it from the wheelhouse)")
    return True


def evaluate() -> bool:
    if not l1_completeness():
        return False
    if not l2_script_uses_skfem():
        return False
    parts = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(parts) != 1:
        return _fail("summary.txt must be one number: max_u")
    try:
        value = float(parts[0])
    except ValueError:
        return _fail("summary.txt value is not a number")
    if abs(value - EXACT_MAX) > MAX_TOL:
        return _fail(f"max_u={value:.6f} is not within {MAX_TOL:.0%} of the exact maximum")
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