#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0014 (frequency, static, buckle).

One CalculiX deck, three steps, five numbers that depend on each other:
  step 1  *FREQUENCY  first two eigenfrequencies of the unloaded column -> f1, f2 [Hz]
  step 2  *STATIC     unit compressive load (-1 N, dof 1) at TIP       -> ux2 [mm]
  step 3  *BUCKLE     first two buckling factors under that unit load   -> lam1, lam2 [N]
L1 artifacts non-empty; L2 deck conformance; L3 independent re-solve; L4 nets against
the Euler-Bernoulli closed form; L5 pinned references (baked by the audit harness);
L6 the submitted .dat must agree with the summary and with the fresh .dat.

No ccx on the authoring host. VERIFIED: the .dat layout, against CalculiX 2.21
ground truth of tasks 0005/0006 and cross-solver 0002/0005. NOT verified: the
syntax of the beam 1-direction data line (the deck must state it; both placements
of the vector and an orientation node are accepted), the default section orientation
(a deck relying on it is rejected), whether a *BUCKLE step inherits the load of an
earlier static step (the deck restates the unit load; a load-free step 3 is accepted
as well), and the run time.
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

IMPLEMENTS = ("L1", "L2", "L3", "L4", "L5", "L6")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
CCX = os.environ.get("VERICAX_CCX", "/usr/bin/ccx")

REQUIRED_ARTIFACTS = ["column.inp", "column.dat", "summary.txt"]

LENGTH, N_ELEM = 1000.0, 20
SIDE1, SIDE2 = 24.0, 12.0             # size 1 along local 1 (= y), size 2 along local 2 (= z)
E_YOUNG, NU, DENSITY = 210000.0, 0.3, 7.85e-9
LOAD = -1.0                           # N, dof 1, on TIP
AREA = SIDE1 * SIDE2
I_WEAK = SIDE1 * SIDE2 ** 3 / 12.0    # depth 12: bending about y, deflection in z
I_STRONG = SIDE2 * SIDE1 ** 3 / 12.0  # depth 24: bending about z, deflection in y

EXPECTED_F1 = None
EXPECTED_F2 = None
EXPECTED_LAM1 = None
EXPECTED_LAM2 = None
EXPECTED_UX2 = None

RESOLVE_REL_TOL = PINNED_REL_TOL = 1.0e-2   # summary <-> submitted .dat <-> fresh .dat; pins
NET_REL_TOL = 5.0e-2                  # f1 and lam1 against the closed form
NET_RATIO_REL_TOL = 2.0e-2            # f2/f1 against 2, lam2/lam1 against 4
NET_UX_REL_TOL = 2.0e-2               # ux2 against -L/(EA)
GEOM_ABS_TOL = 1.0e-6
NAMES = ("f1", "f2", "lam1", "lam2", "ux2")


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-12) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * abs(target))


# ---------------------------------------------------------------- deck text
class DeckError(ValueError):
    """The deck (or a .dat) violates the task definition; str(exc) is the reason."""


def _need(cond: bool, reason: str) -> None:
    if not cond:
        raise DeckError(reason)


def _num(token: str) -> float | None:
    """float of a data-line entry; None if it is not a finite number."""
    try:
        value = float(token)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _floats(line: str) -> list[float] | None:
    """Comma-separated numbers of a data line; None if an entry is not a number."""
    vals = [_num(p) for p in line.split(",") if p.strip() != ""]
    return None if None in vals else vals


def kw_base(kw: str) -> str:
    return kw.split(",")[0].strip().upper()


