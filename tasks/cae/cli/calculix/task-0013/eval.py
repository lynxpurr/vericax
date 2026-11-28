#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--calculix--task-0013 (stepped tension plate).

One deck, three linear static steps on a 200 x 100 x 2 mm plane-stress plate
(40 x 20 CPS4, x = 0 clamped in dofs 1-2), loads with *DLOAD only: step 1 the
+100 MPa traction on x = 200 as element face loads; step 2 that traction
removed and a uniform body force in -x (*DLOAD GRAV, rho*g = 10/200); step 3
both together, so step 3 = step 1 + step 2.

L1 artifacts, L2 deck conformance (per-step load state included), L3 independent
re-solve of the submitted deck, L4 physics nets independent of any gold, L5 pins.

Hand estimates: ux1 = sigma*L/E = 0.095238 mm, ux2 = -(rho g) L^2/(2E) =
-0.004762 mm, ux3 = ux1 + ux2; the mean uy of the free edge is zero (the
lateral contraction is antisymmetric about y = 50); the clamp carries -20000 N
and then +2000 N. An independent plane-stress FE solve of this mesh lies 0.63 %
(ux1) and 1.25 % (ux2) under the closed forms: the clamp also blocks the
lateral contraction.

Conventions read from real CalculiX 2.21 output on this image:
  * .dat blocks " displacements (vx,vy,vz) for set <NAME> and time ..." and
    " forces (fx,fy,fz) for set <NAME> and time ...", one per *NODE PRINT
    request; upper-case set name; node number, then three E-format values.
  * RF at a constrained node is the constraint force (support on structure),
    opposite to the applied load: a B31 cantilever with -80 N at the tip reads
    +80 N at its root, a block stretched by a prescribed +x displacement reads
    -21030 N at its fixed face, so the clamp reads -20000 N in step 1. No real
    example had a distributed load on constrained nodes themselves (the body
    force also acts on the clamp nodes): the step-2 net accepts the constraint
    force rho*g*A*t = 2000 N and the elastic internal force K*u at the clamp,
    2000 N minus the 25 N body-force share of the clamped nodes.
  * "*DLOAD: set, GRAV, magnitude, gx, gy, gz" loads rho*magnitude per unit
    volume along (gx, gy, gz); a real deck with 9810., 0., -1., 0. sags in -y.
  * A positive face pressure acts into the element. The force of a face load is
    p * edge length * thickness along the inward normal, taken from the
    element's own node ordering (face k joins local nodes k and k+1).
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

IMPLEMENTS = ("L1", "L2", "L3", "L4", "L5")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
CCX = os.environ.get("VERICAX_CCX", "/usr/bin/ccx")

REQUIRED_ARTIFACTS = ["plate.inp", "plate.dat", "summary.txt"]

# ---- pinned problem (task-0013 instruction) ----
NX, NY, CELL = 40, 20, 5.0
LENGTH, HEIGHT, THICK = CELL * NX, CELL * NY, 2.0
E_YOUNG, NU, RHO = 210000.0, 0.3, 7.85e-9
TRACTION = 100.0                        # MPa, +x on the edge x = 200
RHO_G = 10.0 / LENGTH                   # N/mm^3, body force in -x
FACE_NODES = ((0, 1), (1, 2), (2, 3), (3, 0))   # CalculiX face k = local nodes k, k+1

# ---- pins in summary order, filled from the audited gold summary ----
EXPECTED_UX1 = None
EXPECTED_UY1 = None
EXPECTED_UX2 = None
EXPECTED_UX3 = None

SUMMARY_REL_TOL = 1.0e-2    # A vs B: reported numbers vs the independent re-solve
RUN_REL_TOL = 1.0e-4        # plate.dat vs the fresh .dat: same deck, same solver
PINNED_REL_TOL = 1.0e-3     # re-solve vs the baked gold pins
UX1_REL_TOL, UX2_REL_TOL = 2.0e-2, 5.0e-2     # L4 nets: closed forms
SUPER_REL_TOL = 1.0e-2      # |ux3 - (ux1 + ux2)| <= SUPER_REL_TOL * |ux1|
RF_REL_TOL = 1.0e-2
UY1_ABS_TOL = 1.0e-9
GEOM_TOL, LOAD_REL_TOL, NOISE = 1.0e-6, 1.0e-3, 1.0e-8    # mm, relative, mm or N

