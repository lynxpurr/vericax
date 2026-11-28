#!/usr/bin/env python3
"""VeriCAx verifier - cross-solver task-0002 (software-selection, L6).

The task requires CalculiX: the client demands a native Abaqus-style deck and
result pair (.inp + .dat) for a linearized buckling analysis (*BUCKLE), which
dolfinx 0.10 cannot deliver (no buckling solver, and its native result family
is XDMF/HDF5). L6 enforcement:

  L1  completeness
  L2  deck conformance + the challenge set name
  L3  independent re-solve (*BUCKLE re-run on the submitted deck)
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
TOKEN = os.environ.get("VERICAX_CHALLENGE", "VCAX_AUDIT_0002")
REQUIRED_TOOL = "calculix"

LENGTH, N_ELEM, ELEM_LEN = 100.0, 10, 10.0
SIDE = 10.0
E_YOUNG, NU = 210000.0, 0.3
LOAD_AXIAL = -1000.0     # compression at the free end (dof 1)
N_EIGS = 4

EXPECTED_BUCKLE_FACTOR = None   # pinned from the same VM image (ground_truth/)

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
    """Parse the buckling-factor table: (mode no, factor) pairs between the
    "BUCKLING FACTOR OUTPUT" header and the first eigenmode section."""
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
            if "BUCKLINGFACTOROUTPUT" in compact:
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
    """The pre-buckling displacement block printed under the reference load."""
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
def l2_design_conformance(inp_text: str) -> bool:
    blocks = inp_blocks(inp_text)
    token = TOKEN.upper()

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
        return _fail("node ids must be 1..11")
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
    if len(sec_cards) != 1:
        return _fail("expected exactly one *Beam Section")
    kw, data = sec_cards[0]
    if "RECT" not in kw:
        return _fail("the beam section must be section=RECT")
    name = kw_param(kw, "ELSET")
    if not name or set(sets.get(name.upper(), [])) != set(range(1, N_ELEM + 1)):
        return _fail("beam section must cover all elements")
    if not data:
        return _fail("*Beam Section needs a data line")
    vals = _floats(data[0])
    if not vals or len(vals) < 2 or abs(vals[0] - SIDE) > 1e-9 or abs(vals[1] - SIDE) > 1e-9:
        return _fail("beam section must be 10 x 10 mm")

    boundary_lines = [l for kw, data in blocks if kw_base(kw) == "*BOUNDARY" for l in data]
    if not boundary_lines:
        return _fail("missing clamped boundary")
    for line in boundary_lines:
        vals = _floats(line)
        if not vals:
            continue
        if not (int(vals[0]) == 1 and int(vals[1]) == 1 and int(vals[2]) == 6):
            return _fail("only node 1 dofs 1-6 may be constrained")
        if len(vals) > 3 and abs(vals[3]) > 1e-12:
            return _fail("clamped boundary must be zero")

    cload = [l for kw, data in blocks if kw_base(kw) == "*CLOAD" for l in data]
    if len(cload) != 1:
        return _fail("expected exactly one *Cload line")
    vals = _floats(cload[0])
    if not vals or int(vals[0]) != N_ELEM + 1 or int(vals[1]) != 1 or abs(vals[2] - LOAD_AXIAL) > 1e-9:
        return _fail("axial reference load changed")

    steps = [kw for kw, _data in blocks if kw_base(kw) == "*STEP"]
    buckles = [kw for kw, _data in blocks if kw_base(kw) == "*BUCKLE"]
    if len(steps) != 1 or len(buckles) != 1:
        return _fail("expected exactly one *Step with one *Buckle (no *Static)")
    if any(kw_base(kw) == "*STATIC" for kw, _data in blocks):
        return _fail("*Static is not allowed in the buckling task")

    # *Buckle carries the eigenvalue count as its first data line
    _kw, bdata = next((kw, d) for kw, d in blocks if kw_base(kw) == "*BUCKLE")
    bvals = _floats(bdata[0]) if bdata else None
    if not bvals or int(bvals[0]) < 1:
        return _fail("*Buckle must request at least one eigenvalue")

    nsets = _nsets(blocks)
    if set(nsets.get(token, [])) != set(range(1, N_ELEM + 2)):
        return _fail(f"node set {TOKEN} must contain all 11 nodes")

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
        return _fail("submitted solution.dat has no buckling-factor table")
    submitted_static = dat_static_field(dat_text, TOKEN)
    if not submitted_static:
        return _fail(f"submitted solution.dat has no reference-load field for set {TOKEN}")
    submitted_mode = dat_mode_field(dat_text, TOKEN, 1)
    if not submitted_mode:
        return _fail(f"submitted solution.dat has no mode-1 eigenmode block for set {TOKEN}")

    fresh_values, fresh_text = l3_resolve(AGENT_ROOT / "solution.inp")
    if not fresh_values or fresh_text is None:
        return _fail("independent re-solve failed to produce the buckling output")
    fresh_static = dat_static_field(fresh_text, TOKEN)
    fresh_mode = dat_mode_field(fresh_text, TOKEN, 1)
    if fresh_static is None or fresh_mode is None:
        return _fail("independent re-solve lacks the token-bound displacement blocks")

    # L6.2: the submitted native result must be this tool's output for this deck.
    if len(submitted_values) != len(fresh_values):
        return _fail("buckling factor count differs from the re-run")
    for a, b in zip(submitted_values, fresh_values):
        if not close_enough(a, b, FIELD_REL_TOL):
            return _fail(f"buckling factor differs from the fresh run: {a} vs {b}")

    for label, sub, fresh in (("reference-load", submitted_static, fresh_static),
                              ("mode-1", submitted_mode, fresh_mode)):
        if set(sub) != set(fresh):
            return _fail(f"submitted {label} field does not cover the same nodes as the re-run")
        for nid in sorted(fresh):
            for actual, expected in zip(sub[nid], fresh[nid]):
                if not close_enough(actual, expected, FIELD_REL_TOL):
                    return _fail(f"submitted {label} field differs from the fresh run at node {nid}")

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 1:
        return _fail("summary.txt must be one number: the mode-1 buckling factor")
    try:
        factor_s = float(summary[0])
    except ValueError:
        return _fail("summary.txt value is not a number")
    if not close_enough(factor_s, fresh_values[0], RESOLVE_REL_TOL):
        return _fail("buckling factor does not match the independent re-solve")
    if EXPECTED_BUCKLE_FACTOR is not None and not close_enough(
            fresh_values[0], EXPECTED_BUCKLE_FACTOR, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (buckling factor)")
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
