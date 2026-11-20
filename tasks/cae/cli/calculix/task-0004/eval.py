#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0004 (thick cylinder, Lamé).

Implements L1 (completeness), L2 (design conformance) and L3 (independent
re-solve). L3 runs the submitted deck through the VM's own ccx in a scratch
directory; the verdict is anchored to physics, never to the agent's claims.

Problem: plane-strain slice of a thick-walled cylinder (ri=10, ro=20) under
50 MPa internal pressure. Two NODAL radial displacements (inner and outer
surface) are the reported quantities; they converge with mesh refinement and
have a closed-form Lamé reference.

Three-way check:
  A  agent's summary.txt
  B  verifier's independent re-solve of the submitted deck   (tight)
  C  pinned reference values from the same image             (tight)
plus a loose plane-strain Lamé band (physics net).
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

# ---- pinned design (task-0004 instruction) ----
RI, RO, HEIGHT = 10.0, 20.0, 1.0
N_RADIAL = 20
PRESSURE = 50.0
E_YOUNG, NU = 210000.0, 0.3

# ---- pinned reference, filled from the same VM image (ground_truth/) ----
EXPECTED_UR_INNER = None   # pinned from the same VM image (ground_truth/)
EXPECTED_UR_OUTER = None   # pinned from the same VM image (ground_truth/)

RESOLVE_REL_TOL = 1.0e-4    # A vs B: same deck, same solver
PINNED_REL_TOL = 1.0e-3     # B vs C: solver-setting noise only
ANALYTIC_REL_TOL = 2.0e-2   # B vs Lamé: converged 20-element mesh
GEOM_ABS_TOL = 1.0e-6


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


def _nsets(blocks) -> dict[str, list[int]]:
    sets: dict[str, list[int]] = {}
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
    nodes: dict[int, tuple[float, float, float]] = {}
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
    elements: dict[int, tuple[str, list[int]]] = {}
    for kw, data in blocks:
        base = kw_base(kw)
        if not base.startswith("*ELEMENT"):
            continue
        etype = kw_param(kw, "TYPE") or ""
        for line in data:
            vals = _floats(line)
            if not vals:
                continue
            elements[int(vals[0])] = (etype.upper(), [int(v) for v in vals[1:]])
    return elements


def _boundary_lines(blocks, nsets: dict[str, list[int]]):
    """Yield (node_ids, first_dof, last_dof, value) for every *Boundary line."""
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
            yield ids, first, last, value


# ---------------------------------------------------------------- .dat parsing
def dat_nodal_u(dat_text: str, node: int) -> float | None:
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
                    return float(p[1])  # radial component
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

    expected = {}
    for i in range(N_RADIAL + 1):
        r = RI + (RO - RI) * i / N_RADIAL
        for j in range(2):
            expected[(round(r, 9), float(j))] = True
    if len(nodes) != len(expected):
        return _fail(f"expected {len(expected)} nodes, found {len(nodes)}")
    got = {}
    for nid, (x, y, z) in nodes.items():
        got[(round(x, 9), round(y, 9))] = True
        if abs(z) > GEOM_ABS_TOL:
            return _fail("2D axisymmetric nodes must lie in the z=0 plane")
    if set(got) != set(expected):
        return _fail("node coordinates do not match the 21 x 2 radial grid")

    if len(elements) != N_RADIAL:
        return _fail(f"expected {N_RADIAL} elements, found {len(elements)}")
    spans = []
    for eid, (etype, conn) in elements.items():
        if etype != "CAX4":
            return _fail(f"element {eid} must be type CAX4")
        if len(conn) != 4 or any(n not in nodes for n in conn):
            return _fail(f"element {eid} has malformed connectivity")
        coords = [nodes[n] for n in conn]
        rs = sorted({round(c[0], 9) for c in coords})
        zs = sorted({round(c[1], 9) for c in coords})
        if len(rs) != 2 or len(zs) != 2:
            return _fail(f"element {eid} is not an axisymmetric rectangle")
        if abs((rs[1] - rs[0]) - (RO - RI) / N_RADIAL) > 1e-6:
            return _fail(f"element {eid} does not span one radial station")
        if abs(zs[0]) > 1e-9 or abs(zs[1] - HEIGHT) > 1e-9:
            return _fail(f"element {eid} must span the axial direction in [0, 1]")
        spans.append(rs[0])
    if sorted(round(s, 9) for s in spans) != [round(RI + (RO - RI) * i / N_RADIAL, 9)
                                              for i in range(N_RADIAL)]:
        return _fail("elements do not cover the 20 radial stations exactly once")

    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        return _fail("expected exactly one *Elastic")
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        return _fail("material constants changed")

    sets = _elsets(blocks)
    solid = [(kw, data) for kw, data in blocks if kw_base(kw) == "*SOLID SECTION"]
    if len(solid) != 1:
        return _fail("expected exactly one *Solid Section")
    name = kw_param(solid[0][0], "ELSET")
    members = set(sets.get((name or "").upper(), []))
    if members != set(elements):
        return _fail("*Solid Section must cover every element")

    # plane strain: every node must be fixed in the axial dof (2), and no
    # radial displacement may be constrained
    nsets = _nsets(blocks)
    covered: set[int] = set()
    for ids, first, last, _value in _boundary_lines(blocks, nsets):
        if first <= 1 <= last:
            return _fail("radial displacement must not be constrained")
        if first <= 2 <= last:
            covered.update(ids)
    if covered != set(nodes):
        return _fail("every node must be constrained in the axial dof (2)")

    # pressure only on the innermost radial layer, positive inward
    inner = {eid for eid, (_etype, conn) in elements.items()
             if min(nodes[n][0] for n in conn) < RI + 1e-9}
    if len(inner) != 1:
        return _fail("expected exactly one element touching the inner surface")
    loads = [(kw, data) for kw, data in blocks if kw_base(kw) in ("*DLOAD", "*CLOAD")]
    if len(loads) != 1 or kw_base(loads[0][0]) != "*DLOAD":
        return _fail("expected exactly one *Dload card and no *Cload")
    load_ok = False
    for line in loads[0][1]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        set_name = parts[0].upper()
        if set(sets.get(set_name, [])) == inner and parts[1].upper() == "P4":
            try:
                load_ok = abs(float(parts[2]) - PRESSURE) < 1e-9
            except ValueError:
                load_ok = False
    if not load_ok:
        return _fail("internal pressure must be 50 MPa on face P4 of the inner element")
    return True


