#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0006 (Euler buckling).

Implements L1 (completeness), L2 (design conformance) and L3 (independent
re-solve). L3 runs the submitted deck through the VM's own ccx and reads the
buckling-factor block from `.dat`; the verdict is anchored to the solver
output, never to the agent's claims.

Problem: first Euler buckling factor of a uniform steel cantilever column
(100 x 10 x 10 mm, 10 B31 elements) under a 1000 N axial reference load.

Three-way check:
  A  agent's summary.txt                   (buckling factor, Pcr in N)
  B  verifier's independent re-solve       (tight)
  C  pinned reference from the same image  (tight)
plus a loose Euler column band (physics net).
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
CCX = os.environ.get("VERICAX_CCX", "/usr/bin/ccx")

REQUIRED_ARTIFACTS = ["solution.inp", "solution.dat", "summary.txt"]

# ---- pinned design (task instruction) ----
LENGTH = 100.0
N_ELEM, ELEM_LEN = 10, 10.0
SIDE = 10.0
E_YOUNG, NU = 210000.0, 0.3
REFERENCE_LOAD = -1000.0     # N, axial compression at the tip
MODE = 1

# ---- pinned reference, filled from the same VM image (ground_truth/) ----
EXPECTED_FACTOR = None       # pinned from the same VM image (ground_truth/)
EXPECTED_PCR = None          # pinned from the same VM image (ground_truth/)

RESOLVE_REL_TOL = 1.0e-4     # A vs B: same deck, same solver
PINNED_REL_TOL = 1.0e-4      # B vs C: same solver, same settings
ANALYTIC_REL_TOL = 2.0e-2    # B vs Euler column (shear deformation omitted)


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


# ---------------------------------------------------------------- .dat parsing
def dat_buckling_factor(dat_text: str) -> float | None:
    armed = False
    for raw in dat_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        norm = s.lower().replace(" ", "")
        if "bucklingfactoroutput" in norm:
            armed = True
            continue
        if not armed:
            continue
        parts = s.split()
        try:
            values = [float(p) for p in parts]
        except ValueError:
            continue
        if len(values) >= 2 and int(values[0]) == MODE:
            return values[1]
    return None


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

    loads = [(kw, data) for kw, data in blocks if kw_base(kw) in ("*CLOAD", "*DLOAD")]
    if len(loads) != 1 or kw_base(loads[0][0]) != "*CLOAD":
        return _fail("expected exactly one *Cload card and no *Dload")
    cload_ok = False
    for line in loads[0][1]:
        vals = _floats(line)
        if vals and int(vals[0]) == N_ELEM + 1 and int(vals[1]) == 1:
            cload_ok = abs(vals[2] - REFERENCE_LOAD) < 1e-9
    if not cload_ok:
        return _fail("the tip reference load must be -1000 N in dof 1")

    buckle = [(kw, data) for kw, data in blocks if kw_base(kw) == "*BUCKLE"]
    if len(buckle) != 1:
        return _fail("expected exactly one *Buckle step")
    data = [l for l in buckle[0][1] if l.strip()]
    if not data:
        return _fail("*Buckle needs a data line")
    vals = _floats(data[0])
    if not vals or int(vals[0]) != 1 or (len(vals) > 1 and int(vals[1]) < 1):
        return _fail("*Buckle must request the first buckling mode")
    return True


# ---------------------------------------------------------------- L3
def l3_resolve(inp_path: Path) -> float | None:
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        (scratch / "solution.inp").write_text(inp_path.read_text(errors="ignore"))
        subprocess.run([CCX, "solution"], cwd=scratch, timeout=300, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "solution.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            return None
        return dat_buckling_factor(dat.read_text(errors="ignore"))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- Euler column
def analytic_factor() -> float:
    """First cantilever Euler factor for the 1000 N reference load."""
    inertia = SIDE**4 / 12.0
    pcr = math.pi**2 * E_YOUNG * inertia / (4.0 * LENGTH**2)
    return pcr / abs(REFERENCE_LOAD)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_conformance(inp_text):
        return False

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 2:
        return _fail("summary.txt must be two comma-separated numbers: buckling_factor, pcr_n")
    try:
        factor_s, pcr_s = (float(x) for x in summary)
    except ValueError:
        return _fail("summary.txt values are not numbers")

    factor = l3_resolve(AGENT_ROOT / "solution.inp")
    if factor is None:
        return _fail("independent re-solve failed to produce a buckling factor")

    if not close_enough(factor_s, factor, RESOLVE_REL_TOL):
        return _fail("buckling factor does not match the independent re-solve of solution.inp")
    if not close_enough(pcr_s, factor * abs(REFERENCE_LOAD), RESOLVE_REL_TOL):
        return _fail("pcr_n does not match the independent re-solve of solution.inp")

    if EXPECTED_FACTOR is not None and not close_enough(factor, EXPECTED_FACTOR, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (buckling factor)")
    if EXPECTED_PCR is not None and not close_enough(factor * abs(REFERENCE_LOAD), EXPECTED_PCR, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (pcr_n)")

    if not close_enough(factor, analytic_factor(), ANALYTIC_REL_TOL):
        return _fail("buckling factor inconsistent with the Euler column solution")
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