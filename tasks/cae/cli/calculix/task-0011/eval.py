#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0011 (drawing reconstruction).

Observation-reconstruct task: the stepped cantilever dimensions and tip load
are only in `drawing.svg`; this verifier checks the reconstructed model and
re-solves it.

Problem (from the drawing): total length 120 mm, root segment 70 mm with a
12 x 12 mm section, tip segment 50 mm with an 8 x 8 mm section, tip load
-80 N. 10 mm B31 elements, 13 nodes, clamped root.

Implements L1, L2 (model conformance), L3 (independent re-solve).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
CCX = os.environ.get("VERICAX_CCX", "/usr/bin/ccx")

REQUIRED_ARTIFACTS = ["solution.inp", "solution.dat", "summary.txt"]

# ---- dimensions read from drawing.svg ----
LENGTH, SPLIT_X = 120.0, 70.0
N_ELEM, ELEM_LEN = 12, 10.0
ROOT_SECTION, TIP_SECTION = (12.0, 12.0), (8.0, 8.0)
LOAD_FY = -80.0
E_YOUNG, NU = 210000.0, 0.3

EXPECTED_TIP_UY = None      # pinned from the same VM image (ground_truth/)

RESOLVE_REL_TOL = 1.0e-4
PINNED_REL_TOL = 1.0e-3
ANALYTIC_REL_TOL = 2.0e-2


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-12) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * abs(target))


# ---------------------------------------------------------------- deck parsing
def inp_blocks(text: str) -> list[tuple[str, list[str]]]:
    blocks = []
    current = None
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
    sets = {}
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
        return _fail("node ids must be 1..13")
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
    assigned = {}
    for kw, data in sec_cards:
        if "RECT" not in kw:
            return _fail("both beam sections must be section=RECT")
        name = kw_param(kw, "ELSET")
        if not name or not data:
            return _fail("*Beam Section needs an ELSET and a data line")
        vals = _floats(data[0])
        if not vals or len(vals) < 2:
            return _fail("malformed *Beam Section data")
        for e in sets.get(name.upper(), []):
            assigned[e] = (vals[0], vals[1])
    if set(assigned) != set(range(1, N_ELEM + 1)):
        return _fail("every element must get exactly one section")
    for e in range(1, 8):
        if assigned[e] != ROOT_SECTION:
            return _fail(f"element {e} must use the 12x12 section")
    for e in range(8, 13):
        if assigned[e] != TIP_SECTION:
            return _fail(f"element {e} must use the 8x8 section")

    cload = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(cload) != 1:
        return _fail("expected exactly one *Cload line")
    vals = _floats(cload[0])
    if not vals or int(vals[0]) != N_ELEM + 1 or int(vals[1]) != 2 or abs(vals[2] - LOAD_FY) > 1e-9:
        return _fail("tip load changed")

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
    return True


# ---------------------------------------------------------------- L3
def _ensure_output_requests(text: str) -> str:
    if "VCAX_ALL_NODES" in text:
        return text
    blocks = inp_blocks(text)
    ids = []
    for kw, data in blocks:
        if kw_base(kw) == "*NODE":
            for line in data:
                vals = _floats(line)
                if vals:
                    ids.append(int(vals[0]))
    if not ids:
        return text
    injection = ("*Nset, nset=VCAX_ALL_NODES\n" + ", ".join(str(n) for n in ids)
                 + "\n*Node Print, NSET=VCAX_ALL_NODES\nU\n")
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
def analytic_tip_uy() -> float:
    inertia_root = ROOT_SECTION[0] ** 4 / 12.0
    inertia_tip = TIP_SECTION[0] ** 4 / 12.0
    b = LENGTH - SPLIT_X
    bracket = ((LENGTH**3 - b**3) / (3.0 * inertia_root)
               + b**3 / (3.0 * inertia_tip))
    return LOAD_FY / E_YOUNG * bracket


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_conformance(inp_text):
        return False

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 1:
        return _fail("summary.txt must be one number: tip_uy")
    try:
        tip_s = float(summary[0])
    except ValueError:
        return _fail("summary.txt value is not a number")

    tip = l3_resolve(AGENT_ROOT / "solution.inp")
    if tip is None:
        return _fail("independent re-solve failed")
    if not close_enough(tip_s, tip, RESOLVE_REL_TOL):
        return _fail("tip_uy does not match the independent re-solve")
    if EXPECTED_TIP_UY is not None and not close_enough(tip, EXPECTED_TIP_UY, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference")
    if not close_enough(tip, analytic_tip_uy(), ANALYTIC_REL_TOL):
        return _fail("tip_uy inconsistent with stepped-beam theory")
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