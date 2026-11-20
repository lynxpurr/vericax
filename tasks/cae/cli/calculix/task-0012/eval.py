#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0012 (report reconstruction).

Observation-reconstruct task: the 2-bar truss nodes, members, supports and load
are only in `report.md`; this verifier checks the reconstructed T3D2 model and
re-solves it.

Two-bar truss: nodes (0,0), (1000,0), (500,500); both base nodes pinned, all z
fixed; area 100 mm^2; E=210000; load -1000 N in y at node 3. The exact tip
displacement is ux=0, uy=-0.0336718 mm.

Implements L1, L2, L3.
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

IMPLEMENTS = ("L1", "L2", "L3")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
CCX = os.environ.get("VERICAX_CCX", "/usr/bin/ccx")

REQUIRED_ARTIFACTS = ["solution.inp", "solution.dat", "summary.txt"]

NODES = {1: (0.0, 0.0, 0.0), 2: (1000.0, 0.0, 0.0), 3: (500.0, 500.0, 0.0)}
MEMBERS = ((1, 3), (2, 3))
AREA = 100.0
LOAD_FY = -1000.0
E_YOUNG, NU = 210000.0, 0.3

EXPECTED_UX3 = None
EXPECTED_UY3 = None

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


def _nsets(blocks) -> dict[str, list[int]]:
    sets = {}
    for kw, data in blocks:
        if kw_base(kw) != "*NSET":
            continue
        name = kw_param(kw, "NSET")
        if not name:
            continue
        ids = []
        for line in data:
            vals = _floats(line)
            if vals:
                ids.extend(int(v) for v in vals)
        sets.setdefault(name.upper(), []).extend(ids)
    return sets


def _nodes(blocks) -> dict[int, tuple[float, float, float]]:
    nodes = {}
    for kw, data in blocks:
        if kw_base(kw) != "*NODE":
            continue
        for line in data:
            vals = _floats(line)
            if not vals or len(vals) != 4:
                raise ValueError(f"malformed node line: {line}")
            nodes[int(vals[0])] = (vals[1], vals[2], vals[3])
    return nodes


def _elements(blocks) -> dict[int, tuple[str, list[int]]]:
    elements = {}
    for kw, data in blocks:
        if not kw_base(kw).startswith("*ELEMENT"):
            continue
        etype = (kw_param(kw, "TYPE") or "").upper()
        for line in data:
            vals = _floats(line)
            if vals:
                elements[int(vals[0])] = (etype, [int(v) for v in vals[1:]])
    return elements


