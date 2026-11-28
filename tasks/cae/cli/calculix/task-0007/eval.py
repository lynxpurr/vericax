#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0007 (3D solid cantilever).

Implements L1 (completeness), L2 (design conformance) and L3 (independent
re-solve). L3 runs the submitted deck through the VM's own ccx and reads the
center tip displacement from `.dat`; the verdict is anchored to the solver
output, never to the agent's claims.

Problem: 3D cantilever block 100 x 10 x 10 mm, 40 x 4 x 4 C3D8 elements,
clamped at x=0, tip load -100 N in y distributed equally over the x=100 face.

Three-way check:
  A  agent's summary.txt                  (tip uy at the face center)
  B  verifier's independent re-solve      (tight)
  C  pinned reference from the same image (tight)
plus a loose Euler-Bernoulli band (physics net).
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

# ---- pinned design (task instruction) ----
LENGTH, WIDTH, HEIGHT = 100.0, 10.0, 10.0
NX, NY, NZ = 40, 4, 4
DX, DY, DZ = LENGTH / NX, WIDTH / NY, HEIGHT / NZ
N_NODES = (NX + 1) * (NY + 1) * (NZ + 1)
N_ELEM = NX * NY * NZ
TIP_NODES = (NY + 1) * (NZ + 1)
LOAD = -100.0
E_YOUNG, NU = 210000.0, 0.3

# ---- pinned reference, filled from the same VM image (ground_truth/) ----
EXPECTED_TIP_UY = None      # pinned from the same VM image (ground_truth/)

RESOLVE_REL_TOL = 1.0e-4    # A vs B: same deck, same solver
PINNED_REL_TOL = 1.0e-3     # B vs C: solver-setting noise only
ANALYTIC_REL_TOL = 5.0e-2   # B vs Euler-Bernoulli (solid is 3.5% below)
GEOM_ABS_TOL = 1.0e-6


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-12) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * abs(target))


