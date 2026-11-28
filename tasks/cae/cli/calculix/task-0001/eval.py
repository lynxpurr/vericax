#!/usr/bin/env python3
"""VeriCAx verifier - task-0001 (cae--cli--calculix: stepped cantilever beam).

Implements L1 (completeness), L2 (design conformance) and L3 (independent
re-solve). L3 runs the submitted deck through the VM's own ccx in a scratch
directory, so the verdict is anchored to physics, never to the agent's claims.

Quantity choice: two NODAL displacements (uy at the step, uy at the tip).
Nodal values converge with mesh refinement and are the textbook quantities;
beam stress output in CalculiX is a section Gauss-point value (~0.58x the
outer-fibre stress) and would be ambiguous to request.

Three-way check:
  A  agent's summary.txt
  B  verifier's independent re-solve of the submitted deck   (tight)
  C  pinned reference values from the same image             (tight)
plus a loose Euler-Bernoulli sanity band (physics net).
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

# ---- pinned design (task-0001 instruction) ----
LENGTH, SPLIT_X = 100.0, 50.0
N_ELEM, ELEM_LEN = 10, 10.0
LOAD_FY = -100.0
E_YOUNG, NU = 210000.0, 0.3
SECTION_ROOT = (10.0, 10.0)
SECTION_TIP = (6.0, 6.0)

# ---- pinned reference, filled from the same VM image (ground_truth/) ----
EXPECTED_STEP_UY = -0.05981791   # pinned from the same VM image (ground_truth/)
EXPECTED_TIP_UY = -0.3463916    # pinned from the same VM image (ground_truth/)

RESOLVE_REL_TOL = 1.0e-4    # A vs B: same deck, same solver
PINNED_REL_TOL = 1.0e-3     # B vs C: allows solver-setting noise only
ANALYTIC_REL_TOL = 0.02     # A vs beam theory: converged mesh, 2% band


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-9) -> bool:
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
    """Parse a CalculiX deck into an ordered list of (keyword-line, data-lines).

    Keyword lines are uppercased; duplicate cards stay separate entries, since
    multiplicity and order-independent grouping are both checked here.
    """
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


# ---------------------------------------------------------------- .dat parsing
def parse_dat_blocks(dat_text: str):
    """Yield (header, rows). Prose lines start blocks; numeric lines feed rows."""
    blocks, header, rows = [], None, []
    for raw in dat_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^[A-Za-z*]", line):
            if header:
                blocks.append((header, rows))
            header, rows = line, []
            continue
        parts = line.split()
        try:
            [float(p) for p in parts]
        except ValueError:
            continue
        rows.append(parts)
    if header:
        blocks.append((header, rows))
    return blocks


def dat_nodal_uy(dat_text: str, node: int) -> float | None:
    for header, rows in parse_dat_blocks(dat_text):
        if "displacements" not in header.lower():
            continue
        for parts in rows:
            try:
                if int(parts[0]) == node:
                    return float(parts[2])  # vy
            except (ValueError, IndexError):
                continue
    return None


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
def _elsets(blocks) -> dict[str, list[int]]:
    """Resolve element sets from *Elset cards and ELSET= on *Element cards."""
    sets: dict[str, list[int]] = {}
    for kw, data in blocks:
        base = kw_base(kw)
        if base.startswith("*ELEMENT"):
            name = kw_param(kw, "ELSET")
            ids = []
            for line in data:
                vals = _floats(line)
                if vals:
                    ids.append(int(vals[0]))
            if name:
                sets.setdefault(name.upper(), []).extend(ids)
        elif base == "*ELSET":
            name = kw_param(kw, "ELSET")
            if not name and data:
                # *Elset with the name on the data line is not valid CCX syntax
                continue
            ids = []
            for line in data:
                vals = _floats(line)
                if vals:
                    ids.extend(int(v) for v in vals)
            sets.setdefault(name.upper(), []).extend(ids)
    return sets


def l2_design_conformance(inp_text: str) -> bool:
    """Check the deck builds the prescribed stepped beam.

    Node ids are pinned by the instruction: node i sits at x=(i-1)*10mm.
    Sections must be assigned by region: elements 1-5 -> 10x10, 6-10 -> 6x6.
    """
    blocks = inp_blocks(inp_text)

    # ---- nodes: exactly 11, ids 1..11 at x=10*(i-1)
    node_lines = [l for kw, data in blocks if kw_base(kw) == "*NODE" for l in data]
    if len(node_lines) != N_ELEM + 1:
        return _fail(f"expected exactly {N_ELEM + 1} nodes")
    nodes: dict[int, tuple[float, float, float]] = {}
    for line in node_lines:
        vals = _floats(line)
        if not vals or len(vals) != 4:
            return _fail(f"malformed node line: {line}")
        nodes[int(vals[0])] = tuple(vals[1:4])
    if sorted(nodes) != list(range(1, N_ELEM + 2)):
        return _fail("node ids must be 1..11")
    for i in range(1, N_ELEM + 2):
        expected = (ELEM_LEN * (i - 1), 0.0, 0.0)
        got = nodes[i]
        if not all(close_enough(g, e, 0.0, abs_tol=1e-6) for g, e in zip(got, expected)):
            return _fail(f"node {i} must sit at x={expected[0]}")

    # ---- elements: exactly 10 B31, element e joins nodes e and e+1
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
    if len(conns) != N_ELEM:
        return _fail(f"expected exactly {N_ELEM} elements")
    if sorted(conns) != sorted((e, e, e + 1) for e in range(1, N_ELEM + 1)):
        return _fail("element e must join nodes e and e+1")

    # ---- material
    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        return _fail("expected exactly one *Elastic")
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        return _fail("material constants changed")

    # ---- sections assigned by region through element sets
    sets = _elsets(blocks)
    thick = set(range(1, 6))     # elements 1..5 -> root section
    thin = set(range(6, 11))     # elements 6..10 -> tip section
    assigned: dict[int, tuple[float, float]] = {}
    sec_cards = [(kw, data) for kw, data in blocks if kw_base(kw).startswith("*BEAM SECTION")]
    if len(sec_cards) != 2:
        return _fail("expected exactly two *Beam Section cards")
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
    if set(assigned) != thick | thin:
        return _fail("every element must get exactly one section assignment")
    for e in thick:
        if assigned[e] != SECTION_ROOT:
            return _fail(f"element {e} must use the 10x10 section")
    for e in thin:
        if assigned[e] != SECTION_TIP:
            return _fail(f"element {e} must use the 6x6 section")

    # ---- load at the tip node (11), dof 2
    cload = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(cload) != 1:
        return _fail("expected exactly one *Cload line")
    vals = _floats(cload[0])
    if not vals or int(vals[0]) != N_ELEM + 1 or int(vals[1]) != 2 or abs(vals[2] - LOAD_FY) > 1e-9:
        return _fail("tip load changed")

    # ---- clamp at node 1, dofs 1-6
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
def _all_entity_ids(blocks) -> tuple[list[int], list[int]]:
    nodes: list[int] = []
    elems: list[int] = []
    for kw, data in blocks:
        base = kw_base(kw)
        if base == "*NODE":
            for line in data:
                vals = _floats(line)
                if vals:
                    nodes.append(int(vals[0]))
        elif base.startswith("*ELEMENT"):
            for line in data:
                vals = _floats(line)
                if vals:
                    elems.append(int(vals[0]))
    return nodes, elems


def _ensure_output_requests(text: str) -> str:
    """Guarantee `.dat` print requests covering every node.

    `.dat` is written by `*Node Print`; it needs an explicit node set (`NALL`
    is an Abaqus convention that CalculiX does not provide). The verifier
    declares its own set over the deck's ids; no model data is altered.
    """
    if "VCAX_ALL_NODES" in text:
        return text
    blocks = inp_blocks(text)
    nodes, _elems = _all_entity_ids(blocks)
    if not nodes:
        return text
    injection = (
        "*Nset, nset=VCAX_ALL_NODES\n" + ", ".join(str(n) for n in nodes) + "\n"
        "*Node Print, NSET=VCAX_ALL_NODES\nU\n"
    )
    return re.sub(r"(?im)^\*end step\s*$", injection + "*End Step", text, count=1)


def l3_resolve(inp_path: Path) -> tuple[float | None, float | None] | None:
    """Re-solve the submitted deck; return (step_uy at node 6, tip_uy at node 11)."""
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
        return dat_nodal_uy(dat_text, 6), dat_nodal_uy(dat_text, N_ELEM + 1)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- analytic net
def analytic_deflections() -> tuple[float, float]:
    """Euler-Bernoulli two-segment cantilever: (uy at split, uy at tip)."""
    i1 = SECTION_ROOT[0] ** 4 / 12.0
    i2 = SECTION_TIP[0] ** 4 / 12.0
    a = SPLIT_X
    d_split = (LOAD_FY / E_YOUNG) * ((LENGTH * a**2 / 2.0 - a**3 / 6.0) / i1)
    d_tip = (LOAD_FY / E_YOUNG) * (
        ((LENGTH**3 - (LENGTH - a) ** 3) / 3.0) / i1 + ((LENGTH - a) ** 3 / 3.0) / i2
    )
    return d_split, d_tip


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_conformance(inp_text):
        return False

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        return _fail("summary.txt must be two comma-separated floats: step_uy, tip_uy")

    resolved = l3_resolve(AGENT_ROOT / "solution.inp")
    if resolved is None or resolved[0] is None or resolved[1] is None:
        return _fail("independent re-solve failed to produce results")
    step_uy, tip_uy = summary

    # A vs B: submitted numbers must match the submitted model's own physics.
    if not close_enough(step_uy, resolved[0], RESOLVE_REL_TOL):
        return _fail("step_uy does not match independent re-solve of solution.inp")
    if not close_enough(tip_uy, resolved[1], RESOLVE_REL_TOL):
        return _fail("tip_uy does not match independent re-solve of solution.inp")

    # B vs C: the model must be the pinned one (guards against L2 blind spots).
    if EXPECTED_STEP_UY is not None and not close_enough(resolved[0], EXPECTED_STEP_UY, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (step_uy)")
    if EXPECTED_TIP_UY is not None and not close_enough(resolved[1], EXPECTED_TIP_UY, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (tip_uy)")

    # A vs beam theory: the converged mesh must reproduce classical results.
    a_step, a_tip = analytic_deflections()
    if not close_enough(step_uy, a_step, ANALYTIC_REL_TOL):
        return _fail("step_uy inconsistent with beam theory")
    if not close_enough(tip_uy, a_tip, ANALYTIC_REL_TOL):
        return _fail("tip_uy inconsistent with beam theory")
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
