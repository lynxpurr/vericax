#!/usr/bin/env python3
"""VeriCAx verifier - task-0003 (cae--cli--calculix: two load cases, one job).

Implements L1 (completeness), L2 (design conformance + load-case structure),
L3 (independent re-solve) and L4 (cross-stage consistency).

What L4 adds here: the two load cases must come from ONE job and stay mutually
consistent. A linear-elastic model loaded with 2F must deflect exactly twice as
far, so the verifier checks the measured ratio in the submitted solver output,
not just each value in isolation. That catches the classic multi-step failure
modes: forgetting to change the load in step 2, accumulating instead of
resetting it, reporting step 2 twice, or swapping the two values.
"""
from __future__ import annotations

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

# ---- pinned design (same stepped beam as task-0001) ----
LENGTH, SPLIT_X, N_ELEM, ELEM_LEN = 100.0, 50.0, 10, 10.0
F_STEP1, F_STEP2 = -100.0, -200.0
E_YOUNG, NU = 210000.0, 0.3
SECTION_ROOT = (10.0, 10.0)
SECTION_TIP = (6.0, 6.0)

EXPECTED_UY_100 = None      # pinned from the same VM image (ground_truth/)
EXPECTED_UY_200 = None

RESOLVE_REL_TOL = 1.0e-4    # summary vs independent re-solve
RATIO_REL_TOL = 2.0e-3      # L4: d2/d1 must be 2 for a linear model
ANALYTIC_REL_TOL = 0.02     # vs Euler-Bernoulli


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
            ids = [int(v[0]) for line in data if (v := _floats(line))]
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


def split_steps(blocks) -> list[list[tuple[str, list[str]]]]:
    """Split the deck into per-step block lists (*Step ... *End Step)."""
    steps: list[list[tuple[str, list[str]]]] = []
    current: list[tuple[str, list[str]]] | None = None
    for kw, data in blocks:
        base = kw_base(kw)
        if base == "*STEP":
            current = []
            steps.append(current)
        elif base == "*END STEP":
            current = None
        elif current is not None:
            current.append((kw, data))
    return steps


# ---------------------------------------------------------------- .dat parsing
def dat_displacement_blocks(dat_text: str) -> list[dict[int, float]]:
    """Return one {node: uy} map per displacements block, in file order."""
    out: list[dict[int, float]] = []
    header = None
    current: dict[int, float] | None = None
    for raw in dat_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.match(r"^[A-Za-z*]", s):
            low = s.lower()
            if "displacements" in low:
                current = {}
                out.append(current)
            else:
                current = None
            header = low
            continue
        if current is not None:
            p = s.split()
            try:
                current[int(p[0])] = float(p[2])
            except (ValueError, IndexError):
                continue
    return out


def parse_summary(summary_path: Path) -> tuple[float, float] | None:
    parts = [p.strip() for p in summary_path.read_text(errors="ignore").strip().split(",")]
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


# ---------------------------------------------------------------- L1
def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


# ---------------------------------------------------------------- L2
def l2_design_and_loadcases(inp_text: str) -> bool:
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
    if len(sec_cards) != 2:
        return _fail("expected exactly two *Beam Section cards")
    assigned: dict[int, tuple[float, float]] = {}
    for kw, data in sec_cards:
        if "RECT" not in kw:
            return _fail("both beam sections must be section=RECT")
        name = kw_param(kw, "ELSET")
        if not name or not data:
            return _fail("*Beam Section needs an ELSET and a data line")
        vals = _floats(data[0])
        if not vals or len(vals) < 2:
            return _fail("malformed *Beam Section data")
        members = sets.get(name.upper(), [])
        if not members:
            return _fail(f"beam section references unknown elset {name}")
        for e in members:
            assigned[e] = (vals[0], vals[1])
    if set(assigned) != set(range(1, N_ELEM + 1)):
        return _fail("every element must get exactly one section assignment")
    for e in range(1, 6):
        if assigned[e] != SECTION_ROOT:
            return _fail(f"element {e} must use the 10x10 section")
    for e in range(6, 11):
        if assigned[e] != SECTION_TIP:
            return _fail(f"element {e} must use the 6x6 section")

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
        return _fail("boundary condition changed")

    steps = split_steps(blocks)
    if len(steps) != 2:
        return _fail(f"expected exactly 2 analysis steps, found {len(steps)}")
    want = [F_STEP1, F_STEP2]
    for index, (step, expected_load) in enumerate(zip(steps, want), start=1):
        cloads = []
        for kw, data in step:
            if kw_base(kw) != "*CLOAD":
                continue
            for line in data:
                vals = _floats(line)
                if vals and len(vals) >= 3:
                    cloads.append((int(vals[0]), int(vals[1]), vals[2]))
        if len(cloads) != 1:
            return _fail(f"step {index} must contain exactly one *Cload line")
        node, dof, value = cloads[0]
        if node != N_ELEM + 1 or dof != 2:
            return _fail(f"step {index} must load node 11 in dof 2")
        if abs(value - expected_load) > 1e-9:
            return _fail(f"step {index} load must be {expected_load} N, found {value}")
    return True


