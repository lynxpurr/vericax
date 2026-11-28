#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0010 (beam vs solid).

Cross-stage/two-artifact consistency: the same uniform cantilever (100 x 10 x
10 mm, -100 N tip load) is delivered twice, as a 10-element B31 beam and as a
40 x 4 x 4 C3D8 solid. Both decks are checked and re-solved; the two tip
deflections must agree within 5% and with beam theory.

Implements L1, L2 (both decks), L3 (re-solve both) and L4 (cross-model).
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

REQUIRED_ARTIFACTS = ["beam.inp", "beam.dat", "solid.inp", "solid.dat", "summary.txt"]
LENGTH, WIDTH, HEIGHT = 100.0, 10.0, 10.0
LOAD = -100.0
E_YOUNG, NU = 210000.0, 0.3
NX, NY, NZ = 40, 4, 4
BEAM_N = 10

EXPECTED_BEAM = None
EXPECTED_SOLID = None

RESOLVE_REL_TOL = 1.0e-4
PINNED_REL_TOL = 1.0e-3
ANALYTIC_REL_TOL = 5.0e-2
CROSS_REL_TOL = 5.0e-2
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

# ---------------------------------------------------------------- parsing
def inp_blocks(text: str) -> list[tuple[str, list[str]]]:
    text = canonical_deck(text)
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


# ---------------------------------------------------------------- beam deck
def check_beam(text: str) -> bool:
    blocks = inp_blocks(text)
    try:
        nodes = _nodes(blocks)
        elements = _elements(blocks)
    except ValueError as exc:
        return _fail(f"beam: {exc}")
    if set(nodes) != set(range(1, BEAM_N + 2)):
        return _fail("beam: expected nodes 1..11")
    for i in range(1, BEAM_N + 2):
        expected = (10.0 * (i - 1), 0.0, 0.0)
        if not all(close_enough(g, e, 0.0, abs_tol=1e-6) for g, e in zip(nodes[i], expected)):
            return _fail(f"beam: node {i} coordinates changed")
    if len(elements) != BEAM_N:
        return _fail("beam: expected 10 elements")
    conns = []
    for eid, (etype, conn) in elements.items():
        if etype != "B31" or len(conn) != 2:
            return _fail(f"beam: element {eid} must be B31")
        conns.append(tuple(sorted(conn)))
    if sorted(conns) != sorted((e, e + 1) for e in range(1, BEAM_N + 1)):
        return _fail("beam: element e must join nodes e and e+1")
    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        return _fail("beam: expected one *Elastic")
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        return _fail("beam: material changed")
    sets = _elsets(blocks)
    sec = [(kw, data) for kw, data in blocks if kw_base(kw).startswith("*BEAM SECTION")]
    if len(sec) != 1:
        return _fail("beam: expected one *Beam Section")
    name = kw_param(sec[0][0], "ELSET")
    if set(sets.get((name or "").upper(), [])) != set(range(1, BEAM_N + 1)):
        return _fail("beam: section must cover all elements")
    vals = _floats(sec[0][1][0]) if sec[0][1] else None
    if not vals or abs(vals[0] - 10.0) > 1e-9 or abs(vals[1] - 10.0) > 1e-9:
        return _fail("beam: section must be 10 x 10")
    bcl = [l for kw, data in blocks if kw_base(kw) == "*BOUNDARY" for l in data]
    if not any((v := _floats(l)) and int(v[0]) == 1 and int(v[1]) == 1 and int(v[2]) == 6 for l in bcl):
        return _fail("beam: root clamp missing")
    cl = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(cl) != 1:
        return _fail("beam: expected one *Cload")
    vals = _floats(cl[0])
    if not vals or int(vals[0]) != BEAM_N + 1 or int(vals[1]) != 2 or abs(vals[2] - LOAD) > 1e-9:
        return _fail("beam: tip load changed")
    return any(kw_base(kw) == "*STATIC" for kw, _data in blocks)


