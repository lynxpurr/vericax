"""Audit cases for cae--cli--calculix--task-0014 (exact_match; frequency, static, buckle).

Each entry is (label, bash script, expectation); CASES[0] is the gold and the
ground-truth source. Every case is ONE solver run composed as
``_run(env=..., after=...)``: an environment override changes the deck that
the generator writes, ``after`` is appended behind the single ``ccx`` run.
Never concatenate two runs: the second would overwrite the first deck.

Hand estimate the gold must agree with within a few percent (Euler-Bernoulli,
units mm, N, MPa, tonne). With the 24 mm side along y, the weak plane is
bending about y (depth 12 mm): I_weak = 24*12^3/12 = 3456 mm^4; the strong
plane is bending about z (depth 24 mm): I_strong = 12*24^3/12 = 13824 mm^4.
A = 288 mm^2, rho*A = 7.85e-9*288 = 2.2608e-6 t/mm, L = 1000 mm, a1 = 1.8751041.

  f_n   = a_n^2/(2 pi) sqrt(E I/(rho A L^4))
        f1 = 1.8751041^2/(2 pi) sqrt(210000*3456/(2.2608e-6*1e12)) = 10.0262 Hz
        f2 = 2 f1 = 20.0524 Hz (strong-axis first mode; the weak-axis second
        mode sits at (4.6941/1.8751)^2 = 6.267 f1 = 62.83 Hz and is not f2)
  lam_n = (2n-1)^2 pi^2 E I/(4 L^2) per newton of reference load
        lam1 = pi^2*210000*3456/(4*1000^2) = 1790.74 N
        lam2 = 4 lam1 = 7162.96 N (weak-axis second mode: 9 lam1 = 16116.7 N)
  ux2   = -L/(E A) = -1000/(210000*288) = -1.653439e-5 mm

Twenty B31 elements are within about 1 % of these; the pins are baked from
the measured gold summary, these numbers only bound it.

Why step 3 is *BUCKLE: a *FREQUENCY step prints eigenvalues in rad^2/s^2 and
frequencies (CalculiX 2.21 .dat of task-0005), never load factors; a *BUCKLE
step prints "B U C K L I N G   F A C T O R   O U T P U T" (task-0006). The
verified buckling decks of this suite define the reference load inside the
*BUCKLE step, so the gold restates the identical unit load there (N4 resets
it to zero and must fail).

Not verified offline (no ccx on the authoring host): the syntax of the beam
1-direction data line (gold: sizes line, then `0.0, 1.0, 0.0`), whether a *BUCKLE
step inherits the load of an earlier static step, and the run time. The numbers
cannot settle the first point: turning the rectangle swaps the two bending
planes and leaves f1, f2, lam1, lam2 unchanged, so the orientation is a property
of the deck text only (N7, N8), not of the result.
"""

