#!/usr/bin/env python3
"""VeriCAx verifier skeleton — implement the layers your task needs.

Contract (spec/02):
- Runs OUT-OF-BAND: agent must never reach this file or ground_truth/.
- Prints exactly ONE line: "True"/"False" (exact_match) or "0.000000".."1.000000" (quantified_score).
- Failure reasons go to stderr as "debug: <reason>" (scoring-side log; no rule enumeration).
- Standard library + the tested software's official API + Pillow only.
- Declare implemented layers at the top. L1/L2 mandatory; L3/L4 per task type; L5 for optimization.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2")  # extend with L3/L4/L5 as implemented

SCORING_ROOT = Path(__file__).resolve().parent          # scoring plane (out-of-band)
AGENT_ROOT = Path("/home/user/Desktop")                 # agent plane (deliverables live here)

REQUIRED_ARTIFACTS = ["solution.inp", "summary.txt"]    # L1: from task.artifact_paths
INPUT_CHECKSUMS = {                                     # L2: anti-tamper, pin at packaging time
    # "solution.inp": None  # baseline files are init_file/ paths -> sha256 filled by packager
}
ABS_TOL, REL_TOL = 1e-6, 1e-4


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


# --- L1 deliverable completeness -------------------------------------------------
def l1_completeness(agent_root: Path) -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = agent_root / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


# --- L2 anti-tamper + dual-path cross-check --------------------------------------
def l2_integrity(agent_root: Path) -> bool:
    # 1) input/baseline checksums (fill INPUT_CHECKSUMS at packaging time).
    for rel, expected in INPUT_CHECKSUMS.items():
        digest = hashlib.sha256((agent_root / rel).read_bytes()).hexdigest()
        if expected and digest != expected:
            return _fail(f"baseline modified: {rel}")
    # 2) dual-path cross-check TODO: reopen the artifact with two independent
    #    parsers (official API vs standalone parser) and compare key quantities.
    # 3) TODO: reopen via the official application interface here.
    return True


# --- L3 independent recompute (sim/optimization tasks) ---------------------------
def l3_recompute(agent_root: Path) -> bool:
    # TODO: independently re-solve from task inputs, read the submitted field
    # results back, compare element-wise within 1e-8 * scale.
    return True


# --- L4 chain evidence (cross-software/multi-stage tasks) ------------------------
def l4_chain_evidence(agent_root: Path) -> bool:
    # TODO: verify intermediate artifacts exist and are consistent across stages.
    return True


# --- verdict ---------------------------------------------------------------------
def evaluate() -> bool:
    if not l1_completeness(AGENT_ROOT):
        return False
    if not l2_integrity(AGENT_ROOT):
        return False
    if "L3" in IMPLEMENTS and not l3_recompute(AGENT_ROOT):
        return False
    if "L4" in IMPLEMENTS and not l4_chain_evidence(AGENT_ROOT):
        return False
    # exact_match tasks: all gates passed -> True.
    # quantified_score tasks (L5): compute score = clamp(1 - submitted/baseline)
    # with METRIC taken from task.json, print f"{score:.6f}" instead of True.
    return True


def main() -> int:
    try:
        ok = evaluate()
    except Exception as exc:  # noqa: BLE001 - verifier must never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        ok = False
    print("True" if ok else "False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