# ---- deck spellings: copied verbatim from scripts/deck_canonical.py (tests/test_deck_spellings.py checks the copy) ----
def canonical_deck(text: str) -> str:
    """Rewrite the legal spellings a verifier may not read into the ones it does.

    CalculiX accepts several spellings of the same deck (spec/02 section 5:
    equivalent spellings must all be accepted). This keeps the model data and
    rewrites only what follows:
    - a data line that ends with a comma is joined with the data line that
      follows, or loses the comma before a keyword;
    - a node line with two coordinates gets the third, 0.0;
    - an element or node set written with GENERATE (first, last, step) is
      written as a full list;
    - a *BOUNDARY row that names a node set becomes one row per member node,
      and the optional last degree of freedom and value are written out;
    - a *DLOAD, *DSLOAD or *CLOAD row that names a set becomes one row per
      member.

    One function, standard library only. Every deck verifier carries a copy
    of it between two marker lines; scripts/deck_canonical.py is the source
    and tests/test_deck_spellings.py checks that the copies match it.
    """
    import re

    def is_int(token):
        t = token.strip()
        return t.lstrip("+-").isdigit() and len(t) > (1 if t[0] in "+-" else 0)

    def tokens(line):
        return [t.strip() for t in line.split(",") if t.strip()]

    def is_keyword(line):
        s = line.strip()
        return s.startswith("*") and not s.startswith("**")

    def is_noise(line):
        s = line.strip()
        return not s or s.startswith("**")

    def base(line):
        return line.strip().split(",")[0].strip().upper()

    def has_flag(keyword_line, flag):
        return any(p.strip() == flag for p in keyword_line.upper().split(",")[1:])

    def param(keyword_line, name):
        m = re.search(name + r"\s*=\s*([A-Za-z0-9_.-]+)", keyword_line.upper())
        return m.group(1).upper() if m else None

    def cards(lines):
        card, start, data = None, None, []
        for i, line in enumerate(lines):
            if is_keyword(line):
                if card is not None:
                    yield card, start, data
                card, start, data = base(line), i, []
            elif card is not None and not is_noise(line):
                data.append(i)
        if card is not None:
            yield card, start, data

    lines = text.splitlines()
    # a data line that ends with a comma continues in the next data line; the
    # comma stays as the separator between the two parts
    joined = []
    pending = None
    for line in lines:
        stripped = line.rstrip()
        if pending is not None:
            if not is_noise(line) and not is_keyword(line):
                pending = pending[:-1].rstrip() + ", " + line.strip()
                if pending.endswith(","):
                    continue
                joined.append(pending)
                pending = None
                continue
            joined.append(pending[:-1].rstrip())
            pending = None
        if not is_keyword(line) and not is_noise(line) and stripped.endswith(","):
            pending = stripped
            continue
        joined.append(line)
    if pending is not None:
        joined.append(pending[:-1].rstrip())
    lines = joined

    elsets, nsets = {}, {}
    for card, start, data in cards(lines):
        kw = lines[start]
        if card in ("*ELSET", "*NSET"):
            name = param(kw, "ELSET" if card == "*ELSET" else "NSET")
            if not name:
                continue
            store = elsets if card == "*ELSET" else nsets
            ids = []
            for i in data:
                toks = tokens(lines[i])
                if toks and all(is_int(t) for t in toks):
                    ids += [int(t) for t in toks]
            if has_flag(kw, "GENERATE") and len(ids) == 3 and ids[2] > 0:
                store[name] = list(range(ids[0], ids[1] + 1, ids[2]))
            else:
                store.setdefault(name, []).extend(ids)
        elif card in ("*ELEMENT", "*NODE"):
            name = param(kw, "ELSET" if card == "*ELEMENT" else "NSET")
            if name:
                store = elsets if card == "*ELEMENT" else nsets
                for i in data:
                    toks = tokens(lines[i])
                    if toks and is_int(toks[0]):
                        store.setdefault(name, []).append(int(toks[0]))

    out = []
    for card, start, data in cards(lines):
        out.append(lines[start])
        kw = lines[start]
        if card in ("*ELSET", "*NSET") and has_flag(kw, "GENERATE") and data:
            name = param(kw, "ELSET" if card == "*ELSET" else "NSET")
            ids = (elsets if card == "*ELSET" else nsets).get(name or "", [])
            out[-1] = ", ".join(p.strip() for p in kw.split(",") if p.strip().upper() != "GENERATE")
            for k in range(0, len(ids), 16):
                out.append(", ".join(str(i) for i in ids[k:k + 16]))
            continue
        # a set declared on the *NODE or *ELEMENT card gets a card of its own after the data
        declared = None
        if card in ("*NODE", "*ELEMENT") and data:
            key = "NSET" if card == "*NODE" else "ELSET"
            name = param(kw, key)
            if name:
                declared = (key, name)
                out[-1] = ", ".join(p.strip() for p in kw.split(",")
                                    if p.strip() and not p.strip().upper().startswith(key))
        for i in data:
            line = lines[i]
            toks = tokens(line)
            if card == "*NODE" and len(toks) == 3 and is_int(toks[0]):
                out.append(line.rstrip() + ", 0.0")
            elif card == "*BOUNDARY" and toks and toks[0].upper() in nsets:
                for node in nsets[toks[0].upper()]:
                    row = [str(node)] + toks[1:]
                    if len(row) == 2:
                        row += [row[1], "0.0"]
                    elif len(row) == 3:
                        row += ["0.0"]
                    out.append(", ".join(row))
            elif card in ("*DLOAD", "*DSLOAD", "*CLOAD") and toks and toks[0].upper() in (
                    elsets if card != "*CLOAD" else nsets):
                members = (elsets if card != "*CLOAD" else nsets)[toks[0].upper()]
                out += [", ".join([str(m)] + toks[1:]) for m in members]
            else:
                out.append(line)
        if declared:
            ids = (nsets if declared[0] == "NSET" else elsets).get(declared[1], [])
            out.append("*{}, {}={}".format("Nset" if declared[0] == "NSET" else "Elset",
                                           declared[0].lower(), declared[1]))
            for k in range(0, len(ids), 16):
                out.append(", ".join(str(i) for i in ids[k:k + 16]))
    return "\n".join(out) + "\n"
# ---- end of the copied block ----

# ---------------------------------------------------------------- deck parsing
def inp_blocks(text: str) -> list[tuple[str, list[str]]]:
    text = canonical_deck(text)
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
        etype = (kw_param(kw, "TYPE") or "").upper()
        for line in data:
            vals = _floats(line)
            if not vals:
                continue
            elements[int(vals[0])] = (etype, [int(v) for v in vals[1:]])
    return elements


