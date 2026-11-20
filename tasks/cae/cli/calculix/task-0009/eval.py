#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0009 (mesh-refinement chain).

Implements L1, L2 (two decks), L3 (re-solve both) and L4 (refinement
consistency): the same 3D cantilever is solved on a coarse (20x2x2) and a fine
(40x4x4) C3D8 mesh, and the fine result must be closer to the Euler-Bernoulli
reference while the two results stay in a plausible band of each other.
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

REQUIRED_ARTIFACTS = ["coarse.inp", "coarse.dat", "fine.inp", "fine.dat", "summary.txt"]

LENGTH, WIDTH, HEIGHT = 100.0, 10.0, 10.0
LOAD = -100.0
E_YOUNG, NU = 210000.0, 0.3
GRIDS = {"coarse": (20, 2, 2), "fine": (40, 4, 4)}

EXPECTED_COARSE = None      # pinned from the same VM image (ground_truth/)
EXPECTED_FINE = None

RESOLVE_REL_TOL = 1.0e-4
PINNED_REL_TOL = 1.0e-3
FINE_ANALYTIC_TOL = 5.0e-2
COARSE_ANALYTIC_TOL = 1.5e-1
CROSS_REL_TOL = 2.0e-1
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


def _boundary_lines(blocks, nsets):
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
def dat_center_uy(dat_text: str, node: int) -> float | None:
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
def check_deck(inp_text: str, nx: int, ny: int, nz: int, label: str) -> bool:
    blocks = inp_blocks(inp_text)
    try:
        nodes = _nodes(blocks)
        elements = _elements(blocks)
    except ValueError as exc:
        return _fail(f"{label}: {exc}")

    dx, dy, dz = LENGTH / nx, WIDTH / ny, HEIGHT / nz
    expected = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            for k in range(nz + 1):
                expected[(round(i * dx, 9), round(j * dy, 9), round(k * dz, 9))] = True
    if len(nodes) != len(expected):
        return _fail(f"{label}: expected {len(expected)} nodes, found {len(nodes)}")
    got = {(round(x, 9), round(y, 9), round(z, 9))
           for x, y, z in nodes.values()}
    if got != set(expected):
        return _fail(f"{label}: node coordinates do not match the {nx}x{ny}x{nz} grid")

    if len(elements) != nx * ny * nz:
        return _fail(f"{label}: expected {nx * ny * nz} elements, found {len(elements)}")
    cells = set()
    for eid, (etype, conn) in elements.items():
        if etype != "C3D8":
            return _fail(f"{label}: element {eid} must be type C3D8")
        if len(conn) != 8 or any(n not in nodes for n in conn):
            return _fail(f"{label}: element {eid} has malformed connectivity")
        coords = [nodes[n] for n in conn]
        xs = sorted({round(c[0], 9) for c in coords})
        ys = sorted({round(c[1], 9) for c in coords})
        zs = sorted({round(c[2], 9) for c in coords})
        if (len(xs) != 2 or len(ys) != 2 or len(zs) != 2
                or abs((xs[1] - xs[0]) - dx) > GEOM_ABS_TOL
                or abs((ys[1] - ys[0]) - dy) > GEOM_ABS_TOL
                or abs((zs[1] - zs[0]) - dz) > GEOM_ABS_TOL):
            return _fail(f"{label}: element {eid} is not a grid cube")
        cells.add((xs[0], ys[0], zs[0]))
    if len(cells) != nx * ny * nz:
        return _fail(f"{label}: elements do not cover the grid exactly once")

    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        return _fail(f"{label}: expected exactly one *Elastic")
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        return _fail(f"{label}: material constants changed")

    sets = _elsets(blocks)
    solid = [(kw, data) for kw, data in blocks if kw_base(kw) == "*SOLID SECTION"]
    if len(solid) != 1:
        return _fail(f"{label}: expected exactly one *Solid Section")
    name = kw_param(solid[0][0], "ELSET")
    if set(sets.get((name or "").upper(), [])) != set(elements):
        return _fail(f"{label}: *Solid Section must cover every element")

    left = {nid for nid, (x, _y, _z) in nodes.items() if abs(x) < GEOM_ABS_TOL}
    nsets = _nsets(blocks)
    covered = set()
    for ids, first, last, value in _boundary_lines(blocks, nsets):
        if 1 <= first <= 3 and 1 <= last <= 3 and abs(value) < 1e-12:
            covered.update(ids)
        else:
            return _fail(f"{label}: only the x=0 face may be constrained, in dofs 1-3")
    if covered != left:
        return _fail(f"{label}: the clamped boundary must cover exactly the x=0 face")

    tip = {nid for nid, (x, _y, _z) in nodes.items() if abs(x - LENGTH) < GEOM_ABS_TOL}
    if len(tip) != (ny + 1) * (nz + 1):
        return _fail(f"{label}: tip face must contain {(ny + 1) * (nz + 1)} nodes")
    each = LOAD / len(tip)
    loads = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(loads) != len(tip):
        return _fail(f"{label}: expected {len(tip)} *Cload lines")
    seen = set()
    for line in loads:
        vals = _floats(line)
        if not vals or len(vals) != 3:
            return _fail(f"{label}: malformed *Cload line")
        nid, dof, value = int(vals[0]), int(vals[1]), vals[2]
        if nid not in tip or dof != 2 or abs(value - each) > 1e-9:
            return _fail(f"{label}: tip load must be {each} N on every tip node, dof 2")
        seen.add(nid)
    if seen != tip:
        return _fail(f"{label}: tip load must cover every tip node exactly once")
    if any(kw_base(kw) in ("*DLOAD", "*FREQUENCY", "*BUCKLE") for kw, _data in blocks):
        return _fail(f"{label}: only a static *Cload analysis is allowed")
    return any(kw_base(kw) == "*STATIC" for kw, _data in blocks)