def kw_param(kw: str, name: str) -> str | None:
    for part in kw.split(",")[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip().upper() == name.upper():
                return v.strip().strip("'\"")
    return None


def kw_has(kw: str, name: str) -> bool:
    """True if the keyword carries the parameter, as a bare flag (GENERATE) or NAME=value."""
    return any(p.strip().upper().split("=")[0] == name.upper() for p in kw.split(",")[1:])


def inp_blocks(text: str) -> list[tuple[str, list[str]]]:
    """(keyword line, data lines) in order; '**' comments dropped; a data line
    that ends with a comma continues in the next line."""
    blocks: list[tuple[str, list[str]]] = []
    carry = ""
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        line = carry + raw.strip()
        if line.startswith("**"):
            continue
        carry = ""
        if not line:
            continue
        if not line.startswith("*") and line.endswith(","):
            # A comma at the end continues the data on the next line only when a
            # data line follows. Before a keyword it is just a terminator (CalculiX
            # reads `2,` before *END STEP as two modes).
            following = next((other.strip() for other in lines[index + 1:] if other.strip()), "")
            if following and not following.startswith("*"):
                carry = line
            else:
                line = line.rstrip(",").strip()
                if not line:
                    continue
        if line.startswith("*"):
            blocks.append((line.upper(), []))
        elif blocks:
            blocks[-1][1].append(line)
    return blocks


# Only these cards may appear. Anything else (other loads, constraints, masses,
# amplitudes, other material models, nonlinear options) changes the model.
MODEL_CARDS = {"*HEADING", "*NODE", "*ELEMENT", "*NSET", "*ELSET", "*MATERIAL", "*ELASTIC",
               "*DENSITY", "*BEAM SECTION"}
PROCEDURES = {"*FREQUENCY", "*STATIC", "*BUCKLE"}
OUTPUT_CARDS = {"*NODE PRINT", "*NODE FILE", "*EL FILE", "*EL PRINT", "*OUTPUT", "*NODE OUTPUT",
                "*ELEMENT OUTPUT", "*MODAL OUTPUT", "*ENERGY FILE", "*ENERGY PRINT",
                "*ENERGY OUTPUT", "*SECTION PRINT", "*SECTION FILE", "*MODAL FILE", "*EL DRAW",
                "*NODE DRAW", "*STORE", "*RESTART", "*FILE FORMAT", "*FILE OUTPUT", "*PRINT"}
ALL_CARDS = MODEL_CARDS | PROCEDURES | OUTPUT_CARDS | {"*STEP", "*END STEP", "*CLOAD", "*BOUNDARY"}


def _members(kw: str, data: list[str]) -> list[int]:
    """Ids of a *Nset/*Elset card (a list, or GENERATE first,last,step)."""
    ids: list[int] = []
    for line in data:
        v = _floats(line)
        _need(v is not None, f"malformed set line: {line}")
        ids += (range(int(v[0]), int(v[1]) + 1, int(abs(v[2])))
                if kw_has(kw, "GENERATE") and len(v) == 3 and v[2] else [int(x) for x in v])
    return ids


def _target(token: str, d: dict) -> list[int]:
    """Node ids named by a data-line entry: a node number or a node-set name."""
    token = token.strip()
    if _num(token) is not None:
        _need(int(_num(token)) in d["nodes"], f"unknown node {token}")
        return [int(_num(token))]
    _need(token.upper() in d["nsets"], f"unknown node set {token}")
    return d["nsets"][token.upper()]


def _cloads(kw: str, data: list[str], d: dict, where: str) -> list[tuple]:
    """(where, node ids, dof, value) of one *CLOAD card."""
    _need((kw_param(kw, "OP") or "").upper() != "NEW", f"{where}: the loads must not use OP=NEW")
    out = []
    for line in data:
        p = [x.strip() for x in line.split(",")]
        _need(len(p) == 3 and _num(p[1]) is not None and _num(p[2]) is not None,
              f"malformed *CLOAD line: {line}")
        out.append((where, _target(p[0], d), int(_num(p[1])), _num(p[2])))
    return out


def _bcs(kw: str, data: list[str], d: dict, where: str) -> list[tuple]:
    """(where, node ids, first dof, last dof, value) of one *BOUNDARY card."""
    _need((kw_param(kw, "OP") or "").upper() != "NEW", f"{where}: boundary conditions must not use OP=NEW")
    out = []
    for line in data:
        p = [x.strip() for x in line.split(",")]
        last = _num(p[2]) if len(p) > 2 and p[2] else _num(p[1])
        value = _num(p[3]) if len(p) > 3 and p[3] else 0.0
        _need(len(p) in (2, 3, 4) and _num(p[1]) is not None and last is not None and value is not None,
              f"malformed *BOUNDARY line: {line}")
        out.append((where, _target(p[0], d), int(_num(p[1])), int(last), value))
    return out


def parse_deck(text: str) -> dict:
    """Validate the deck against the model definition; return {"tip": node id}
    (DeckError carries the reason)."""
    d: dict = {"nodes": {}, "elements": {}, "nsets": {}, "elsets": {}, "materials": {},
               "sections": [], "loads": [], "bc": [], "steps": []}
    step: dict | None = None
    material: str | None = None
    for kw, data in inp_blocks(text):
        base = kw_base(kw)
        _need(not kw_has(kw, "NLGEOM"), "no NLGEOM: all three steps are linear")
        _need(base in ALL_CARDS, f"unexpected card {base}")
        if base == "*STEP":
            step = {"procs": [], "prints": []}
            d["steps"].append(step)
        elif base == "*END STEP":
            _need(step is not None, "*END STEP without *STEP")
            step = None
        elif base in {"*NSET", "*ELSET"}:       # sets may be defined anywhere
            name = kw_param(kw, "NSET") or kw_param(kw, "ELSET")
            _need(name is not None, f"{base} needs a name")
            store = d["nsets"] if base == "*NSET" else d["elsets"]
            store.setdefault(name.upper(), []).extend(_members(kw, data))
        elif base == "*CLOAD":
            _need(step is not None, "*CLOAD must be inside a step")
            d["loads"] += _cloads(kw, data, d, f"step {len(d['steps'])}")
        elif base == "*BOUNDARY":
            d["bc"] += _bcs(kw, data, d, "model" if step is None else f"step {len(d['steps'])}")
        elif step is not None:
            if base in PROCEDURES:
                step["procs"].append((base, kw, data))
            elif base == "*NODE PRINT":
                step["prints"].append((kw, data))
            else:
                _need(base in OUTPUT_CARDS, f"card {base} must be defined before the first step")
        elif base == "*NODE":
            for line in data:
                v = _floats(line)
                # a node line may leave out z, which is 0 by default in CalculiX
                _need(v is not None and len(v) in (3, 4), f"malformed node line: {line}")
                _need(int(v[0]) not in d["nodes"], f"duplicate node {int(v[0])}")
                d["nodes"][int(v[0])] = tuple(v[1:4]) if len(v) == 4 else (v[1], v[2], 0.0)
        elif base == "*ELEMENT":
            for line in data:
                v = _floats(line)
                _need(v is not None and len(v) >= 3, f"malformed element line: {line}")
                _need(int(v[0]) not in d["elements"], f"duplicate element {int(v[0])}")
                d["elements"][int(v[0])] = ((kw_param(kw, "TYPE") or "").upper(), [int(x) for x in v[1:]])
                if kw_param(kw, "ELSET"):
                    d["elsets"].setdefault(kw_param(kw, "ELSET").upper(), []).append(int(v[0]))
        elif base == "*MATERIAL":
            material = (kw_param(kw, "NAME") or "").upper()
            _need(material, "*MATERIAL needs a name")
            d["materials"].setdefault(material, [None, None])
        elif base in {"*ELASTIC", "*DENSITY"}:
            _need(material is not None, f"{base} outside *MATERIAL")
            _need(len(data) == 1 and _floats(data[0]) is not None, f"{base} needs one data line")
            v = _floats(data[0])
            if base == "*DENSITY":
                d["materials"][material][1] = v[0]
            elif len(v) >= 2 and (kw_param(kw, "TYPE") or "ISO").upper() == "ISO":
                d["materials"][material][0] = (v[0], v[1])
            else:
                raise DeckError("*ELASTIC needs E and nu (isotropic)")
        elif base == "*BEAM SECTION":
            d["sections"].append((kw, data))
        elif base != "*HEADING":               # an output request outside any step
            raise DeckError(f"card {base} must be inside a step")
    _need(step is None, "the last *STEP has no *END STEP")
    return _validate(d)


def _validate(d: dict) -> dict:
    nodes, elements, steps = d["nodes"], d["elements"], d["steps"]

    # ---- nodes: 21 stations on the x axis; other nodes only as orientation nodes
    axis: dict[int, int] = {}
    for nid, (x, y, z) in nodes.items():
        if abs(y) <= GEOM_ABS_TOL and abs(z) <= GEOM_ABS_TOL:
            i = int(round(x / (LENGTH / N_ELEM)))
            _need(0 <= i <= N_ELEM and i not in axis and abs(x - i * LENGTH / N_ELEM) <= GEOM_ABS_TOL,
                  f"expected nodes at (50*i, 0, 0), i = 0..20 (node {nid})")
            axis[i] = nid
    _need(len(axis) == N_ELEM + 1, f"expected {N_ELEM + 1} nodes at (50*i, 0, 0), i = 0..20")

    # ---- elements: one B31 chain from x = 0 to x = L (connectivity, not numbering)
    _need(len(elements) == N_ELEM, f"expected {N_ELEM} elements, found {len(elements)}")
    station = {nid: i for i, nid in axis.items()}
    for eid, (etype, conn) in elements.items():
        _need(etype == "B31" and len(conn) in (2, 3), f"element {eid} must be B31 (2 nodes)")
        _need(all(n in nodes for n in conn), f"element {eid} uses an undefined node")
    links = sorted(sorted((station.get(c[0], -1), station.get(c[1], -1)))
                   for _t, c in elements.values())
    _need(links == [[i, i + 1] for i in range(N_ELEM)],
          "elements must form one chain of neighbouring stations from x = 0 to x = L")
    third = {c[2] for _t, c in elements.values() if len(c) == 3}
    _need(all(n in third for n in nodes if n not in station),
          "nodes off the axis are only allowed as orientation nodes of a beam")
    root, tip, mid = axis[0], axis[N_ELEM], axis[N_ELEM // 2]

    # ---- exactly one RECT section over all elements, local 1 = y; material with density
    _need(len(d["sections"]) == 1, "expected exactly one *BEAM SECTION")
    kw, data = d["sections"][0]
    _need((kw_param(kw, "SECTION") or "RECT").upper() == "RECT", "beam section must be SECTION=RECT")
    _need(sorted(set(d["elsets"].get((kw_param(kw, "ELSET") or "").upper(), []))) == sorted(elements),
          "the beam section ELSET must cover all elements")
    sizes = _floats(data[0]) if data else None
    _need(sizes is not None and len(sizes) in (2, 5), "malformed *BEAM SECTION data line")
    _need(abs(sizes[0] - SIDE1) <= GEOM_ABS_TOL and abs(sizes[1] - SIDE2) <= GEOM_ABS_TOL,
          f"section sizes must be {SIDE1:g} x {SIDE2:g} (first size along local 1 = y)")
    directions = [("section 1-direction", sizes[2:5])] if len(sizes) == 5 else []
    if len(sizes) == 2 and len(data) > 1:      # or on the line after the sizes
        _need(_floats(data[1]) is not None and len(_floats(data[1])) == 3,
              "malformed section 1-direction line")
        directions.append(("section 1-direction", _floats(data[1])))
    directions += [(f"orientation node of element {eid}",                 # third node of a beam
                    [nodes[c[2]][k] - nodes[c[0]][k] for k in range(3)])
                   for eid, (_t, c) in elements.items() if len(c) == 3]
    _need(directions, "section orientation is not stated (the 1-direction must be the global y)")
    for label, vec in directions:
        across = math.hypot(vec[1], vec[2])   # part perpendicular to the beam axis (x)
        _need(across > GEOM_ABS_TOL, f"{label} is parallel to the beam axis")
        _need(abs(vec[2]) / across <= 1e-6, f"{label} must make local 1 the global y axis")
    mat = (kw_param(kw, "MATERIAL") or "").upper()
    _need(mat in d["materials"], f"beam section references unknown material {mat}")
    elastic, density = d["materials"][mat]
    _need(elastic is not None and abs(elastic[0] - E_YOUNG) <= 1e-6 and abs(elastic[1] - NU) <= 1e-9,
          "material must be E = 210000 MPa, nu = 0.3")
    _need(density is not None, "*DENSITY is missing (the frequency step needs it)")
    _need(close_enough(density, DENSITY, 1e-9, abs_tol=0.0), "density must be 7.85e-9")

    # ---- sets by coordinates
    for label, node in (("ROOT", root), ("TIP", tip), ("MID", mid)):
        _need(label in d["nsets"], f"node set {label} is missing")
        _need(sorted(set(d["nsets"][label])) == [node],
              f"node set {label} must hold only the node at x = {nodes[node][0]:g}")

    # ---- clamp: ROOT only, dofs 1-6, zero, in the model part or restated unchanged in a step
    fixed: set[int] = set()
    for where, ids, first, last, value in d["bc"]:
        _need(set(ids) == {root}, f"{where}: only ROOT may be constrained")
        _need(1 <= first <= last <= 6, f"{where}: degrees of freedom must be within 1..6")
        _need(value == 0.0, f"{where}: prescribed value must be zero")
        fixed.update(range(first, last + 1))
    _need(fixed == set(range(1, 7)), "ROOT must be clamped in dofs 1-6")

    # ---- three steps in order: frequency, static (+unit load), buckle (no new load)
    _need(len(steps) == 3 and all(len(s["procs"]) == 1 for s in steps),
          f"expected exactly three *STEP blocks with one analysis card each, found {len(steps)}")

    def unit_loads(k: int) -> list:
        """The *CLOAD lines of step k; each of them must be the unit load itself."""
        lines = [e for e in d["loads"] if e[0] == f"step {k}"]
        for _w, ids, dof, value in lines:
            _need(set(ids) == {tip} and dof == 1 and abs(value - LOAD) <= 1e-9,
                  f"step {k} load must be -1 N in dof 1 on TIP")
        return lines

    (base1, _k, data1), (base2, kw2, _d), (base3, _k, data3) = [s["procs"][0] for s in steps]
    _need(base1 == "*FREQUENCY", f"step 1 must be *FREQUENCY, found {base1}")
    _need(not any(e[0] == "step 1" for e in d["loads"]),
          "step 1 must not define loads (the column is unloaded)")
    _need(base2 == "*STATIC" and not kw_has(kw2, "RIKS"),
          f"step 2 must be a linear *STATIC step, found {base2}")
    _need(len(unit_loads(2)) == 1, "step 2 must hold exactly one *CLOAD line")
    unit_loads(3)          # the unit load may be restated in the buckle step; nothing else
    _need(base3 == "*BUCKLE", f"step 3 must be *BUCKLE (the card that prints buckling factors), "
                             f"found {base3}")
    for k, card_data in ((1, data1), (3, data3)):
        n = _floats(card_data[0])[0] if card_data and _floats(card_data[0]) else None
        _need(n is not None and n >= 2 and n == int(n), f"step {k} must request at least two modes")
    _need(any(kw_param(pk, "NSET") and tip in d["nsets"].get(kw_param(pk, "NSET").upper(), [])
              and "U" in [t.upper() for line in pd for t in re.split(r"[,\s]+", line) if t.strip()]
              for pk, pd in steps[1]["prints"]),
          "step 2 must print U for TIP with *NODE PRINT (the axial shortening goes to .dat)")
    return {"tip": tip}


# ---------------------------------------------------------------- .dat parsing
# Layout verified against CalculiX 2.21 .dat files of tasks 0005/0006 and cross-solver
# 0002/0005: "S T E P       n"; EIGENVALUE OUTPUT rows `mode eigenvalue rad/time
# cycles/time imag`; BUCKLING FACTOR OUTPUT rows `mode factor`; "displacements (vx,vy,vz)
# for set ..." rows `node ux uy uz`; per-mode title "E I G E N V A L U E    N U M B E R  n".
# Tolerated variants (not from those files): unspaced titles, D exponents, an
# EIGENFREQUENCY table, missing step headers, extra columns.
_NUM = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[DdEe][-+]?\d+)?$")
_INT = re.compile(r"^[-+]?\d+$")
_KEEP = ("(", "MODENO", "REALPART", "IMAGINARYPART", "FACTOR", "BUCKLING", "EIGENVALUE",
         "FREQUENCY", "NODE")          # column headers; other unknown titles end a table


def _title_kind(c: str) -> str | None:
    """Table kind of a title line (whitespace removed, upper-case); None if unknown."""
    if c.startswith("EIGENVALUENUMBER") or re.fullmatch(r"EIGENMODE\d+", c):
        return "mode"                       # per-mode title: mode shapes follow
    if c.startswith("EIGENFREQUENCY"):
        return "eigfreq"                    # a table that holds the frequencies themselves
    if c.startswith("EIGENVALUE"):
        return "eigen"                      # eigenvalue output: mode, omega^2, frequencies
    if "BUCKLINGFACTOR" in c or "BUCKLINGLOAD" in c or "LOADFACTOR" in c:
        return "buckle"
    if c.startswith("DISPLACEMENTS"):
        return "disp"
    if "PARTICIPATIONFACTOR" in c or "EFFECTIVEMASS" in c or "EFFECTIVEMODALMASS" in c:
        return "other"
    return None


def dat_tables(text: str) -> tuple[bool, list[list]]:
    """Split a .dat into titled tables: (step_numbers_seen, [kind, step, rows]).
    A table starts at a recognised title and takes the numeric rows that follow
    (`mode value ...` or `node ux uy uz`); rows not starting with an integer are skipped."""
    tables: list[list] = []
    step, known, cur = 0, False, None
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        c = re.sub(r"\s+", "", s).upper()
        m = re.fullmatch(r"STEP(\d+)", c)
        if m:
            step, known, cur = int(m.group(1)), True, None
            continue
        p = s.replace(",", " ").split()
        if _INT.match(p[0]):
            if cur is not None and len(p) > 1 and all(_NUM.match(t) for t in p[1:]):
                cur[2].append([int(p[0])] + [float(t.replace("D", "E").replace("d", "e"))
                                             for t in p[1:]])
            continue
        kind = _title_kind(c)
        if kind == "mode":
            cur = None
        elif kind is not None:
            cur = [kind, step, []]
            tables.append(cur)
        elif cur is not None and not c.startswith(_KEEP):
            cur = None
    return known, tables


def _frequency(row: list, kind: str) -> float:
    """Hz of one eigen row: the CYCLES/TIME column when it agrees with the
    eigenvalue (rad^2/s^2), else sqrt(|eigenvalue|)/(2 pi); a short row of an
    EIGENFREQUENCY table holds the frequency itself."""
    if len(row) < 5:
        return abs(row[1]) if kind == "eigfreq" else math.sqrt(abs(row[1])) / (2 * math.pi)
    f = math.sqrt(abs(row[1])) / (2 * math.pi)
    return row[3] if row[3] > 0 and close_enough(row[3], f, 1e-3, abs_tol=0.0) else f


def dat_results(text: str, tip: int) -> list[float]:
    """[f1, f2, lam1, lam2, ux2] of a .dat; DeckError carries the reason."""
    known, tables = dat_tables(text)
    eigen = [t for t in tables if t[0] in ("eigen", "eigfreq")]
    freq = next((t for t in eigen if t[1] == 1), eigen[0] if eigen else None)
    _need(freq is not None and len(freq[2]) >= 2,
          "column.dat has no step-1 EIGENVALUE table with two modes")
    buck = [t for t in tables if t[0] == "buckle"]
    lamt = next((t for t in buck if t[1] == 3), buck[0] if buck else None)
    if lamt is None:   # tolerated layout: the buckle step prints an EIGENVALUE table
        lamt = next((t for t in eigen if t is not freq and t[1] != 1), None)
    _need(lamt is not None and len(lamt[2]) >= 2,
          "column.dat has no BUCKLING FACTOR table with two modes")
    uxs = [row[1] for t in tables if t[0] == "disp" and (t[1] == 2 or not known)
           for row in t[2] if row[0] == tip]
    _need(bool(uxs), "column.dat has no displacement record of TIP in the static step")
    return ([_frequency(r, freq[0]) for r in freq[2][:2]]
            + [abs(r[1]) for r in lamt[2][:2]] + [uxs[-1]])


# ---------------------------------------------------------------- L1 / L3 / L4
def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


def resolve(path: Path, tip: int) -> list[float]:
    """Independent re-solve: run the submitted deck unchanged in a scratch directory."""
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        shutil.copyfile(path, scratch / "column.inp")
        try:
            subprocess.run([CCX, "column"], cwd=scratch, timeout=300, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"independent re-solve could not run: {exc}")
        dat = scratch / "column.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            raise ValueError("independent re-solve produced no column.dat")
        return dat_results(dat.read_text(errors="ignore"), tip)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def closed_form() -> list[float]:
    """Euler-Bernoulli estimates for the cantilever, per bending plane:
    f = a1^2/(2 pi) sqrt(E I/(rho A L^4)) and Pcr = pi^2 E I/(4 L^2), a1 = 1.8751041.
    I_weak gives the first mode (f1, lam1); I_strong the next one (f2, lam2),
    which is the strong-axis first mode, not the weak-axis second mode."""
    c = 1.8751041 ** 2 / (2 * math.pi) * math.sqrt(E_YOUNG / (DENSITY * AREA * LENGTH ** 4))
    e = math.pi ** 2 * E_YOUNG / (4 * LENGTH ** 2)
    return [c * math.sqrt(I_WEAK), c * math.sqrt(I_STRONG), e * I_WEAK, e * I_STRONG,
            -LENGTH / (E_YOUNG * AREA)]


def _summary() -> list[float]:
    """The one numeric line of summary.txt as five finite numbers. Text lines
    (a header, units), blank lines and empty entries are ignored; a second
    numeric line is not."""
    numeric = []
    for line in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").splitlines():
        parts = [p for p in (x.strip() for x in line.split(",")) if p]
        if parts and all(_num(p) is not None for p in parts):
            numeric.append([_num(p) for p in parts])
    _need(len(numeric) == 1 and len(numeric[0]) == 5,
          "summary.txt must hold one line of five comma-separated numbers: f1, f2, lam1, lam2, ux2")
    return numeric[0]


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    try:
        deck = parse_deck((AGENT_ROOT / "column.inp").read_text(errors="ignore"))
        summary = _summary()
        submitted = dat_results((AGENT_ROOT / "column.dat").read_text(errors="ignore"), deck["tip"])
        fresh = resolve(AGENT_ROOT / "column.inp", deck["tip"])
    except (ValueError, OSError) as exc:
        return _fail(str(exc))
    src = {"summary": summary, "submitted column.dat": submitted, "independent re-solve": fresh}
    pins = dict(zip(NAMES, (EXPECTED_F1, EXPECTED_F2, EXPECTED_LAM1, EXPECTED_LAM2, EXPECTED_UX2)))
    for i, name in enumerate(NAMES):       # L6 and L3: every pair must agree; L5: the pins
        for x, y in (("summary", "submitted column.dat"),
                     ("submitted column.dat", "independent re-solve"),
                     ("summary", "independent re-solve")):
            if not close_enough(src[x][i], src[y][i], RESOLVE_REL_TOL):
                return _fail(f"{x} {name} does not match the {y}")
        if pins[name] is not None and not close_enough(fresh[i], pins[name], PINNED_REL_TOL):
            return _fail(f"re-solve {name} deviates from the pinned reference")
    f1, f2, lam1, lam2, ux2 = fresh
    ref = closed_form()
    if f1 <= 0.0 or lam1 <= 0.0:
        return _fail("f1 and lam1 must be positive")
    for value, target, tol, reason in (
            (f1, ref[0], NET_REL_TOL, "f1 is not within 5% of the Euler-Bernoulli estimate"),
            (f2 / f1, 2.0, NET_RATIO_REL_TOL, "f2/f1 must be 2 (strong-axis over weak-axis first mode)"),
            (lam1, ref[2], NET_REL_TOL, "lam1 is not within 5% of the Euler buckling load"),
            (lam2 / lam1, 4.0, NET_RATIO_REL_TOL, "lam2/lam1 must be 4 (strong-axis over weak-axis mode)"),
            (ux2, ref[4], NET_UX_REL_TOL, "ux2 is not within 2% of the axial shortening -L/(EA)")):
        if not close_enough(value, target, tol):
            return _fail(reason)
    return True


def main() -> int:
    try:
        ok = evaluate()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - verifier must never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        ok = False
    print("True" if ok else "False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
