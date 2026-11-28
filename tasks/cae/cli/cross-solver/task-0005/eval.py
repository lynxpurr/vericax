#!/usr/bin/env python3
"""VeriCAx verifier - cross-solver task-0005 (software-selection, L6).

The task requires CalculiX: the client demands a native Abaqus-style deck and
result pair (.inp + .dat) with the solver's own eigenvalue table and mode
shapes (*FREQUENCY), which only CalculiX delivers in that native family
(dolfinx checkpoints are XDMF/HDF5). L6 enforcement:

  L1  completeness
  L2  deck conformance + the challenge set name
  L3  independent re-solve (*FREQUENCY re-run on the submitted deck)
  L6  the SUBMITTED .dat must equal the verifier's fresh .dat: the buckling
      factor and the printed mode-shape field for the challenge set; a
      fabricated, replayed or foreign (XDMF/HDF5) native result is rejected.

spec/02 section 6 boundary: this proves artifact-tool equivalence, not that
the agent executed the tool.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3", "L6")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))
CCX = os.environ.get("VERICAX_CCX", "/usr/bin/ccx")

REQUIRED_ARTIFACTS = ["solution.inp", "solution.dat", "summary.txt"]
# L6.3: the grading instance injects the per-episode token (and required tool)
# through the environment; audit/L0 runs carry no env and keep the fixed token.
TOKEN = os.environ.get("VERICAX_CHALLENGE", "VCAX_AUDIT_0005")
REQUIRED_TOOL = "calculix"

LENGTH, N_ELEM, ELEM_LEN = 100.0, 10, 10.0
SIDE = 10.0
E_YOUNG, NU = 210000.0, 0.3

EXPECTED_FREQ_1 = None   # pinned from the same VM image (ground_truth/)

RESOLVE_REL_TOL = 1.0e-4    # summary vs independent re-solve
FIELD_REL_TOL = 1.0e-4      # submitted mode shape vs fresh run, every component
PINNED_REL_TOL = 1.0e-3


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-9) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * max(abs(actual), abs(target)))


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


# ---------------------------------------------------------------- .dat parsing
def _compact(s: str) -> str:
    return re.sub(r"\s+", "", s).upper()


def dat_eigenvalues(dat_text: str) -> list[float]:
    """Parse the eigenvalue table: (mode no, eigenvalue) pairs between the
    "EIGENVALUE OUTPUT" header and the first eigenmode section."""
    values: list[float] = []
    state = 0  # 0 = outside, 1 = inside table
    for raw in dat_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        compact = _compact(s)
        if re.match(r"^[A-Za-z*]", s):
            if state == 1 and "EIGENVALUENUMBER" in compact:
                break
            if "EIGENVALUEOUTPUT" in compact:
                state = 1
            continue
        if state == 1:
            p = s.split()
            if len(p) >= 2:
                try:
                    mode = int(p[0])
                    value = float(p[1])
                except ValueError:
                    continue
                if mode == len(values) + 1:
                    values.append(value)
    return values


def _displacement_block(text: str, token: str) -> dict[int, tuple[float, float, float]] | None:
    """Collect the displacement block for the set <token>: the first
    "displacements ... <token>" header and its data rows (up to the next
    letter-prefixed line)."""
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        if re.match(r"^[A-Za-z*]", s):
            if "DISPLACEMENTS" in _compact(s) and token.lower() in s.lower():
                current: dict[int, tuple[float, float, float]] = {}
                for raw2 in lines[i + 1:]:
                    s2 = raw2.strip()
                    if not s2:
                        continue
                    if re.match(r"^[A-Za-z*]", s2):
                        break
                    p = s2.split()
                    try:
                        current[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
                    except (ValueError, IndexError):
                        pass
                return current
    return None


def dat_static_field(dat_text: str, token: str) -> dict[int, tuple[float, float, float]] | None:
    """The first token-bound displacement block (unused for the modal task; kept
    for symmetry with the buckling verifier)."""
    return _displacement_block(dat_text, token)


def dat_mode_field(dat_text: str, token: str, mode: int = 1) -> dict[int, tuple[float, float, float]] | None:
    """The eigenmode displacement block printed after
    "EIGENVALUE NUMBER <mode>"."""
    lines = dat_text.splitlines()
    start = None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s and re.match(r"^[A-Za-z*]", s) and f"EIGENVALUENUMBER{mode}" in _compact(s):
            start = i
            break
    if start is None:
        return None
    return _displacement_block("\n".join(lines[start:]), token)


# ---------------------------------------------------------------- L1
def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


# ---------------------------------------------------------------- L2
W, H = 100.0, 100.0
GRID = 10                   # 10 x 10 CPS4 elements
NODES_PER_EDGE = GRID + 1
THICKNESS = 1.0
DENSITY = 7.85e-9     # tonne/mm^3 (steel), required by *Frequency


def _grid_nodes(nodes):
    for nid, (x, y, _z) in nodes.items():
        gx = (nid - 1) % NODES_PER_EDGE
        gy = (nid - 1) // NODES_PER_EDGE
        if not (close_enough(x, 10.0 * gx, 0.0, abs_tol=1e-6)
                and close_enough(y, 10.0 * gy, 0.0, abs_tol=1e-6)):
            return False
    return True


def l2_design_conformance(inp_text: str) -> bool:
    blocks = inp_blocks(inp_text)
    token = TOKEN.upper()

    node_lines = [l for kw, data in blocks if kw_base(kw) == "*NODE" for l in data]
    if len(node_lines) != NODES_PER_EDGE ** 2:
        return _fail(f"expected exactly {NODES_PER_EDGE ** 2} grid nodes")
    nodes = {}
    for line in node_lines:
        vals = _floats(line)
        if not vals or len(vals) != 4:
            return _fail(f"malformed node line: {line}")
        nodes[int(vals[0])] = tuple(vals[1:4])
    if sorted(nodes) != list(range(1, NODES_PER_EDGE ** 2 + 1)):
        return _fail("node ids must be 1..121 in grid order")
    if not _grid_nodes(nodes):
        return _fail("nodes must follow the 10 mm grid in id order")

    elem_blocks = [(kw, data) for kw, data in blocks if kw_base(kw).startswith("*ELEMENT")]
    if not elem_blocks or not all("CPS4" in kw for kw, _ in elem_blocks):
        return _fail("all element cards must be type CPS4")
    conns = []
    for _kw, data in elem_blocks:
        for line in data:
            vals = _floats(line)
            if not vals or len(vals) != 5:
                return _fail(f"malformed element line: {line}")
            conns.append(tuple(int(v) for v in vals))
    expected_elems = set()
    for gy in range(GRID):
        for gx in range(GRID):
            n1 = gy * NODES_PER_EDGE + gx + 1
            n2 = n1 + 1
            n3 = n1 + NODES_PER_EDGE
            n4 = n3 + 1
            expected_elems.add((GRID * gy + gx + 1, n1, n2, n4, n3))
    if sorted(conns) != sorted(expected_elems):
        return _fail("CPS4 elements must follow the standard grid ordering")

    elastic = [l for kw, data in blocks if kw_base(kw) == "*ELASTIC" for l in data]
    if len(elastic) != 1:
        return _fail("expected exactly one *Elastic")
    vals = _floats(elastic[0])
    if not vals or abs(vals[0] - E_YOUNG) > 1e-9 or abs(vals[1] - NU) > 1e-9:
        return _fail("material constants changed")
    density = [l for kw, data in blocks if kw_base(kw) == "*DENSITY" for l in data]
    if len(density) != 1:
        return _fail("expected exactly one *Density (mass matrix)")
    dvals = _floats(density[0])
    if not dvals or abs(dvals[0] - DENSITY) > 1e-18:
        return _fail("density changed")

    sets = _elsets(blocks)
    sec_cards = [(kw, data) for kw, data in blocks if kw_base(kw).startswith("*SOLID SECTION")]
    if len(sec_cards) != 1:
        return _fail("expected exactly one *Solid Section")
    kw, data = sec_cards[0]
    name = kw_param(kw, "ELSET")
    if not name or set(sets.get(name.upper(), [])) != set(range(1, GRID ** 2 + 1)):
        return _fail("solid section must cover all elements")
    if not data:
        return _fail("*Solid Section needs the thickness data line")
    if abs(_floats(data[0])[0] - THICKNESS) > 1e-9:
        return _fail("thickness must be 1.0 mm")

    boundary_blocks = [(kw, data) for kw, data in blocks if kw_base(kw) == "*BOUNDARY"]
    if not boundary_blocks:
        return _fail("missing clamped boundary")
    clamped = set()
    for kw, data in boundary_blocks:
        # both forms are legal: per-node data lines, or an NSET name in the
        # first data field
        for line in data:
            vals = _floats(line)
            if not vals:
                name = line.split(",")[0].strip().strip("'\"")
                named = _nsets(blocks).get(name.upper(), [])
                if named:
                    clamped.update(named)
                continue
            nid = int(vals[0])
            if int(vals[1]) != 1 or int(vals[2]) != 2:
                return _fail("clamped boundary must fix dofs 1-2")
            clamped.add(nid)
            if len(vals) > 3 and abs(vals[3]) > 1e-12:
                return _fail("clamped boundary must be zero")
    expected_clamped = {r * NODES_PER_EDGE + 1 for r in range(NODES_PER_EDGE)}
    if clamped != expected_clamped:
        return _fail("the whole edge x = 0 must be clamped")

    steps = [kw for kw, _data in blocks if kw_base(kw) == "*STEP"]
    freqs = [kw for kw, _data in blocks if kw_base(kw) == "*FREQUENCY"]
    if len(steps) != 1 or len(freqs) != 1:
        return _fail("expected exactly one *Step with one *Frequency (no *Static)")
    if any(kw_base(kw) == "*STATIC" for kw, _data in blocks):
        return _fail("*Static is not allowed in the modal task")
    _kw, fdata = next((kw, d) for kw, d in blocks if kw_base(kw) == "*FREQUENCY")
    fvals = _floats(fdata[0]) if fdata else None
    if not fvals or int(fvals[0]) < 1:
        return _fail("*Frequency must request at least one eigenvalue")

    nsets = _nsets(blocks)
    if set(nsets.get(token, [])) != set(range(1, NODES_PER_EDGE ** 2 + 1)):
        return _fail(f"node set {TOKEN} must contain all 121 nodes")

    prints = [(kw, data) for kw, data in blocks if kw_base(kw) == "*NODE PRINT"]
    if not prints:
        return _fail("missing *Node Print")
    ok = False
    for kw, _data in prints:
        if (kw_param(kw, "NSET") or "").upper() == token:
            ok = True
    if not ok:
        return _fail(f"*Node Print must use NSET={TOKEN}")
    return True


# ---------------------------------------------------------------- L3/L6
def l3_resolve(inp_path: Path) -> tuple[list[float] | None, str | None]:
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        (scratch / "solution.inp").write_text(inp_path.read_text(errors="ignore"))
        subprocess.run([CCX, "solution"], cwd=scratch, timeout=300, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "solution.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            return None, None
        text = dat.read_text(errors="ignore")
        values = dat_eigenvalues(text)
        if not values:
            return None, None
        return values, text
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_conformance(inp_text):
        return False

    dat_text = (AGENT_ROOT / "solution.dat").read_text(errors="ignore")
    submitted_values = dat_eigenvalues(dat_text)
    if not submitted_values:
        return _fail("submitted solution.dat has no eigenvalue table")
    submitted_mode = dat_mode_field(dat_text, TOKEN, 1)
    if not submitted_mode:
        return _fail(f"submitted solution.dat has no mode-1 eigenmode block for set {TOKEN}")

    fresh_values, fresh_text = l3_resolve(AGENT_ROOT / "solution.inp")
    if not fresh_values or fresh_text is None:
        return _fail("independent re-solve failed to produce the modal output")
    fresh_mode = dat_mode_field(fresh_text, TOKEN, 1)
    if fresh_mode is None:
        return _fail("independent re-solve lacks the token-bound eigenmode block")

    # L6.2: the submitted native result must be this tool's output for this deck.
    if len(submitted_values) != len(fresh_values):
        return _fail("eigenvalue count differs from the re-run")
    for a, b in zip(submitted_values, fresh_values):
        if not close_enough(a, b, FIELD_REL_TOL):
            return _fail(f"eigenvalue differs from the fresh run: {a} vs {b}")

    for label, sub, fresh in (("mode-1", submitted_mode, fresh_mode),):
        if set(sub) != set(fresh):
            return _fail(f"submitted {label} field does not cover the same nodes as the re-run")
        for nid in sorted(fresh):
            for actual, expected in zip(sub[nid], fresh[nid]):
                if not close_enough(actual, expected, FIELD_REL_TOL):
                    return _fail(f"submitted {label} field differs from the fresh run at node {nid}")

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 1:
        return _fail("summary.txt must be one number: f1 in Hz")
    try:
        f1_s = float(summary[0])
    except ValueError:
        return _fail("summary.txt value is not a number")
    import math
    f1_fresh = math.sqrt(fresh_values[0]) / (2.0 * math.pi)
    if not close_enough(f1_s, f1_fresh, RESOLVE_REL_TOL):
        return _fail("f1 does not match the independent re-solve")
    if EXPECTED_FREQ_1 is not None and not close_enough(
            f1_fresh, EXPECTED_FREQ_1, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (f1)")
    return True


def main() -> int:
    tool = os.environ.get("VERICAX_TOOL")
    if tool is not None and tool != REQUIRED_TOOL:
        print(f"debug: VERICAX_TOOL={tool!r} does not match required {REQUIRED_TOOL!r}",
              file=sys.stderr)
        print("False")
        return 0
    try:
        ok = evaluate()
    except Exception as exc:  # noqa: BLE001 - verifier must never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        ok = False
    print("True" if ok else "False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