# ---------------------------------------------------------------- L3
def _ensure_output_requests(text: str) -> str:
    """Guarantee exactly one U print request per step.

    CalculiX writes `.dat` from `*Node Print` and needs an explicit node set, so
    the verifier declares its own set and adds a print only to steps that lack
    one. Injecting unconditionally would duplicate output blocks and break the
    per-step pairing that L4 relies on.
    """
    if "VCAX_ALL_NODES" in text:
        return text
    blocks = inp_blocks(text)
    nodes = [int(v[0]) for kw, data in blocks if kw_base(kw) == "*NODE"
             for line in data if (v := _floats(line))]
    if not nodes:
        return text

    out: list[str] = []
    in_step = has_print = injected = False
    for raw in text.splitlines():
        stripped = raw.strip().upper()
        if stripped.startswith("*STEP"):
            in_step, has_print = True, False
            out.append(raw)
            continue
        if in_step and stripped.startswith("*NODE PRINT"):
            has_print = True
        if in_step and stripped.startswith("*END STEP"):
            if not has_print:
                out += ["*Node Print, NSET=VCAX_ALL_NODES", "U"]
                injected = True
            out.append(raw)
            in_step = False
            continue
        out.append(raw)

    result = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    if injected:
        nset = "*Nset, nset=VCAX_ALL_NODES\n" + ", ".join(str(n) for n in nodes) + "\n"
        result = re.sub(r"(?im)^\*step\b", nset + "*Step", result, count=1)
    return result


def l3_resolve(inp_path: Path) -> tuple[float, float] | None:
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        text = _ensure_output_requests(inp_path.read_text(errors="ignore"))
        (scratch / "solution.inp").write_text(text)
        subprocess.run([CCX, "solution"], cwd=scratch, timeout=300, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "solution.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            return None
        maps = dat_displacement_blocks(dat.read_text(errors="ignore"))
        if len(maps) != 2:
            return None
        u1 = maps[0].get(N_ELEM + 1)
        u2 = maps[1].get(N_ELEM + 1)
        if u1 is None or u2 is None:
            return None
        return u1, u2
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- analytic
def analytic_uy(load: float) -> float:
    i1 = SECTION_ROOT[0] ** 4 / 12.0
    i2 = SECTION_TIP[0] ** 4 / 12.0
    a = SPLIT_X
    int1 = (LENGTH**3 - (LENGTH - a) ** 3) / 3.0
    int2 = (LENGTH - a) ** 3 / 3.0
    return (load / E_YOUNG) * (int1 / i1 + int2 / i2)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_and_loadcases(inp_text):
        return False

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        return _fail("summary.txt must be two comma-separated floats: uy_100, uy_200")

    resolved = l3_resolve(AGENT_ROOT / "solution.inp")
    if resolved is None:
        return _fail("independent re-solve did not produce two displacement blocks")
    r1, r2 = resolved

    # A vs B
    if not close_enough(summary[0], r1, RESOLVE_REL_TOL):
        return _fail("uy_100 does not match the independent re-solve")
    if not close_enough(summary[1], r2, RESOLVE_REL_TOL):
        return _fail("uy_200 does not match the independent re-solve")

    # L4: cross-stage consistency (linear response to a doubled load)
    if abs(r1) < 1e-9:
        return _fail("step-1 displacement is zero; cannot check the ratio")
    if not close_enough(r2 / r1, 2.0, RATIO_REL_TOL):
        return _fail(f"step2/step1 displacement ratio is {r2 / r1:.4f}, expected 2.0")

    # B vs C (pinned) and vs beam theory
    if EXPECTED_UY_100 is not None and not close_enough(r1, EXPECTED_UY_100, 1e-3):
        return _fail("re-solve deviates from pinned reference (uy_100)")
    if EXPECTED_UY_200 is not None and not close_enough(r2, EXPECTED_UY_200, 1e-3):
        return _fail("re-solve deviates from pinned reference (uy_200)")
    if not close_enough(summary[0], analytic_uy(F_STEP1), ANALYTIC_REL_TOL):
        return _fail("uy_100 inconsistent with beam theory")
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