# The deck may only use these cards (the instruction lists them); anything else
# can change the mechanics.
ALLOWED = {"*HEADING", "*NODE", "*ELEMENT", "*NSET", "*ELSET", "*MATERIAL", "*ELASTIC", "*DENSITY",
           "*SOLID SECTION", "*BOUNDARY", "*STATIC", "*DLOAD", "*NODE PRINT", "*NODE FILE",
           "*EL FILE", "*EL PRINT"}
DEFINITION = {"*HEADING", "*NODE", "*ELEMENT", "*NSET", "*ELSET", "*MATERIAL", "*ELASTIC",
              "*DENSITY", "*SOLID SECTION"}
NUMBER = r"[-+]?\d*\.?\d+(?:[EeDd][-+]?\d+)?"


class Reject(Exception):
    """A conformance or physics failure; the message is the debug line."""


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-12) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * abs(target))


def _toks(line: str) -> list[str]:
    return [t for t in re.split(r"[,\s]+", line.strip()) if t]


def _num(token: str) -> float:
    return float(token.replace("D", "E").replace("d", "e"))


def _int(token: str) -> int:
    return int(_num(token))


# ---------------------------------------------------------------- deck parsing
def read_blocks(text: str) -> list[list]:
    """[keyword, params, data rows]. Keyword lines are split on commas (they may
    hold two words, such as *SOLID SECTION) and upper-cased; data rows are
    tokenised on commas or blanks; comments, blank lines and trailing-backslash
    continuations are removed."""
    blocks, current, pending = [], None, None
    for raw in text.splitlines():
        line = raw.strip()
        if line.endswith("\\"):
            pending = (pending or "") + line[:-1] + " "
            continue
        line = (pending or "") + line
        pending = None
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            parts = [p.strip() for p in line.upper().split(",")]
            params = dict((k, v) for k, _, v in (p.partition("=") for p in " ".join(parts[1:]).split()))
            current = [" ".join(parts[0].split()), params, []]
            blocks.append(current)
        elif current is not None:
            current[2].append(_toks(line))
    return blocks


def _model_card(deck: dict, base: str, params: dict, data: list) -> None:
    """Store one model-definition card; ValueError on malformed data."""
    if base in ("*NSET", "*ELSET"):
        kind, key = ("nsets", "NSET") if base == "*NSET" else ("elsets", "ELSET")
        target = deck[kind].setdefault(params.get(key, "").upper(), set())
        for row in data:
            if "GENERATE" in params:
                target.update(range(_int(row[0]), _int(row[1]) + 1, _int(row[2])))
            else:
                target.update(_int(t) for t in row)
    elif base == "*NODE":
        for row in data:
            if len(row) not in (3, 4):
                raise ValueError(f"node line {row}")
            deck["nodes"][_int(row[0])] = tuple(_num(v) for v in row[1:]) + (0.0,) * (4 - len(row))
        if params.get("NSET"):
            deck["nsets"].setdefault(params["NSET"].upper(), set()).update(_int(r[0]) for r in data)
    elif base == "*ELEMENT":
        etype = params.get("TYPE", "").upper()
        for row in data:
            if len(row) < 3:
                raise ValueError(f"element line {row}")
            deck["elems"][_int(row[0])] = (etype, [_int(v) for v in row[1:]])
        if params.get("ELSET"):
            deck["elsets"].setdefault(params["ELSET"].upper(), set()).update(_int(r[0]) for r in data)
    elif base == "*MATERIAL":
        deck["nmat"] += 1
    elif base in ("*ELASTIC", "*DENSITY"):
        deck[base[1:].lower()].extend(data)
    elif base != "*HEADING":                      # its title line needs no check
        deck["sections" if base == "*SOLID SECTION" else "bc"].append((params, data))