def _boundary_lines(blocks, nsets: dict[str, list[int]]):
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

    expected = {}
    for i in range(NX + 1):
        for j in range(NY + 1):
            for k in range(NZ + 1):
                expected[(round(i * DX, 9), round(j * DY, 9), round(k * DZ, 9))] = True
    if len(nodes) != N_NODES:
        return _fail(f"expected {N_NODES} nodes, found {len(nodes)}")
    got = {}
    for _nid, (x, y, z) in nodes.items():
        got[(round(x, 9), round(y, 9), round(z, 9))] = True
    if set(got) != set(expected):
        return _fail("node coordinates do not match the 41 x 5 x 5 grid")

    if len(elements) != N_ELEM:
        return _fail(f"expected {N_ELEM} elements, found {len(elements)}")
    cells = set()
    for eid, (etype, conn) in elements.items():
        if etype != "C3D8":
            return _fail(f"element {eid} must be type C3D8")
        if len(conn) != 8 or any(n not in nodes for n in conn):
            return _fail(f"element {eid} has malformed connectivity")
        coords = [nodes[n] for n in conn]
        xs = sorted({round(c[0], 9) for c in coords})
        ys = sorted({round(c[1], 9) for c in coords})
        zs = sorted({round(c[2], 9) for c in coords})
        if (len(xs) != 2 or len(ys) != 2 or len(zs) != 2
                or abs((xs[1] - xs[0]) - DX) > GEOM_ABS_TOL
                or abs((ys[1] - ys[0]) - DY) > GEOM_ABS_TOL
                or abs((zs[1] - zs[0]) - DZ) > GEOM_ABS_TOL):
            return _fail(f"element {eid} is not a 2.5 mm cube of the grid")
        cells.add((round(xs[0], 9), round(ys[0], 9), round(zs[0], 9)))
    if len(cells) != N_ELEM:
        return _fail("elements do not cover the 40 x 4 x 4 grid exactly once")

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
    if set(sets.get((name or "").upper(), [])) != set(elements):
        return _fail("*Solid Section must cover every element")

    # clamp only the x=0 face, all three dofs
    left = {nid for nid, (x, _y, _z) in nodes.items() if abs(x) < GEOM_ABS_TOL}
    nsets = _nsets(blocks)
    covered: set[int] = set()
    for ids, first, last, value in _boundary_lines(blocks, nsets):
        if 1 <= first <= 3 and 1 <= last <= 3 and abs(value) < 1e-12:
            covered.update(ids)
        else:
            return _fail("only the x=0 face may be constrained, in dofs 1-3")
    if covered != left:
        return _fail("the clamped boundary must cover exactly the x=0 face")

    # equal tip load: 25 nodes at x=100, dof 2, total -100 N
    tip = {nid for nid, (x, _y, _z) in nodes.items() if abs(x - LENGTH) < GEOM_ABS_TOL}
    if len(tip) != TIP_NODES:
        return _fail("tip face must contain 25 nodes")
    loads = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(loads) != TIP_NODES:
        return _fail(f"expected {TIP_NODES} *Cload lines on the tip face")
    seen = set()
    for line in loads:
        vals = _floats(line)
        if not vals or len(vals) != 3:
            return _fail(f"malformed *Cload line: {line}")
        nid, dof, value = int(vals[0]), int(vals[1]), vals[2]
        if nid not in tip or dof != 2:
            return _fail("every *Cload must target a tip node in dof 2")
        if abs(value - LOAD / TIP_NODES) > 1e-9:
            return _fail("the tip load must be equally divided over the 25 tip nodes")
        seen.add(nid)
    if seen != tip:
        return _fail("the tip load must cover every tip node exactly once")

    if any(kw_base(kw) in ("*DLOAD", "*FREQUENCY", "*BUCKLE") for kw, _data in blocks):
        return _fail("only a static *Cload analysis is allowed")
    if not any(kw_base(kw) == "*STATIC" for kw, _data in blocks):
        return _fail("missing *Static step")
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
        dat_text = dat.read_text(errors="ignore")
        blocks = inp_blocks(text)
        nodes = _nodes(blocks)
        center = next((nid for nid, (x, y, z) in nodes.items()
                       if abs(x - LENGTH) < GEOM_ABS_TOL
                       and abs(y - WIDTH / 2) < GEOM_ABS_TOL
                       and abs(z - HEIGHT / 2) < GEOM_ABS_TOL), None)
        if center is None:
            return None
        u = dat_nodal_u(dat_text, center)
        return None if u is None else u[1]
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
        return _fail("independent re-solve failed to produce a tip displacement")
    if not close_enough(tip_s, tip, RESOLVE_REL_TOL):
        return _fail("tip_uy does not match the independent re-solve of solution.inp")
    if EXPECTED_TIP_UY is not None and not close_enough(tip, EXPECTED_TIP_UY, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (tip_uy)")
    if not close_enough(tip, analytic_tip_uy(), ANALYTIC_REL_TOL):
        return _fail("tip_uy inconsistent with Euler-Bernoulli beam theory")
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