GENERATOR = r'''
import os
from pathlib import Path

numbering = os.environ.get("NUMBERING", "forward")     # forward | reverse
load_ref = os.environ.get("LOAD_REF", "set")           # set | node
elset_card = os.environ.get("ELSET_CARD", "0") == "1"
bc_plain = os.environ.get("BC_PLAIN", "0") == "1"
nmodes = int(os.environ.get("NMODES", "2"))
defect = os.environ.get("DEFECT", "")
tcomma = os.environ.get("TCOMMA", "0") == "1"       # trailing comma before a keyword

n = 10 if defect == "ten_elements" else 20
dx = 1000.0 / n
stations = range(n + 1)
if numbering == "reverse":        # the root gets the highest node number
    ids = {i: n + 1 - i for i in stations}
    elems = [(n + 1 - e, e, e - 1) for e in range(1, n + 1)]   # listed tip -> root
else:
    ids = {i: i + 1 for i in stations}
    elems = [(e, e - 1, e) for e in range(1, n + 1)]           # listed root -> tip
root, mid, tip = ids[0], ids[n // 2], ids[n]


def ref(name, node):
    return str(node) if load_ref == "node" else name


lines = ["*Heading", "VeriCAx task-0014 column: frequency, static, buckle", "*Node"]
for i in stations:
    lines.append(f"{ids[i]}, {dx * i:.1f}, 0.0, 0.0")
lines.append("*Element, type=B31" + ("" if elset_card else ", elset=COLUMN"))
for eid, a, b in elems:
    lines.append(f"{eid}, {ids[a]}, {ids[b]}")
if elset_card:
    lines.append("*Elset, elset=COLUMN")
    for k in range(0, n, 16):     # at most 16 entries per data line
        lines.append(", ".join(str(e) for e, _a, _b in elems[k:k + 16]))
for name, node in (("ROOT", root), ("TIP", tip), ("MID", mid)):
    lines += [f"*Nset, nset={name}", str(node)]
lines += ["*Material, name=Steel", "*Elastic", "210000.0, 0.3"]
if defect != "no_density":
    lines += ["*Density", "7.85e-09"]
lines += ["*Beam Section, elset=COLUMN, material=Steel, section=RECT",
          "12.0, 24.0" if defect == "swap_sizes" else "24.0, 12.0",
          "0.0, 0.0, 1.0" if defect == "axis_z" else "0.0, 1.0, 0.0"]
lines.append("*Boundary")
lines.append("ROOT, 1, 3, 0.0" if defect == "clamp_123"
             else (f"{root}, 1, 6" if bc_plain else "ROOT, 1, 6, 0.0"))
if defect == "tip_fixed":
    lines.append("TIP, 2, 3, 0.0")

load = f"{ref('MID', mid) if defect == 'load_mid' else ref('TIP', tip)}, 1, "
load += "1.0" if defect == "tensile" else "-1.0"
freq = ["*Step", "*Frequency", str(nmodes), "*End Step"]
static = ["*Step", "*Static, nlgeom" if defect == "nlgeom" else "*Static",
          "*Cload", load, "*Node Print, NSET=TIP", "U", "*End Step"]
if defect == "freq_step3":
    last = ["*Step", "*Frequency", str(nmodes), "*End Step"]
elif defect == "drop_load_step3":
    last = ["*Step", "*Buckle", str(nmodes), "*Cload, OP=NEW", load.split(",")[0] + ", 1, 0.0",
            "*End Step"]
else:
    last = ["*Step", "*Buckle", str(nmodes), "*Cload", load, "*End Step"]
if defect == "order_static_first":
    steps = [static, freq, last]
elif defect == "two_steps":
    steps = [freq, static]
else:
    steps = [freq, static, last]
all_lines = lines + [l for s in steps for l in s]
if tcomma:
    # A comma at the end of a data line that is followed by a keyword. CalculiX
    # reads it as a terminator; a real deck used it (2026-11-28) and the first
    # verifier took it for a continuation.
    out, card = [], ""
    for i, l in enumerate(all_lines):
        nxt = next((o.strip() for o in all_lines[i + 1:] if o.strip()), "")
        if l.startswith("*"):
            card = l.split(",")[0].strip().upper()
        elif card != "*HEADING" and nxt.startswith("*"):
            l = l + ","
        out.append(l)
    all_lines = out
Path("column.inp").write_text("\n".join(all_lines) + "\n")
'''

# Independent of eval.py (stdlib only, specific to the CalculiX 2.21 layout).
SUMMARY = r'''
from pathlib import Path

tip, card = None, None
for raw in Path("column.inp").read_text().splitlines():
    s = raw.strip()
    if not s or s.startswith("**"):
        continue
    if s.startswith("*"):
        card = s.split(",")[0].strip().upper()
    elif card == "*NODE":
        p = [x.strip() for x in s.split(",") if x.strip()]     # a trailing comma is no field
        # z may be left out: 0 by default
        if len(p) in (3, 4) and abs(float(p[1]) - 1000.0) < 1e-6 and float(p[2]) == 0.0 \
                and (len(p) == 3 or float(p[3]) == 0.0):
            tip = int(p[0])
assert tip is not None, "TIP node not found in column.inp"

eigs, factors, ux, armed = [], [], None, None   # eigs: rows of each EIGENVALUE OUTPUT table
for raw in Path("column.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    compact = s.lower().replace(" ", "")
    if "eigenvalueoutput" in compact:
        armed = "eig"
        eigs.append([])
        continue
    if "bucklingfactoroutput" in compact:
        armed = "buckle"
        continue
    if compact.startswith("displacements"):
        armed = "disp"
        continue
    if any(k in compact for k in ("participationfactor", "effectivemodalmass",
                                  "totaleffectivemass", "eigenvaluenumber")):
        armed = None
        continue
    try:
        values = [float(x.replace("D", "E")) for x in s.split()]
    except ValueError:
        continue                       # column header lines
    if armed == "eig" and len(values) >= 4 and values[0] == int(values[0]):
        eigs[-1].append((values[1], values[3]))     # eigenvalue rad^2/s^2, cycles/time
    elif armed == "buckle" and len(values) == 2 and values[0] == int(values[0]):
        factors.append(values[1])
    elif armed == "disp" and int(values[0]) == tip and ux is None:
        ux = values[1]          # vx of TIP in the static step: the FIRST TIP record.
        # The buckle step repeats that block and then prints the mode shapes at
        # TIP ("E I G E N V A L U E    N U M B E R"), whose vx is ~0.
assert len(eigs) >= 1 and len(eigs[0]) >= 2 and ux is not None, "column.dat parse failed"
if len(factors) >= 2:
    lam = factors[:2]                 # buckling factors of the *BUCKLE step
elif len(eigs) >= 2:                  # no *BUCKLE table: the second eigenvalue table
    lam = [row[0] for row in eigs[1][:2]]
else:                                 # nothing to report; the verifier refuses the deck
    lam = [0.0, 0.0]
f1, f2 = eigs[0][0][1], eigs[0][1][1]
Path("summary.txt").write_text(f"{f1!r}, {f2!r}, {lam[0]!r}, {lam[1]!r}, {ux!r}\n")
'''