def parse_deck(text: str) -> dict:
    """Model data and steps of a free-format deck; Reject on a card this task
    does not allow or on model data placed after the first step."""
    deck = {"nodes": {}, "elems": {}, "nsets": {}, "elsets": {}, "elastic": [], "density": [],
            "sections": [], "bc": [], "steps": [], "nmat": 0}
    blocks = read_blocks(text)
    if not blocks:
        raise Reject("plate.inp contains no keyword cards")
    step, closed = None, False
    for base, params, data in blocks:
        if base not in ALLOWED | {"*STEP", "*END STEP"}:
            raise Reject(f"card {base} is not allowed in this deck")
        if base == "*STEP":
            if step is not None:
                raise Reject("a *STEP card inside another step")
            step = {"params": params, "blocks": []}
            deck["steps"].append(step)
        elif base == "*END STEP":
            if step is None:
                raise Reject("*END STEP without a *STEP card")
            step, closed = None, True
        elif step is not None:
            step["blocks"].append((base, params, data))
        elif closed and base not in DEFINITION:
            raise Reject(f"card {base} comes after the first step: define the model once, before the steps")
        else:
            try:
                _model_card(deck, base, params, data)
            except (ValueError, KeyError, IndexError) as exc:
                raise Reject(f"malformed {base} card: {exc}") from None
    if step is not None:
        raise Reject("the last *STEP has no *END STEP")
    return deck


def step_states(deck: dict) -> list[dict]:
    """*DLOAD entries active at the end of each step, {(element, label): value},
    carried the way CalculiX carries them: they persist, OP=NEW drops them, the
    same element and label replaces. Stores each step's print requests too."""
    active, states = {}, []
    for si, step in enumerate(deck["steps"], 1):
        if {"NLGEOM", "PERTURBATION"} & set(step["params"]):
            raise Reject(f"step {si}: linear static analysis only (no NLGEOM, no perturbation step)")
        static = [params for base, params, _ in step["blocks"] if base == "*STATIC"]
        if len(static) != 1 or {"RIKS", "PERTURBATION"} & set(static[0]):
            raise Reject(f"step {si}: exactly one plain *STATIC procedure is required")

        def add_load(row: list) -> None:
            """Enter one *DLOAD data row (element or element set, label, magnitude)."""
            label, value = row[1].upper(), _num(row[2])
            if label == "GRAV":
                if len(row) != 6:
                    raise Reject(f"step {si}: GRAV needs a magnitude and the direction vector gx, gy, gz")
                value = (value, tuple(_num(v) for v in row[3:]))
            try:
                targets = [_int(row[0])]
            except ValueError:
                targets = sorted(deck["elsets"].get(row[0].upper(), ()))
            if not targets:
                raise Reject(f"step {si}: *DLOAD target {row[0]!r} is neither an element nor an element set")
            for eid in targets:
                active[(eid, label)] = value

        prints = []
        for base, params, data in step["blocks"]:
            if base == "*DLOAD":
                if params.get("OP", "").upper() == "NEW":
                    active = {}
                for row in data:
                    if len(row) < 3:
                        raise Reject(f"step {si}: malformed *DLOAD line {row}")
                    try:
                        add_load(row)
                    except ValueError:
                        raise Reject(f"step {si}: malformed *DLOAD line {row}") from None
            elif base == "*BOUNDARY":
                if si > 1:
                    raise Reject("boundary conditions may not be defined or changed after step 1")
                deck["bc"].append((params, data))
            elif base == "*NODE PRINT":
                name = params.get("NSET", "").upper()
                prints.append((deck["nsets"].get(name, set()), {t.upper() for r in data for t in r}))
        step["prints"] = prints
        states.append(dict(active))
    return states