def dat_nodal_u(dat_text: str, node: int) -> tuple[float, float, float] | None:
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
                    return float(p[1]), float(p[2]), float(p[3])
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
    try:
        nodes = _nodes(blocks)
        elements = _elements(blocks)
    except ValueError as exc:
        return _fail(str(exc))

    if set(nodes) != {1, 2, 3}:
        return _fail("expected exactly nodes 1, 2, 3")
    for nid, xyz in NODES.items():
        if not all(close_enough(g, e, 0.0, abs_tol=1e-6) for g, e in zip(nodes[nid], xyz)):
            return _fail(f"node {nid} coordinates do not match the report")

    if len(elements) != 2:
        return _fail("expected exactly two truss elements")
    conns = []
    for eid, (etype, conn) in elements.items():
        if etype != "T3D2":
            return _fail(f"element {eid} must be type T3D2")
        if len(conn) != 2 or any(n not in nodes for n in conn):
            return _fail(f"element {eid} has malformed connectivity")
        conns.append(tuple(sorted(conn)))
    if sorted(conns) != sorted(tuple(sorted(m)) for m in MEMBERS):
        return _fail("elements must join 1-3 and 2-3")

    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        return _fail("expected exactly one *Elastic")
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        return _fail("material constants changed")

    solid = [(kw, data) for kw, data in blocks if kw_base(kw) == "*SOLID SECTION"]
    if len(solid) != 1 or not solid[0][1]:
        return _fail("expected one *Solid Section with an area line")
    vals = _floats(solid[0][1][0])
    if not vals or abs(vals[0] - AREA) > 1e-9:
        return _fail("truss area changed")

    # supports: node 1 and 2 pinned in x/y, every node fixed in z
    nsets = _nsets(blocks)
    support: dict[int, set[int]] = {n: set() for n in nodes}
    for kw, data in blocks:
        if kw_base(kw) != "*BOUNDARY":
            continue
        for line in data:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            token = parts[0]
            if token.upper() in nsets:
                ids = nsets[token.upper()]
            else:
                try:
                    ids = [int(token)]
                except ValueError:
                    continue
            try:
                first = int(parts[1])
                last = int(parts[2]) if len(parts) > 2 and parts[2] else first
                value = float(parts[3]) if len(parts) > 3 and parts[3] else 0.0
            except ValueError:
                continue
            if abs(value) > 1e-12:
                return _fail("support displacements must be zero")
            for nid in ids:
                if nid in support:
                    support[nid].update(range(first, last + 1))
    if not {1, 2} <= support[1] or not {1, 2} <= support[2]:
        return _fail("nodes 1 and 2 must be pinned in x and y")
    if 3 not in support[3]:
        return _fail("all nodes must be fixed in z")
    for nid, dofs in support.items():
        if dofs - {1, 2, 3} or (nid == 3 and dofs - {3}):
            return _fail("unexpected support constraints")

    cload = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(cload) != 1:
        return _fail("expected exactly one *Cload line")
    vals = _floats(cload[0])
    if not vals or int(vals[0]) != 3 or int(vals[1]) != 2 or abs(vals[2] - LOAD_FY) > 1e-9:
        return _fail("tip load changed")
    if not any(kw_base(kw) == "*STATIC" for kw, _data in blocks):
        return _fail("missing *Static step")
    return True


# ---------------------------------------------------------------- L3
def _ensure_output_requests(text: str) -> str:
    if "VCAX_ALL_NODES" in text:
        return text
    injection = "*Nset, nset=VCAX_ALL_NODES\n1, 2, 3\n*Node Print, NSET=VCAX_ALL_NODES\nU\n"
    return re.sub(r"(?im)^\*end step\s*$", injection + "*End Step", text, count=1)


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
        u = dat_nodal_u(dat.read_text(errors="ignore"), 3)
        return None if u is None else (u[0], u[1])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- truss theory
def analytic_uy3() -> float:
    length = math.hypot(500.0, 500.0)
    sin45 = 1.0 / math.sqrt(2.0)
    return LOAD_FY * length / (2.0 * E_YOUNG * AREA * sin45**2)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_conformance(inp_text):
        return False

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 2:
        return _fail("summary.txt must be two comma-separated numbers: ux3, uy3")
    try:
        ux_s, uy_s = (float(x) for x in summary)
    except ValueError:
        return _fail("summary.txt values are not numbers")

    resolved = l3_resolve(AGENT_ROOT / "solution.inp")
    if resolved is None:
        return _fail("independent re-solve failed")
    ux, uy = resolved
    if not close_enough(ux_s, ux, RESOLVE_REL_TOL):
        return _fail("ux3 does not match the independent re-solve")
    if not close_enough(uy_s, uy, RESOLVE_REL_TOL):
        return _fail("uy3 does not match the independent re-solve")
    if EXPECTED_UX3 is not None and not close_enough(ux, EXPECTED_UX3, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (ux3)")
    if EXPECTED_UY3 is not None and not close_enough(uy, EXPECTED_UY3, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (uy3)")
    if not close_enough(ux, 0.0, 0.0, abs_tol=1e-9):
        return _fail("ux3 is inconsistent with the symmetric truss")
    if not close_enough(uy, analytic_uy3(), ANALYTIC_REL_TOL):
        return _fail("uy3 is inconsistent with truss theory")
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