# ---------------------------------------------------------------- L3
def _ensure_output_requests(text: str) -> str:
    if "VCAX_ALL_NODES" in text:
        return text
    blocks = inp_blocks(text)
    try:
        nodes = _nodes(blocks)
    except ValueError:
        return text
    ids = sorted(nodes)
    lines = ["*Nset, nset=VCAX_ALL_NODES"]
    for i in range(0, len(ids), 16):
        lines.append(", ".join(str(n) for n in ids[i:i + 16]))
    lines += ["*Node Print, NSET=VCAX_ALL_NODES", "U"]
    injection = "\n".join(lines) + "\n"
    return re.sub(r"(?im)^\*end step\s*$", injection + "*End Step", text, count=1)


def l3_resolve(inp_path: Path) -> tuple[float | None, float | None] | None:
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        text = _ensure_output_requests(inp_path.read_text(errors="ignore"))
        (scratch / "solution.inp").write_text(text)
        subprocess.run([CCX, "solution"], cwd=scratch, timeout=300, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "solution.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            return None
        dat_text = dat.read_text(errors="ignore")
        # locate the inner/outer node ids from the deck's coordinates
        blocks = inp_blocks(text)
        nodes = _nodes(blocks)
        inner_node = next((n for n, c in nodes.items() if abs(c[0] - RI) < 1e-9 and abs(c[1]) < 1e-9), None)
        outer_node = next((n for n, c in nodes.items() if abs(c[0] - RO) < 1e-9 and abs(c[1]) < 1e-9), None)
        if inner_node is None or outer_node is None:
            return None
        return dat_nodal_u(dat_text, inner_node), dat_nodal_u(dat_text, outer_node)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- Lamé net
def analytic_ur(r: float) -> float:
    """Plane-strain Lamé radial displacement at radius r (mm)."""
    c1 = PRESSURE * RI**2 / (RO**2 - RI**2)
    c2 = PRESSURE * RI**2 * RO**2 / (RO**2 - RI**2)
    return (1.0 + NU) / E_YOUNG * ((1.0 - 2.0 * NU) * c1 * r + c2 / r)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_conformance(inp_text):
        return False

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 2:
        return _fail("summary.txt must be two comma-separated floats: ur_inner, ur_outer")
    try:
        ur_inner_s, ur_outer_s = (float(x) for x in summary)
    except ValueError:
        return _fail("summary.txt values are not numbers")

    resolved = l3_resolve(AGENT_ROOT / "solution.inp")
    if resolved is None or resolved[0] is None or resolved[1] is None:
        return _fail("independent re-solve failed to produce results")
    ur_inner, ur_outer = resolved

    if not close_enough(ur_inner_s, ur_inner, RESOLVE_REL_TOL):
        return _fail("ur_inner does not match the independent re-solve of solution.inp")
    if not close_enough(ur_outer_s, ur_outer, RESOLVE_REL_TOL):
        return _fail("ur_outer does not match the independent re-solve of solution.inp")

    if EXPECTED_UR_INNER is not None and not close_enough(ur_inner, EXPECTED_UR_INNER, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (ur_inner)")
    if EXPECTED_UR_OUTER is not None and not close_enough(ur_outer, EXPECTED_UR_OUTER, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (ur_outer)")

    if not close_enough(ur_inner, analytic_ur(RI), ANALYTIC_REL_TOL):
        return _fail("ur_inner inconsistent with the plane-strain Lamé solution")
    if not close_enough(ur_outer, analytic_ur(RO), ANALYTIC_REL_TOL):
        return _fail("ur_outer inconsistent with the plane-strain Lamé solution")
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