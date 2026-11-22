#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0008 (two-step superposition).

Implements L1 (completeness), L2 (design conformance + load-step structure),
L3 (independent re-solve) and L4 (cross-stage consistency).

The job has two static steps on one uniform cantilever: step 1 applies a
transverse tip load, step 2 adds an axial tip load without removing the first.
Linear superposition then requires the final transverse displacement to equal
the step-1 value and the final axial displacement to equal the axial extension
of the beam. That is the cross-stage invariant checked here.

Three-way check:
  A  agent's summary.txt                  (uy1, ux2, uy2)
  B  verifier's independent re-solve      (tight)
  C  pinned reference from the same image (tight)
plus the linear-superposition invariant and a loose beam-theory band.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3", "L4")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
CCX = os.environ.get("VERICAX_CCX", "/usr/bin/ccx")

REQUIRED_ARTIFACTS = ["solution.inp", "solution.dat", "summary.txt"]

# ---- pinned design (task instruction) ----
LENGTH = 100.0
N_ELEM, ELEM_LEN = 10, 10.0
SIDE = 10.0
E_YOUNG, NU = 210000.0, 0.3
FY, FX = -100.0, 50.0

# ---- pinned reference, filled from the same VM image (ground_truth/) ----
EXPECTED_UY1 = None         # pinned from the same VM image (ground_truth/)
EXPECTED_UX2 = None
EXPECTED_UY2 = None

RESOLVE_REL_TOL = 1.0e-4    # summary vs independent re-solve
PINNED_REL_TOL = 1.0e-3     # B vs C
SUPERPOSITION_REL_TOL = 2.0e-3
AXIAL_REL_TOL = 2.0e-2
BENDING_REL_TOL = 2.0e-2


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-12) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * abs(target))


# ---------------------------------------------------------------- deck parsing
def inp_blocks(text: str) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            current = [line.upper(), []]
            blocks.append((current[0], current[1]))
            continue
        if current is not None:
            current[1].append(line)
    return blocks


def _floats(line: str) -> list[float] | None:
    try:
        return [float(p) for p in line.split(",") if p.strip() != ""]
    except ValueError:
        return None


def kw_base(kw: str) -> str:
    return kw.split(",")[0].strip().upper()