def _run(env: str = "", after: str = "") -> str:
    """One solver run: deck generator (environment overrides in ``env``), one
    ``ccx column``, the summary parser, then the optional tail ``after``."""
    prefix = f"{env} " if env else ""
    tail = f"\n{after}\n" if after else ""
    return (
        "set -e\n"
        "cd /home/user/Desktop\n"
        + prefix + "python3 - <<'PYEOF'\n"
        + GENERATOR
        + "\nPYEOF\n"
        "/usr/bin/ccx column > /tmp/ccx-column.log 2>&1"
        " || { tail -20 /tmp/ccx-column.log; exit 1; }\n"
        "python3 - <<'PYEOF'\n"
        + SUMMARY
        + "\nPYEOF\n"
        + tail
    )


GOLD = _run()
ALT = _run(env="NUMBERING=reverse BC_PLAIN=1")
ALT2 = _run(env="LOAD_REF=node ELSET_CARD=1 NMODES=3")
ALT3 = _run(env="TCOMMA=1")


def _resummary(body: str) -> str:
    return _run(after="python3 - <<'PY'\n" + body + "\nPY")


SWAP_F12 = _resummary(
    "v = [float(x) for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(', '.join(repr(x) for x in (v[1], v[0], v[2], v[3], v[4])) + '\\n')")
FABRICATE = _resummary(
    "v = [float(x) for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(', '.join(f'{x * 1.10:.9g}' for x in v) + '\\n')")

# One value of the native result edited: the TIP axial shortening x 10.
TAMPER_DAT = _run(after=r"""python3 - <<'PY'
import re
from pathlib import Path

tip, card = None, None
for raw in Path("column.inp").read_text().splitlines():
    s = raw.strip()
    if s.startswith("*"):
        card = s.split(",")[0].strip().upper()
    elif card == "*NODE":
        p = [x.strip() for x in s.split(",")]
        if len(p) == 4 and abs(float(p[1]) - 1000.0) < 1e-6:
            tip = p[0]
out, head, done = [], None, False
for raw in Path("column.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if s and re.match(r"^[A-Za-z*]", s):
        head = s.lower()
    p = s.split()
    if (not done and head and "displacements" in head and p and p[0] == tip):
        raw = " " + "  ".join([p[0], f"{float(p[1]) * 10:.6E}"] + p[2:])
        done = True
    out.append(raw)
assert done, "TIP displacement row not found"
Path("column.dat").write_text("\n".join(out) + "\n")
PY""")

ZERO_INP = _run(after=": > column.inp")
BAD_SUMMARY = _run(after="printf '10.0, 20.0, 1790.0, 7160.0\\n' > summary.txt")
ENCODE_SUMMARY = _run(after=r"""python3 - <<'PY'
import base64
from pathlib import Path
raw = Path("summary.txt").read_text().strip().encode()
Path("summary.txt").write_text(base64.b64encode(raw).decode() + "\n")
PY""")

# Only the metrics: closed-form numbers, no deck and no solver output.
METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '10.0262, 20.0524, 1790.74, 7162.96, -1.653439e-05' > summary.txt
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N17 tampered .dat (one value edited)": "tampered_input",
    "N13 skipped steps (deck with two steps)": "skipped_steps",
    "N15 fabricated summary (+10%)": "fabricated_field",
    "N20 metrics only": "metrics_only",
    "N21 encoded payload (base64 summary)": "encoded_payload",
}

# every legal spelling at once (added 2026-11-28)
# In B2 the agents wrote decks in spellings the verifiers could not read: GENERATE
# sets, a boundary row on a node set, two-coordinate node lines, a load on a
# one-member set, a comma at the end of a data line. The verifier must read them
# all and the solver must give the reference numbers. The decks below are GOLD's
# in that spelling (scripts/deck_variants.py, every variant chained), written
# just before the solver runs.

import re


def _in_heredoc(lines, at):
    """True when line ``at`` sits inside a quoted here-document of the shell script."""
    delimiter = None
    for line in lines[:at]:
        if delimiter is None:
            found = re.search(r"<<'([A-Za-z_]+)'", line)
            if found:
                delimiter = found.group(1)
        elif line.strip() == delimiter:
            delimiter = None
    return delimiter is not None


