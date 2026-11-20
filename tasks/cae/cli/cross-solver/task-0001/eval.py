#!/usr/bin/env python3
"""VeriCAx verifier - cross-solver task-0001 (L6 provenance conformance).

This is the P2 spike prototype, not a true `software-selection` task: the
image contains CalculiX only, so the agent cannot choose a second tool. It
validates the rejection half of L6:

  L1  completeness
  L2  deck conformance + the challenge set name
  L3  independent re-solve
  L6  the SUBMITTED full-field .dat must equal the verifier's fresh .dat for
      every node in the challenge set; a fabricated, replayed or foreign
      native result is rejected.

The task is honest about its capability: `single-execution`.
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
TOKEN = "VCAX_AUDIT_0001"

LENGTH, N_ELEM, ELEM_LEN = 100.0, 10, 10.0
SIDE = 10.0
E_YOUNG, NU = 210000.0, 0.3
LOAD_FY = -100.0

EXPECTED_TIP_UY = None      # pinned from the same VM image (ground_truth/)

RESOLVE_REL_TOL = 1.0e-4    # summary vs independent re-solve
FIELD_REL_TOL = 1.0e-4      # submitted .dat vs fresh .dat, every component
PINNED_REL_TOL = 1.0e-3


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-9) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * max(abs(actual), abs(target)))


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


# ---------------------------------------------------------------- .dat parsing
def dat_token_field(dat_text: str, token: str) -> dict[int, tuple[float, float, float]] | None:
    """Return the displacement field printed 'for set <token>' (last block)."""
    header = None
    current: dict[int, tuple[float, float, float]] | None = None
    result = None
    for raw in dat_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.match(r"^[A-Za-z*]", s):
            if "displacements" in s.lower() and token.lower() in s.lower():
                current = {}
                result = current
            else:
                current = None
            continue
        if current is not None:
            p = s.split()
            try:
                current[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
            except (ValueError, IndexError):
                pass
    return result


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
    if not vals or int(vals[0]) != N_ELEM + 1 or int(vals[1]) != 2 or abs(vals[2] - LOAD_FY) > 1e-9:
        return _fail("tip load changed")

    if not any(kw_base(kw) == "*STATIC" for kw, _data in blocks):
        return _fail("missing *Static step")

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
def _ensure_output_requests(text: str) -> str:
    blocks = inp_blocks(text)
    if any(kw_base(kw) == "*NODE PRINT" for kw, _data in blocks):
        return text
    ids = sorted({int(_floats(l)[0]) for kw, data in blocks
                  if kw_base(kw) == "*NODE" for l in data if _floats(l)})
    injection = ("*Nset, nset=VCAX_ALL_NODES\n"
                 + ", ".join(str(n) for n in ids) + "\n"
                 "*Node Print, NSET=VCAX_ALL_NODES\nU\n")
    return re.sub(r"(?im)^\*end step\s*$", injection + "*End Step", text, count=1)


def l3_resolve(inp_path: Path) -> tuple[dict[int, tuple[float, float, float]] | None, float | None]:
    scratch = Path(tempfile.mkdtemp(prefix="vericax-eval-"))
    try:
        text = _ensure_output_requests(inp_path.read_text(errors="ignore"))
        (scratch / "solution.inp").write_text(text)
        subprocess.run([CCX, "solution"], cwd=scratch, timeout=300, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dat = scratch / "solution.dat"
        if not dat.is_file() or dat.stat().st_size == 0:
            return None, None
        field = dat_token_field(dat.read_text(errors="ignore"), TOKEN)
        if not field or (N_ELEM + 1) not in field:
            return field, None
        return field, field[N_ELEM + 1][1]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False
    inp_text = (AGENT_ROOT / "solution.inp").read_text(errors="ignore")
    if not l2_design_conformance(inp_text):
        return False

    submitted = dat_token_field((AGENT_ROOT / "solution.dat").read_text(errors="ignore"), TOKEN)
    if not submitted:
        return _fail(f"submitted solution.dat has no displacement block for set {TOKEN}")

    fresh, tip = l3_resolve(AGENT_ROOT / "solution.inp")
    if fresh is None or tip is None:
        return _fail("independent re-solve failed to produce the challenge field")

    # L6.2: the submitted native result must be the tool's output for this deck.
    if set(submitted) != set(fresh):
        return _fail("submitted field does not cover the same nodes as the re-run")
    for nid in sorted(fresh):
        for actual, expected in zip(submitted[nid], fresh[nid]):
            if not close_enough(actual, expected, FIELD_REL_TOL):
                return _fail(f"submitted field differs from the fresh run at node {nid}")

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(errors="ignore").strip().split(",")]
    if len(summary) != 1:
        return _fail("summary.txt must be one number: tip_uy")
    try:
        tip_s = float(summary[0])
    except ValueError:
        return _fail("summary.txt value is not a number")
    if not close_enough(tip_s, tip, RESOLVE_REL_TOL):
        return _fail("tip_uy does not match the independent re-solve")
    if EXPECTED_TIP_UY is not None and not close_enough(tip, EXPECTED_TIP_UY, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (tip_uy)")
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