def kw_param(kw: str, name: str) -> str | None:
    for part in kw.split(",")[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip().upper() == name.upper():
                return v.strip().strip("'\"")
    return None


def _elsets(blocks) -> dict[str, list[int]]:
    sets: dict[str, list[int]] = {}
    for kw, data in blocks:
        base = kw_base(kw)
        name = kw_param(kw, "ELSET")
        if base.startswith("*ELEMENT"):
            ids = []
            for line in data:
                vals = _floats(line)
                if vals:
                    ids.append(int(vals[0]))
            if name:
                sets.setdefault(name.upper(), []).extend(ids)
        elif base == "*ELSET" and name:
            ids = []
            for line in data:
                vals = _floats(line)
                if vals:
                    ids.extend(int(v) for v in vals)
            sets.setdefault(name.upper(), []).extend(ids)
    return sets


def _steps(blocks):
    """Return [(step_keyword, static, [(cload_keyword, lines)])]."""
    steps = []
    current = None
    for kw, data in blocks:
        base = kw_base(kw)
        if base == "*STEP":
            current = {"kw": kw, "static": False, "cload": []}
            steps.append(current)
        elif base == "*END STEP":
            current = None
        elif current is not None:
            if base == "*STATIC":
                current["static"] = True
            elif base == "*CLOAD":
                current["cload"].append((kw, data))
    return steps


# ---------------------------------------------------------------- .dat parsing
def dat_step_u(dat_text: str) -> list[dict[int, tuple[float, float, float]]]:
    maps, current = [], None
    for raw in dat_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.match(r"^[A-Za-z*]", s):
            if "displacements" in s.lower():
                current = {}
                maps.append(current)
            else:
                current = None
            continue
        if current is not None:
            p = s.split()
            try:
                current[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
            except (ValueError, IndexError):
                pass
    return maps


# ---------------------------------------------------------------- L1
def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


# ---------------------------------------------------------------- L2
def l2_design_conformance(inp_text: str) -> bool:
    blocks = inp_blocks(inp_text)

    node_lines = [l for kw, data in blocks if kw_base(kw) == "*NODE" for l in data]
    if len(node_lines) != N_ELEM + 1:
        return _fail(f"expected exactly {N_ELEM + 1} nodes")
    nodes = {}
    for line in node_lines:
        vals = _floats(line)
        if not vals or len(vals) != 4:
            return _fail(f"malformed node line: {line}")
        nodes[int(vals[0])] = tuple(vals[1:4])
    if sorted(nodes) != list(range(1, N_ELEM + 2)):
        return _fail("node ids must be 1..11")
    for i in range(1, N_ELEM + 2):
        expected = (ELEM_LEN * (i - 1), 0.0, 0.0)
        if not all(close_enough(g, e, 0.0, abs_tol=1e-6) for g, e in zip(nodes[i], expected)):
            return _fail(f"node {i} must sit at x={expected[0]}")

    elem_blocks = [(kw, data) for kw, data in blocks if kw_base(kw).startswith("*ELEMENT")]
    if not elem_blocks or not all("B31" in kw for kw, _ in elem_blocks):
        return _fail("all element cards must be type B31")
    conns = []
    for _kw, data in elem_blocks:
        for line in data:
            vals = _floats(line)
            if not vals or len(vals) != 3:
                return _fail(f"malformed element line: {line}")
            conns.append(tuple(int(v) for v in vals))
    if sorted(conns) != sorted((e, e, e + 1) for e in range(1, N_ELEM + 1)):
        return _fail("element e must join nodes e and e+1")

    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        return _fail("expected exactly one *Elastic")
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        return _fail("material constants changed")

    sets = _elsets(blocks)
    sec_cards = [(kw, data) for kw, data in blocks if kw_base(kw).startswith("*BEAM SECTION")]
    if len(sec_cards) != 1:
        return _fail("expected exactly one *Beam Section")
    kw, data = sec_cards[0]
    if "RECT" not in kw:
        return _fail("the beam section must be section=RECT")
    name = kw_param(kw, "ELSET")
    if not name or set(sets.get(name.upper(), [])) != set(range(1, N_ELEM + 1)):
        return _fail("beam section must cover all elements")
    if not data:
        return _fail("*Beam Section needs a data line")
    vals = _floats(data[0])
    if not vals or len(vals) < 2 or abs(vals[0] - SIDE) > 1e-9 or abs(vals[1] - SIDE) > 1e-9:
        return _fail("beam section must be 10 x 10 mm")

    boundary_lines = [l for kw, data in blocks if kw_base(kw) == "*BOUNDARY" for l in data]
    if not boundary_lines:
        return _fail("missing clamped boundary")
    for line in boundary_lines:
        vals = _floats(line)
        if not vals:
            continue
        if not (int(vals[0]) == 1 and int(vals[1]) == 1 and int(vals[2]) == 6):
            return _fail("only node 1 dofs 1-6 may be constrained")
        if len(vals) > 3 and abs(vals[3]) > 1e-12:
            return _fail("clamped boundary must be zero")

    steps = _steps(blocks)
    if len(steps) != 2 or not all(s["static"] for s in steps):
        return _fail("expected exactly two static steps")

    def load_state(step, prior):
        sums = dict(prior)
        for kw, data in step["cload"]:
            if "OP=NEW" in kw:
                sums = {1: 0.0, 2: 0.0}
            for line in data:
                vals = _floats(line)
                if vals and int(vals[0]) == N_ELEM + 1 and int(vals[1]) in sums:
                    sums[int(vals[1])] += vals[2]
        return sums

    s1 = load_state(steps[0], {1: 0.0, 2: 0.0})
    if abs(s1[1]) > 1e-9 or abs(s1[2] - FY) > 1e-9:
        return _fail("step 1 must apply only FY=-100 N at the tip")
    s2 = load_state(steps[1], s1)
    if abs(s2[1] - FX) > 1e-9 or abs(s2[2] - FY) > 1e-9:
        return _fail("step 2 must leave the final tip load at (FX,FY)=(50,-100) N")
    return True


# ---------------------------------------------------------------- L3
def _ensure_output_requests(text: str) -> str:
    if "VCAX_ALL_NODES" in text:
        return text
    blocks = inp_blocks(text)
    if any(kw_base(kw) == "*NODE PRINT" for kw, _data in blocks):
        return text
    node_ids = []
    for kw, data in blocks:
        if kw_base(kw) == "*NODE":
            for line in data:
                vals = _floats(line)
                if vals:
                    node_ids.append(int(vals[0]))
    if not node_ids:
        return text
    injection = ("*Nset, nset=VCAX_ALL_NODES\n"
                 + ", ".join(str(n) for n in sorted(node_ids)) + "\n"
                 "*Node Print, NSET=VCAX_ALL_NODES\nU\n")
    return re.sub(r"(?im)^\*end step\s*$", injection + "*End Step", text, count=1)


def l3_resolve(inp_path: Path) -> tuple[float, float, float] | None:
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        text = _ensure_output_requests(inp_path.read_text(errors="ignore"))
        (scratch / "solution.inp").write_text(text)
        subprocess.run([CCX, "solution"], cwd=scratch, timeout=300, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "solution.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            return None
        maps = dat_step_u(dat.read_text(errors="ignore"))
        if len(maps) < 2 or N_ELEM + 1 not in maps[0] or N_ELEM + 1 not in maps[1]:
            return None
        uy1 = maps[0][N_ELEM + 1][1]
        ux2, uy2 = maps[1][N_ELEM + 1][0], maps[1][N_ELEM + 1][1]
        return uy1, ux2, uy2
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- beam theory
def analytic_uy() -> float:
    inertia = SIDE**4 / 12.0
    return FY * LENGTH**3 / (3.0 * E_YOUNG * inertia)


def analytic_ux() -> float:
    area = SIDE**2
    return FX * LENGTH / (E_YOUNG * area)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_conformance(inp_text):
        return False

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 3:
        return _fail("summary.txt must be three comma-separated numbers: uy1, ux2, uy2")
    try:
        uy1_s, ux2_s, uy2_s = (float(x) for x in summary)
    except ValueError:
        return _fail("summary.txt values are not numbers")

    resolved = l3_resolve(AGENT_ROOT / "solution.inp")
    if resolved is None:
        return _fail("independent re-solve failed to produce two steps")
    uy1, ux2, uy2 = resolved

    if not close_enough(uy1_s, uy1, RESOLVE_REL_TOL):
        return _fail("uy1 does not match the independent re-solve")
    if not close_enough(ux2_s, ux2, RESOLVE_REL_TOL):
        return _fail("ux2 does not match the independent re-solve")
    if not close_enough(uy2_s, uy2, RESOLVE_REL_TOL):
        return _fail("uy2 does not match the independent re-solve")

    if EXPECTED_UY1 is not None and not close_enough(uy1, EXPECTED_UY1, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (uy1)")
    if EXPECTED_UX2 is not None and not close_enough(ux2, EXPECTED_UX2, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (ux2)")
    if EXPECTED_UY2 is not None and not close_enough(uy2, EXPECTED_UY2, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (uy2)")

    # ---- L4: cross-stage superposition
    if not close_enough(uy2, uy1, SUPERPOSITION_REL_TOL):
        return _fail("step 2 changed the transverse displacement (loaded state reset)")
    if not close_enough(ux2, analytic_ux(), AXIAL_REL_TOL):
        return _fail("step 2 axial displacement is inconsistent with the axial load")
    if not close_enough(uy1, analytic_uy(), BENDING_REL_TOL):
        return _fail("step 1 transverse displacement is inconsistent with beam theory")
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