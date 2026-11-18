#!/usr/bin/env python3
"""VeriCAx verifier - task-0002 (cae--cli--calculix: mass-minimising stepped beam).

Quantified-score task (spec/02 L5), two stages:

  stage 1 (feasibility gate)  deck conformance, variable bounds, deflection
                              limit on the independent re-solve, and an
                              outer-fibre stress check from beam theory.
                              Any violation -> 0.000000 (no partial credit).
  stage 2 (quality score)     score = clamp(1 - mass / mass_baseline), where
                              mass is computed by the verifier from the deck's
                              own sections and the baseline is the uniform
                              10x10 mm design on the same mesh.

The agent's summary.txt is cross-checked against the verifier's independent
re-solve; it is never the source of the score.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3", "L5")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
CCX = os.environ.get("VERICAX_CCX", "/usr/bin/ccx")

REQUIRED_ARTIFACTS = ["solution.inp", "solution.dat", "summary.txt"]

# ---- pinned problem statement ----
LENGTH, N_ELEM, ELEM_LEN = 100.0, 10, 10.0
SPLIT_X = 50.0
LOAD_FY = -100.0
E_YOUNG, NU = 210000.0, 0.3
A1_BOUNDS = (6.0, 12.0)      # root segment side, mm
A2_BOUNDS = (4.0, 10.0)      # tip segment side, mm
DEFLECTION_LIMIT = 0.35      # |uy| at the tip, mm
STRESS_LIMIT = 140.0         # outer-fibre bending stress, MPa
MASS_BASELINE = 50.0 * 10.0**2 * 2   # uniform 10x10 on the same mesh = 10000
BASELINE_SUMMARY = "10.0, 10.0"      # reported for reference only

RESOLVE_REL_TOL = 1.0e-4     # summary vs independent re-solve
VARIABLE_REL_TOL = 1.0e-6    # summary sections vs deck sections
BOUND_TOL = 1.0e-9


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-9) -> bool:
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
def dat_nodal_uy(dat_text: str, node: int) -> float | None:
    header = None
    for raw in dat_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.match(r"^[A-Za-z*]", s):
            header = s.lower()
            continue
        if header and "displacements" in header:
            p = s.split()
            try:
                if int(p[0]) == node:
                    return float(p[2])
            except (ValueError, IndexError):
                continue
    return None


# ---------------------------------------------------------------- L1
def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


# ---------------------------------------------------------------- L2
def parse_design(inp_text: str) -> tuple[float, float] | None:
    """Validate deck structure and return (a1, a2) or None on any violation."""
    blocks = inp_blocks(inp_text)

    node_lines = [l for kw, data in blocks if kw_base(kw) == "*NODE" for l in data]
    if len(node_lines) != N_ELEM + 1:
        _fail(f"expected exactly {N_ELEM + 1} nodes")
        return None
    nodes = {}
    for line in node_lines:
        vals = _floats(line)
        if not vals or len(vals) != 4:
            _fail(f"malformed node line: {line}")
            return None
        nodes[int(vals[0])] = tuple(vals[1:4])
    if sorted(nodes) != list(range(1, N_ELEM + 2)):
        _fail("node ids must be 1..11")
        return None
    for i in range(1, N_ELEM + 2):
        expected = (ELEM_LEN * (i - 1), 0.0, 0.0)
        if not all(close_enough(g, e, 0.0, abs_tol=1e-6) for g, e in zip(nodes[i], expected)):
            _fail(f"node {i} must sit at x={expected[0]}")
            return None

    elem_blocks = [(kw, data) for kw, data in blocks if kw_base(kw).startswith("*ELEMENT")]
    if not elem_blocks or not all("B31" in kw for kw, _ in elem_blocks):
        _fail("all element cards must be type B31")
        return None
    conns = []
    for _kw, data in elem_blocks:
        for line in data:
            vals = _floats(line)
            if not vals or len(vals) != 3:
                _fail(f"malformed element line: {line}")
                return None
            conns.append(tuple(int(v) for v in vals))
    if sorted(conns) != sorted((e, e, e + 1) for e in range(1, N_ELEM + 1)):
        _fail("element e must join nodes e and e+1")
        return None

    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        _fail("expected exactly one *Elastic")
        return None
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        _fail("material constants changed")
        return None

    sets = _elsets(blocks)
    assigned: dict[int, float] = {}
    sec_cards = [(kw, data) for kw, data in blocks if kw_base(kw).startswith("*BEAM SECTION")]
    if len(sec_cards) != 2:
        _fail("expected exactly two *Beam Section cards")
        return None
    for kw, data in sec_cards:
        if "RECT" not in kw:
            _fail("both beam sections must be section=RECT")
            return None
        name = kw_param(kw, "ELSET")
        if not name or not data:
            _fail("*Beam Section needs an ELSET and a data line")
            return None
        vals = _floats(data[0])
        if not vals or len(vals) < 2:
            _fail("malformed *Beam Section data")
            return None
        if abs(vals[0] - vals[1]) > 1e-9:
            _fail("optimisation variables are square sections (side x side)")
            return None
        members = sets.get(name.upper(), [])
        if not members:
            _fail(f"beam section references unknown elset {name}")
            return None
        for e in members:
            if e in assigned:
                _fail(f"element {e} has two section assignments")
                return None
            assigned[e] = vals[0]
    if set(assigned) != set(range(1, N_ELEM + 1)):
        _fail("every element must get exactly one section assignment")
        return None
    a1 = assigned[1]
    a2 = assigned[N_ELEM]
    if not all(abs(assigned[e] - a1) < 1e-9 for e in range(1, 6)):
        _fail("root segment (elements 1-5) must share one section")
        return None
    if not all(abs(assigned[e] - a2) < 1e-9 for e in range(6, 11)):
        _fail("tip segment (elements 6-10) must share one section")
        return None

    if not (A1_BOUNDS[0] - BOUND_TOL <= a1 <= A1_BOUNDS[1] + BOUND_TOL):
        _fail(f"a1={a1} outside [{A1_BOUNDS[0]}, {A1_BOUNDS[1]}]")
        return None
    if not (A2_BOUNDS[0] - BOUND_TOL <= a2 <= A2_BOUNDS[1] + BOUND_TOL):
        _fail(f"a2={a2} outside [{A2_BOUNDS[0]}, {A2_BOUNDS[1]}]")
        return None

    cload = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(cload) != 1:
        _fail("expected exactly one *Cload line")
        return None
    vals = _floats(cload[0])
    if not vals or int(vals[0]) != N_ELEM + 1 or int(vals[1]) != 2 or abs(vals[2] - LOAD_FY) > 1e-9:
        _fail("tip load changed")
        return None

    ok_bc = False
    for kw, data in blocks:
        if kw_base(kw) != "*BOUNDARY":
            continue
        for line in data:
            vals = _floats(line)
            if vals and int(vals[0]) == 1 and int(vals[1]) == 1 and int(vals[2]) == 6:
                if len(vals) == 3 or abs(vals[3]) < 1e-12:
                    ok_bc = True
    if not ok_bc:
        _fail("boundary condition changed")
        return None
    return a1, a2


# ---------------------------------------------------------------- L3
def _ensure_output_requests(text: str) -> str:
    if "VCAX_ALL_NODES" in text:
        return text
    blocks = inp_blocks(text)
    nodes: list[int] = []
    for kw, data in blocks:
        if kw_base(kw) == "*NODE":
            for line in data:
                vals = _floats(line)
                if vals:
                    nodes.append(int(vals[0]))
    if not nodes:
        return text
    injection = (
        "*Nset, nset=VCAX_ALL_NODES\n" + ", ".join(str(n) for n in nodes) + "\n"
        "*Node Print, NSET=VCAX_ALL_NODES\nU\n"
    )
    return re.sub(r"(?im)^\*end step\s*$", injection + "*End Step", text, count=1)


def l3_resolve(inp_path: Path) -> float | None:
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        text = _ensure_output_requests(inp_path.read_text(errors="ignore"))
        (scratch / "solution.inp").write_text(text)
        subprocess.run([CCX, "solution"], cwd=scratch, timeout=300, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "solution.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            return None
        return dat_nodal_uy(dat.read_text(errors="ignore"), N_ELEM + 1)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- beam theory
def outer_fibre_stress(a1: float, a2: float) -> float:
    """Max outer-fibre bending stress over both segments (MPa).

    sigma = M * (a/2) / (a^4/12) = 6M/a^3, with M the internal moment:
    M(0) = F*L = 1e4 N.mm at the root, M(50) = F*50 = 5e3 N.mm at the step.
    """
    m_root = abs(LOAD_FY) * LENGTH
    m_step = abs(LOAD_FY) * (LENGTH - SPLIT_X)
    return max(6.0 * m_root / a1**3, 6.0 * m_step / a2**3)


def mass_of(a1: float, a2: float) -> float:
    """Relative mass: unit density, 50 mm per segment."""
    return (LENGTH - SPLIT_X) * a1**2 + SPLIT_X * a2**2


# ---------------------------------------------------------------- verdict
def evaluate() -> float:
    if not l1_completeness():
        return 0.0
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    design = parse_design(inp_text)
    if design is None:
        return 0.0
    a1, a2 = design

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 3:
        _fail("summary.txt must be three comma-separated numbers: a1, a2, tip_uy")
        return 0.0
    try:
        s_a1, s_a2, s_uy = (float(x) for x in summary)
    except ValueError:
        _fail("summary.txt values are not numbers")
        return 0.0

    if not close_enough(s_a1, a1, VARIABLE_REL_TOL) or not close_enough(s_a2, a2, VARIABLE_REL_TOL):
        _fail("reported sections do not match the deck sections")
        return 0.0

    uy = l3_resolve(AGENT_ROOT / "solution.inp")
    if uy is None:
        _fail("independent re-solve failed to produce results")
        return 0.0
    if not close_enough(s_uy, uy, RESOLVE_REL_TOL):
        _fail("reported tip_uy does not match the independent re-solve")
        return 0.0

    # ---- stage 1: feasibility gate (no partial credit)
    if abs(uy) > DEFLECTION_LIMIT:
        _fail(f"deflection {abs(uy):.4f} mm exceeds the {DEFLECTION_LIMIT} mm limit")
        return 0.0
    sigma = outer_fibre_stress(a1, a2)
    if sigma > STRESS_LIMIT * (1 + 1e-9):
        _fail(f"outer-fibre stress {sigma:.1f} MPa exceeds the {STRESS_LIMIT} MPa limit")
        return 0.0

    # ---- stage 2: quality score
    score = 1.0 - mass_of(a1, a2) / MASS_BASELINE
    return max(0.0, min(1.0, score))


def main() -> int:
    try:
        score = evaluate()
    except Exception as exc:  # noqa: BLE001 - verifier must never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        score = 0.0
    print(f"{max(0.0, min(1.0, float(score))):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