def _re_spelled(gold, decks):
    """GOLD with its decks overwritten by ``decks`` (file -> text) before the solver runs."""
    lines = gold.splitlines(keepends=True)
    at = next(i for i, line in enumerate(lines) if "/usr/bin/ccx" in line)
    if _in_heredoc(lines, at):          # the solver is started from the generating script
        block = "".join('Path(%r).write_text("""%s""")\n' % (name, text) for name, text in decks.items())
    else:
        block = "".join("cat > %s <<'VCAX_SPELLINGS'\n%sVCAX_SPELLINGS\n" % (name, text)
                        for name, text in decks.items())
    return "".join(lines[:at]) + block + "".join(lines[at:])

SPELLING_COLUMN = r"""*Heading
VeriCAx task-0014 column: frequency, static, buckle
*Node, NSET=VCAX_ALLNODES
1, 0.0, 0.0
2, 50.0, 0.0
3, 100.0, 0.0
4, 150.0, 0.0
5, 200.0, 0.0
6, 250.0, 0.0
7, 300.0, 0.0
8, 350.0, 0.0
9, 400.0, 0.0
10, 450.0, 0.0
11, 500.0, 0.0
12, 550.0, 0.0
13, 600.0, 0.0
14, 650.0, 0.0
15, 700.0, 0.0
16, 750.0, 0.0
17, 800.0, 0.0
18, 850.0, 0.0
19, 900.0, 0.0
20, 950.0, 0.0
21, 1000.0, 0.0
*Element, type=B31, elset=COLUMN
1, 1, 2
2, 2, 3
3, 3, 4
4, 4, 5
5, 5, 6
6, 6, 7
7, 7, 8
8, 8, 9
9, 9, 10
10, 10, 11
11, 11, 12
12, 12, 13
13, 13, 14
14, 14, 15
15, 15, 16
16, 16, 17
17, 17, 18
18, 18, 19
19, 19, 20
20, 20, 21,
*Nset, nset=ROOT
1,
*Nset, nset=TIP
21,
*Nset, nset=MID
11,
*Material, name=Steel
*Elastic
210000.0, 0.3,
*Density
7.85e-09,
*Beam Section, elset=COLUMN, material=Steel, section=RECT
24.0, 12.0
0.0, 1.0, 0.0,
*Boundary
ROOT, 1, 6
** node sets named by the *Boundary rows
** sets of one member, named by the load rows
*Step
*Frequency
2,
*End Step
*Step
*Static
*Cload
21, 1, -1.0
*Node Print, NSET=TIP
U,
*End Step
*Step
*Buckle
2,
*Cload
21, 1, -1.0
*End Step
"""

SPELLINGS = _re_spelled(GOLD, {'column.inp': SPELLING_COLUMN})

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (renumbered nodes, reversed element order)", ALT, ("true",)),
    ("A2 alternative legal (loads by node number, three modes)", ALT2, ("true",)),
    ("A3 alternative legal (trailing commas before keyword lines)", ALT3, ("true",)),
    ("A4 alternative legal (every spelling at once)", SPELLINGS, ('true',)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 density omitted", _run(env="DEFECT=no_density"), ("false",)),
    ("N3 step order wrong (static step first)", _run(env="DEFECT=order_static_first"), ("false",)),
    ("N4 step 3 without the unit load (reset to zero)",
     _run(env="DEFECT=drop_load_step3"), ("false",)),
    ("N5 tensile instead of compressive unit load", _run(env="DEFECT=tensile"), ("false",)),
    ("N6 unit load applied at MID", _run(env="DEFECT=load_mid"), ("false",)),
    ("N7 section sizes swapped (12 x 24)", _run(env="DEFECT=swap_sizes"), ("false",)),
    ("N8 section 1-direction along z", _run(env="DEFECT=axis_z"), ("false",)),
    ("N9 ROOT clamped in dofs 1-3 only", _run(env="DEFECT=clamp_123"), ("false",)),
    ("N10 ten elements instead of 20", _run(env="DEFECT=ten_elements"), ("false",)),
    ("N11 TIP also constrained", _run(env="DEFECT=tip_fixed"), ("false",)),
    ("N12 NLGEOM on the static step", _run(env="DEFECT=nlgeom"), ("false",)),
    ("N13 skipped steps (deck with two steps)", _run(env="DEFECT=two_steps"), ("false",)),
    ("N14 step 3 is a frequency step, not a buckle step",
     _run(env="DEFECT=freq_step3"), ("false",)),
    ("N15 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N16 f1 and f2 swapped in the summary", SWAP_F12, ("false",)),
    ("N17 tampered .dat (one value edited)", TAMPER_DAT, ("false",)),
    ("N18 zero-byte .inp", ZERO_INP, ("false",)),
    ("N19 malformed summary (four numbers)", BAD_SUMMARY, ("false",)),
    ("N20 metrics only", METRICS_ONLY, ("false",)),
    ("N21 encoded payload (base64 summary)", ENCODE_SUMMARY, ("false",)),
]