# ---------------------------------------------------------------- solid deck
def check_solid(text: str) -> bool:
    blocks = inp_blocks(text)
    try:
        nodes = _nodes(blocks)
        elements = _elements(blocks)
    except ValueError as exc:
        return _fail(f"solid: {exc}")
    dx, dy, dz = LENGTH / NX, WIDTH / NY, HEIGHT / NZ
    expected = {}
    for i in range(NX + 1):
        for j in range(NY + 1):
            for k in range(NZ + 1):
                expected[(round(i * dx, 9), round(j * dy, 9), round(k * dz, 9))] = True
    if len(nodes) != len(expected):
        return _fail(f"solid: expected {len(expected)} nodes")
    got = {(round(x, 9), round(y, 9), round(z, 9)) for x, y, z in nodes.values()}
    if got != set(expected):
        return _fail("solid: node grid changed")
    if len(elements) != NX * NY * NZ:
        return _fail("solid: expected 640 elements")
    cells = set()
    for eid, (etype, conn) in elements.items():
        if etype != "C3D8" or len(conn) != 8 or any(n not in nodes for n in conn):
            return _fail(f"solid: element {eid} must be C3D8")
        coords = [nodes[n] for n in conn]
        xs = sorted({round(c[0], 9) for c in coords})
        ys = sorted({round(c[1], 9) for c in coords})
        zs = sorted({round(c[2], 9) for c in coords})
        if (len(xs) != 2 or len(ys) != 2 or len(zs) != 2
                or abs((xs[1] - xs[0]) - dx) > GEOM_ABS_TOL
                or abs((ys[1] - ys[0]) - dy) > GEOM_ABS_TOL
                or abs((zs[1] - zs[0]) - dz) > GEOM_ABS_TOL):
            return _fail(f"solid: element {eid} is not a grid cube")
        cells.add((xs[0], ys[0], zs[0]))
    if len(cells) != NX * NY * NZ:
        return _fail("solid: elements do not cover the grid")
    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        return _fail("solid: expected one *Elastic")
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        return _fail("solid: material changed")
    sets = _elsets(blocks)
    solid_sec = [(kw, data) for kw, data in blocks if kw_base(kw) == "*SOLID SECTION"]
    if len(solid_sec) != 1:
        return _fail("solid: expected one *Solid Section")
    name = kw_param(solid_sec[0][0], "ELSET")
    if set(sets.get((name or "").upper(), [])) != set(elements):
        return _fail("solid: section must cover all elements")
    left = {n for n, (x, _y, _z) in nodes.items() if abs(x) < GEOM_ABS_TOL}
    nsets = _nsets(blocks)
    covered = set()
    for ids, first, last, value in _boundary_lines(blocks, nsets):
        if 1 <= first <= 3 and 1 <= last <= 3 and abs(value) < 1e-12:
            covered.update(ids)
        else:
            return _fail("solid: only the x=0 face may be constrained")
    if covered != left:
        return _fail("solid: clamp must cover the x=0 face")
    tip = {n for n, (x, _y, _z) in nodes.items() if abs(x - LENGTH) < GEOM_ABS_TOL}
    loads = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(loads) != len(tip):
        return _fail("solid: expected one *Cload per tip node")
    each = LOAD / len(tip)
    seen = set()
    for line in loads:
        vals = _floats(line)
        if not vals or len(vals) != 3:
            return _fail("solid: malformed *Cload")
        nid, dof, value = int(vals[0]), int(vals[1]), vals[2]
        if nid not in tip or dof != 2 or abs(value - each) > 1e-9:
            return _fail("solid: tip load must be equal on every tip node")
        seen.add(nid)
    if seen != tip:
        return _fail("solid: tip load must cover every tip node")
    return any(kw_base(kw) == "*STATIC" for kw, _data in blocks)


# ---------------------------------------------------------------- L3
def _ensure_output_requests(text: str) -> str:
    blocks = inp_blocks(text)
    if any(kw_base(kw) == "*NODE PRINT" for kw, _data in blocks):
        return text
    ids = sorted({int(_floats(l)[0]) for kw, data in blocks
                  if kw_base(kw) == "*NODE" for l in data if _floats(l)})
    injection = ("*Nset, nset=VCAX_ALL_NODES\n"
                 + "\n".join(", ".join(str(n) for n in ids[i:i + 16])
                             for i in range(0, len(ids), 16))
                 + "\n*Node Print, NSET=VCAX_ALL_NODES\nU\n")
    return re.sub(r"(?im)^\*end step\s*$", injection + "*End Step", text, count=1)


def resolve(path: Path, kind: str) -> float | None:
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
        if kind == "beam":
            return dat_nodal_u(dat.read_text(errors="ignore"), BEAM_N + 1)[1] \
                if dat_nodal_u(dat.read_text(errors="ignore"), BEAM_N + 1) else None
        center = next((nid for nid, (x, y, z) in nodes.items()
                       if abs(x - LENGTH) < GEOM_ABS_TOL
                       and abs(y - WIDTH / 2) < GEOM_ABS_TOL
                       and abs(z - HEIGHT / 2) < GEOM_ABS_TOL), None)
        if center is None:
            return None
        u = dat_nodal_u(dat.read_text(errors="ignore"), center)
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
    if not check_beam((AGENT_ROOT / "beam.inp").read_text(errors="ignore")):
        return False
    if not check_solid((AGENT_ROOT / "solid.inp").read_text(errors="ignore")):
        return False

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 2:
        return _fail("summary.txt must be two numbers: beam_tip_uy, solid_tip_uy")
    try:
        beam_s, solid_s = (float(x) for x in summary)
    except ValueError:
        return _fail("summary.txt values are not numbers")

    beam = resolve(AGENT_ROOT / "beam.inp", "beam")
    solid = resolve(AGENT_ROOT / "solid.inp", "solid")
    if beam is None or solid is None:
        return _fail("independent re-solve failed on one deck")
    if not close_enough(beam_s, beam, RESOLVE_REL_TOL):
        return _fail("beam_tip_uy does not match the independent re-solve")
    if not close_enough(solid_s, solid, RESOLVE_REL_TOL):
        return _fail("solid_tip_uy does not match the independent re-solve")
    if EXPECTED_BEAM is not None and not close_enough(beam, EXPECTED_BEAM, PINNED_REL_TOL):
        return _fail("beam re-solve deviates from pinned reference")
    if EXPECTED_SOLID is not None and not close_enough(solid, EXPECTED_SOLID, PINNED_REL_TOL):
        return _fail("solid re-solve deviates from pinned reference")

    analytic = analytic_tip_uy()
    if not close_enough(beam, analytic, ANALYTIC_REL_TOL):
        return _fail("beam result is not within 5% of beam theory")
    if not close_enough(solid, analytic, ANALYTIC_REL_TOL):
        return _fail("solid result is not within 5% of beam theory")
    if not close_enough(beam, solid, CROSS_REL_TOL):
        return _fail("beam and solid results differ by more than 5%")
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