# ---------------------------------------------------------------- L2
def check_bc(deck: dict, clamp: set) -> None:
    """Every CLAMP node fixed in dofs 1 and 2; nothing else constrained."""
    fixed = set()
    for params, data in deck["bc"]:
        if "TYPE" in params:
            raise Reject("*BOUNDARY must fix the dofs explicitly (no TYPE=)")
        for row in data:
            if len(row) not in (2, 3, 4):
                raise Reject(f"malformed *Boundary line {row}")
            try:
                ids = [_int(row[0])]
            except ValueError:
                ids = sorted(deck["nsets"].get(row[0].upper(), ()))
            if not ids:
                raise Reject(f"*Boundary target {row[0]!r} is neither a node nor a node set")
            first = _int(row[1])
            # CalculiX data line: node or set, first dof, last dof (optional), value
            # (optional, 0 by default). The value only exists in a 4-token row.
            last = _int(row[2]) if len(row) >= 3 else first
            value = _num(row[3]) if len(row) == 4 else 0.0
            if last < first or not set(range(first, last + 1)) <= {1, 2}:
                raise Reject(f"the clamp must fix dof 1 and dof 2 only (found dofs {first} to {last})")
            if abs(value) > 1e-12:
                raise Reject("the clamp must be fixed to zero")
            if not set(ids) <= clamp:
                raise Reject("boundary conditions are allowed on the CLAMP nodes only")
            fixed.update((n, d) for n in ids for d in range(first, last + 1))
    if fixed != {(n, d) for n in clamp for d in (1, 2)}:
        raise Reject("every CLAMP node must be fixed in dof 1 and dof 2")


def check_material(deck: dict) -> float:
    """One linear elastic material, one section over all elements; returns rho."""
    elastic = deck["elastic"]
    if deck["nmat"] != 1 or len(elastic) != 1 or len(elastic[0]) != 2:
        raise Reject("exactly one material with one *Elastic data line (E, nu) is required")
    e_mod, nu = map(_num, elastic[0])
    if abs(e_mod - E_YOUNG) > 1e-6 * E_YOUNG or abs(nu - NU) > 1e-9:
        raise Reject("the material must be E = 210000 MPa and nu = 0.3")
    density, sections = deck["density"], deck["sections"]
    if len(density) != 1 or len(density[0]) != 1:
        raise Reject("exactly one *Density value is required")
    rho = _num(density[0][0])
    if abs(rho - RHO) > 1e-6 * RHO:
        raise Reject("the density must be 7.85e-9 t/mm^3")
    if len(sections) != 1:
        raise Reject("exactly one *Solid Section is required")
    params, data = sections[0]
    if deck["elsets"].get(params.get("ELSET", "").upper()) != set(deck["elems"]):
        raise Reject("the *Solid Section must cover every element")
    if len(data) != 1 or len(data[0]) != 1 or abs(_num(data[0][0]) - THICK) > 1e-9:
        raise Reject("the *Solid Section data line must be the thickness 2.0")
    return rho