# ---------------------------------------------------------------- L3
def _ensure_output_requests(text: str) -> str:
    blocks = inp_blocks(text)
    if any(kw_base(kw) == "*NODE PRINT" for kw, _data in blocks):
        return text
    try:
        nodes = _nodes(blocks)
    except ValueError:
        return text
    ids = sorted(nodes)
    injection = ("*Nset, nset=VCAX_ALL_NODES\n"
                 + "\n".join(", ".join(str(n) for n in ids[i:i + 16])
                             for i in range(0, len(ids), 16))
                 + "\n*Node Print, NSET=VCAX_ALL_NODES\nU\n")
    return re.sub(r"(?im)^\*end step\s*$", injection + "*End Step", text, count=1)


def resolve(path: Path) -> float | None:
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        text = _ensure_output_requests(path.read_text(errors="ignore"))
        (scratch / "job.inp").write_text(text)
        subprocess.run([CCX, "job"], cwd=scratch, timeout=300, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "job.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            return None
        blocks = inp_blocks(text)
        nodes = _nodes(blocks)
        center = next((nid for nid, (x, y, z) in nodes.items()
                       if abs(x - LENGTH) < GEOM_ABS_TOL
                       and abs(y - WIDTH / 2) < GEOM_ABS_TOL
                       and abs(z - HEIGHT / 2) < GEOM_ABS_TOL), None)
        if center is None:
            return None
        return dat_center_uy(dat.read_text(errors="ignore"), center)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- beam theory
def analytic_tip_uy() -> float:
    inertia = WIDTH * HEIGHT**3 / 12.0
    return LOAD * LENGTH**3 / (3.0 * E_YOUNG * inertia)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    coarse_inp = (AGENT_ROOT / "coarse.inp").read_text(errors="ignore")
    fine_inp = (AGENT_ROOT / "fine.inp").read_text(errors="ignore")
    if not check_deck(coarse_inp, *GRIDS["coarse"], "coarse"):
        return False
    if not check_deck(fine_inp, *GRIDS["fine"], "fine"):
        return False

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 2:
        return _fail("summary.txt must be two comma-separated numbers: coarse_tip_uy, fine_tip_uy")
    try:
        coarse_s, fine_s = (float(x) for x in summary)
    except ValueError:
        return _fail("summary.txt values are not numbers")

    coarse = resolve(AGENT_ROOT / "coarse.inp")
    fine = resolve(AGENT_ROOT / "fine.inp")
    if coarse is None or fine is None:
        return _fail("independent re-solve failed on one of the decks")
    if not close_enough(coarse_s, coarse, RESOLVE_REL_TOL):
        return _fail("coarse_tip_uy does not match the independent re-solve")
    if not close_enough(fine_s, fine, RESOLVE_REL_TOL):
        return _fail("fine_tip_uy does not match the independent re-solve")

    if EXPECTED_COARSE is not None and not close_enough(coarse, EXPECTED_COARSE, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (coarse)")
    if EXPECTED_FINE is not None and not close_enough(fine, EXPECTED_FINE, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (fine)")

    analytic = analytic_tip_uy()
    if not close_enough(fine, analytic, FINE_ANALYTIC_TOL):
        return _fail("fine mesh is not within 5% of beam theory")
    if not close_enough(coarse, analytic, COARSE_ANALYTIC_TOL):
        return _fail("coarse mesh is not within 15% of beam theory")
    if abs(fine - analytic) >= abs(coarse - analytic):
        return _fail("refinement did not move the result toward beam theory")
    if not close_enough(coarse, fine, CROSS_REL_TOL):
        return _fail("coarse and fine results are not in the same 20% band")
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