def conformance(text: str) -> tuple[set, set]:
    """L2: the deck against the instruction. Returns the (FREE, CLAMP) node ids,
    which are found by coordinates, never by index."""
    deck = parse_deck(text)
    nodes, elems = deck["nodes"], deck["elems"]
    at = {}
    for node, (x, y, z) in nodes.items():
        i, j = round(x / CELL), round(y / CELL)
        if (abs(z) > GEOM_TOL or abs(x - i * CELL) > GEOM_TOL or abs(y - j * CELL) > GEOM_TOL
                or not 0 <= i <= NX and 0 <= j <= NY):
            raise Reject(f"node {node} is not on the 5 mm grid in the plane z = 0")
        at[node] = (i, j)
    if set(at.values()) != {(i, j) for i in range(NX + 1) for j in range(NY + 1)}:
        raise Reject(f"expected the {(NX + 1) * (NY + 1)} nodes (5*i, 5*j, 0), i = 0..40, j = 0..20")
    cells = set()
    for eid, (etype, conn) in elems.items():
        corners = {at[n] for n in conn if n in at}
        if etype != "CPS4" or len(conn) != 4 or len(corners) != 4:
            raise Reject(f"element {eid} must be a CPS4 joining four mesh nodes")
        (i0, j0), (i1, j1) = min(corners), max(corners)
        if (i1 - i0, j1 - j0) != (1, 1):
            raise Reject(f"element {eid} is not one 5 x 5 mm cell")
        cells.add((i0, j0))
    if cells != {(i, j) for i in range(NX) for j in range(NY)}:
        raise Reject(f"expected {NX * NY} elements covering the plate once, found {len(elems)}")
    clamp = {n for n, ij in at.items() if ij[0] == 0}
    free = {n for n, ij in at.items() if ij[0] == NX}
    want = {"CLAMP": ("x = 0", {(0, j) for j in range(NY + 1)}),
            "FREE": ("x = 200", {(NX, j) for j in range(NY + 1)}),
            "MIDFREE": ("(200, 50)", {(NX, NY // 2)}), "CENTRE": ("(100, 50)", {(NX // 2, NY // 2)})}
    for name, (where, members) in want.items():
        got = deck["nsets"].get(name, set())
        if not got <= set(at) or {at[n] for n in got} != members:
            raise Reject(f"node set {name} must hold exactly the node(s) at {where}")
    if len(deck["steps"]) != 3:
        raise Reject(f"expected exactly three *STEP blocks in one deck, found {len(deck['steps'])}")
    states = step_states(deck)          # also collects *Boundary cards placed inside step 1
    rho = check_material(deck)
    check_bc(deck, clamp)
    right = {eid: k for eid, (_t, conn) in elems.items() for k, (a, b) in enumerate(FACE_NODES, 1)
             if at[conn[a]][0] == NX and at[conn[b]][0] == NX}       # right column: face on x = 200

    def face_force(eid: int, face: int, p: float) -> tuple[float, float]:
        """In-plane force a pressure p exerts on an element. Face k joins the local
        nodes k and k+1; the inward normal runs from the face midpoint to the
        centroid, and a positive CalculiX pressure acts along it."""
        conn = elems[eid][1]
        (ax, ay), (bx, by) = (nodes[n][:2] for n in (conn[k] for k in FACE_NODES[face - 1]))
        vx = sum(nodes[n][0] for n in conn) / 4 - (ax + bx) / 2
        vy = sum(nodes[n][1] for n in conn) / 4 - (ay + by) / 2
        if math.hypot(vx, vy) < 1e-9:
            raise Reject(f"degenerate face {face} of element {eid}")
        scale = p * math.hypot(bx - ax, by - ay) * THICK / math.hypot(vx, vy)
        return vx * scale, vy * scale

    def split(state: dict, si: int) -> tuple[dict, dict]:
        press, grav = {}, {}
        for (eid, label), value in state.items():
            if eid not in elems:
                raise Reject(f"step {si}: *DLOAD names element {eid}, which the mesh does not have")
            if label == "GRAV":
                grav[eid] = value
            elif label[0] == "P" and label[1:] in ("1", "2", "3", "4"):
                if abs(value) > 1e-12:       # a pressure of 0 is no load: it cancels an earlier one
                    press[(eid, int(label[1:]))] = value
            else:
                raise Reject(f"step {si}: load label {label} is not allowed (face pressures and GRAV only)")
        return press, grav

    def check_traction(press: dict, si: int) -> None:
        forces = [face_force(eid, face, p) for (eid, face), p in press.items()]
        fx, fy = (sum(f[k] for f in forces) for k in (0, 1))
        want = TRACTION * HEIGHT * THICK
        if not close_enough(fx, want, LOAD_REL_TOL, 1e-6) or abs(fy) > 1e-6:
            raise Reject(f"step {si}: the face loads must total +{want:g} N in +x on the edge x = 200, "
                         f"they total ({fx:.4g}, {fy:.4g}) N")
        if set(press) != set(right.items()) or any(not close_enough(p, -TRACTION, 1e-9) for p in press.values()):
            raise Reject(f"step {si}: a uniform traction of {TRACTION:g} MPa must act on the twenty faces "
                         "of the rightmost element column on x = 200")

    def check_grav(grav: dict, si: int) -> None:
        if set(grav) != set(elems):
            raise Reject(f"step {si}: the body force must act on all {NX * NY} elements")
        for g, (gx, gy, gz) in grav.values():
            if (abs(math.sqrt(gx * gx + gy * gy + gz * gz) - 1) > 1e-6
                    or gx > -1 + 1e-6 or max(abs(gy), abs(gz)) > 1e-6):
                raise Reject(f"step {si}: GRAV must carry the unit direction vector (-1, 0, 0), "
                             "the body force acts in -x")
            if not close_enough(rho * g, RHO_G, LOAD_REL_TOL, 1e-15):
                raise Reject(f"step {si}: rho*g = {rho * g:.6g} N/mm^3, it must be {RHO_G:g} "
                             "(10 MPa at the clamp)")

    (p1, g1), (p2, g2), (p3, g3) = (split(state, si) for si, state in enumerate(states, 1))
    if g1:
        raise Reject("step 1 must carry the edge traction only, no body force")
    check_traction(p1, 1)
    if p2:
        raise Reject("step 2 must not keep the step-1 traction (drop it, for example with *DLOAD, OP=NEW)")
    check_grav(g2, 2)
    check_traction(p3, 3)
    check_grav(g3, 3)
    for si, step in enumerate(deck["steps"], 1):
        if not any("U" in asked and free <= ids for ids, asked in step["prints"]):
            raise Reject(f"step {si}: *NODE PRINT must request U for the node set FREE")
        if not any("RF" in asked and clamp <= ids for ids, asked in step["prints"]):
            raise Reject(f"step {si}: *NODE PRINT must request RF for the node set CLAMP")
    return free, clamp


# ---------------------------------------------------------------- .dat parsing
def parse_dat(text: str) -> dict:
    """{step: {"U": {node: (ux, uy, uz)}, "RF": {node: (fx, fy, fz)}}}: every print
    request of a step is merged; the last record of a node wins."""
    steps, step, kind = {}, 0, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line[0].isalpha() or line[0] == "*":             # a header line
            found = re.match(r"S\s+T\s+E\s+P\s+(\d+)", line)
            if found:
                step = int(found.group(1))
                steps.setdefault(step, {"U": {}, "RF": {}})
                kind = None
            else:
                kind = "RF" if line[:4].lower() == "forc" else "U" if line[:5].lower() == "displ" else None
            continue
        values = re.findall(NUMBER, line)
        try:
            if step and kind and len(values) >= 4:
                steps[step][kind][int(values[0])] = tuple(_num(v) for v in values[1:4])
        except ValueError:
            pass
    return steps


def results(dat: dict, free: set, clamp: set) -> tuple | None:
    """(ux1, uy1, ux2, ux3, [clamp reaction sums in x for steps 1..3])."""
    if set(dat) != {1, 2, 3}:
        return None
    if any(not free <= set(dat[s]["U"]) or not clamp <= set(dat[s]["RF"]) for s in (1, 2, 3)):
        return None
    ux = [sum(dat[s]["U"][n][0] for n in free) / len(free) for s in (1, 2, 3)]
    uy1 = sum(dat[1]["U"][n][1] for n in free) / len(free)
    return ux[0], uy1, ux[1], ux[2], [sum(dat[s]["RF"][n][0] for n in clamp) for s in (1, 2, 3)]


def field_mismatch(a: dict, b: dict, free: set, clamp: set) -> str | None:
    """First printed value in a that differs from the fresh run b."""
    for s in (1, 2, 3):
        for kind, ids in (("U", free), ("RF", clamp)):
            for n in sorted(ids):
                for i, axis in enumerate("xyz"):
                    if not close_enough(a[s][kind][n][i], b[s][kind][n][i], RUN_REL_TOL, NOISE):
                        return (f"step {s}, node {n}: {kind}{axis} is {a[s][kind][n][i]:.6E} "
                                f"in plate.dat, {b[s][kind][n][i]:.6E} in the re-solve")
    return None


def resolve(path: Path) -> dict | None:
    """L3: run the submitted deck unchanged in a scratch directory."""
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        shutil.copyfile(path, scratch / "plate.inp")
        subprocess.run([CCX, "plate"], cwd=scratch, timeout=180, check=False, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "plate.dat"
        return parse_dat(dat.read_text(errors="ignore")) if dat.is_file() else None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    try:
        return _evaluate()
    except Reject as exc:
        return _fail(str(exc))
    except (ValueError, KeyError, IndexError, TypeError, ArithmeticError) as exc:
        return _fail(f"malformed artifact ({type(exc).__name__}: {exc})")


def _evaluate() -> bool:
    for rel in REQUIRED_ARTIFACTS:                                                   # L1
        path = AGENT_ROOT / rel
        if not path.is_file() or path.stat().st_size == 0:
            raise Reject(f"missing or empty artifact: {rel}")
    free, clamp = conformance((AGENT_ROOT / "plate.inp").read_text(errors="ignore"))    # L2

    raw = (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip()
    fields = [f.strip() for f in raw.split(",")]
    if any(c in raw for c in "\r\n") or len(fields) != 4:
        raise Reject(f"summary.txt must be exactly one line of four comma-separated numbers "
                     f"(ux1, uy1, ux2, ux3); found {len(fields)} fields")
    try:
        ux1, uy1, ux2, ux3 = map(_num, fields)
    except ValueError:
        raise Reject("the summary.txt fields are not numbers") from None
    if not all(map(math.isfinite, (ux1, uy1, ux2, ux3))):
        raise Reject("the summary.txt fields must be finite numbers")

    submitted_dat = parse_dat((AGENT_ROOT / "plate.dat").read_text(errors="ignore"))
    submitted = results(submitted_dat, free, clamp)
    if submitted is None:
        raise Reject("plate.dat must hold three step blocks with U of every FREE node "
                     "and RF of every CLAMP node")
    fresh = resolve(AGENT_ROOT / "plate.inp")                                        # L3
    resub = results(fresh, free, clamp) if fresh else None
    if resub is None:
        raise Reject("the independent re-solve did not print U of FREE and RF of CLAMP in three steps")
    why = field_mismatch(submitted_dat, fresh, free, clamp)
    if why:
        raise Reject(f"plate.dat does not match the independent re-solve: {why}")
    for name, a, b in zip(("ux1", "uy1", "ux2", "ux3"), (ux1, uy1, ux2, ux3), resub):
        if not close_enough(a, b, SUMMARY_REL_TOL, NOISE):
            raise Reject(f"{name} = {a:.6E} does not match the independent re-solve ({b:.6E})")

    # L4: physics nets on the reported numbers and on the submitted reactions
    if not close_enough(ux1, TRACTION * LENGTH / E_YOUNG, UX1_REL_TOL):
        raise Reject(f"ux1 = {ux1:.6E} mm is not close to the uniaxial extension sigma*L/E")
    if abs(uy1) > UY1_ABS_TOL:
        raise Reject(f"uy1 = {uy1:.6E} mm: the mean lateral displacement of the free edge "
                     "must vanish (antisymmetric about y = 50)")
    if not close_enough(ux2, -RHO_G * LENGTH**2 / (2 * E_YOUNG), UX2_REL_TOL):
        raise Reject(f"ux2 = {ux2:.6E} mm is not close to -(rho g) L^2/(2E), a shortening in -x")
    if abs(ux3 - (ux1 + ux2)) > SUPER_REL_TOL * abs(ux1):
        raise Reject("ux3 must equal ux1 + ux2 (linear superposition of the two load cases)")
    body = RHO_G * LENGTH * HEIGHT * THICK            # total body force, N
    share = RHO_G * (CELL / 2) * HEIGHT * THICK       # its part allocated to the clamped nodes
    rx1, rx2 = submitted[4][:2]
    if not close_enough(rx1, -TRACTION * HEIGHT * THICK, RF_REL_TOL, NOISE):
        raise Reject(f"the clamp reaction in step 1 is {rx1:.6g} N, expected about -20000 N")
    if not any(close_enough(rx2, t, RF_REL_TOL, NOISE) for t in (body, body - share)):
        raise Reject(f"the clamp reaction in step 2 is {rx2:.6g} N, expected about +2000 N")

    for pin, value in zip((EXPECTED_UX1, EXPECTED_UY1, EXPECTED_UX2, EXPECTED_UX3), resub):   # L5
        if pin is not None and not close_enough(value, pin, PINNED_REL_TOL, NOISE):
            raise Reject("the re-solve deviates from the pinned reference")
    return True


def main() -> int:
    try:
        ok = evaluate()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - a verifier never crashes open
        print(f"debug: evaluator exception: {exc!r}", file=sys.stderr)
        ok = False
    print("True" if ok else "False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
