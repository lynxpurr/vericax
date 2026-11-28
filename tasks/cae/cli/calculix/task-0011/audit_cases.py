"""Audit cases for cae--cli--calculix--task-0011 (drawing reconstruction).

The first case is the ground-truth source. The drawing dimensions are
120 / 70 / 12 / 8 / 80 N. The verifier checks the reconstructed stepped beam
and re-solves it.
"""

BASE = r"""
set -e
cd /home/user/Desktop
export N=__N__
export LEN=__LEN__
export ROOT=__ROOT__
export TIP=__TIP__
export LOAD=__LOAD__
export REVERSE=__REVERSE__
export ELSETS=__ELSETS__
python3 - <<'PYEOF'
import os
from pathlib import Path

n = int(os.environ["N"])
length = float(os.environ["LEN"])
root = float(os.environ["ROOT"])
tip = float(os.environ["TIP"])
load = float(os.environ["LOAD"])
reverse = os.environ["REVERSE"] == "1"
elset_cards = os.environ["ELSETS"] == "1"
split_elem = 7 if n == 12 else n // 2

lines = ["*Heading", "VeriCAX task-0011 reconstructed stepped beam", "*Node"]
order = range(n + 1, 0, -1) if reverse else range(1, n + 2)
for i in order:
    x = length * (i - 1) / n
    lines.append(f"{i}, {x:.6f}, 0.0, 0.0")

if elset_cards:
    lines.append("*Element, type=B31")
    for e in range(1, n + 1):
        lines.append(f"{e}, {e}, {e + 1}")
    lines += ["*Elset, elset=RootElems", ", ".join(str(e) for e in range(1, split_elem + 1)),
              "*Elset, elset=TipElems", ", ".join(str(e) for e in range(split_elem + 1, n + 1))]
else:
    if reverse:
        lines.append("*Element, type=B31, elset=TipElems")
        for e in range(n, split_elem, -1):
            lines.append(f"{e}, {e}, {e + 1}")
        lines.append("*Element, type=B31, elset=RootElems")
        for e in range(split_elem, 0, -1):
            lines.append(f"{e}, {e}, {e + 1}")
    else:
        lines.append("*Element, type=B31, elset=RootElems")
        for e in range(1, split_elem + 1):
            lines.append(f"{e}, {e}, {e + 1}")
        lines.append("*Element, type=B31, elset=TipElems")
        for e in range(split_elem + 1, n + 1):
            lines.append(f"{e}, {e}, {e + 1}")

lines += ["*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=RootElems, material=Steel, section=RECT", f"{root!r}, {root!r}",
          "*Beam Section, elset=TipElems, material=Steel, section=RECT", f"{tip!r}, {tip!r}",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Static", "*Cload", f"{n + 1}, 2, {load!r}",
          "*Node Print, NSET=All_Nodes", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import os, re
from pathlib import Path
n = int(os.environ["N"])
dat = Path("solution.dat").read_text(errors="ignore")
uy, head = {}, None
for raw in dat.splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        head = s.lower()
        continue
    if head and "displacements" in head:
        p = s.split()
        try:
            uy[int(p[0])] = float(p[2])
        except (ValueError, IndexError):
            pass
assert n + 1 in uy, "parse failed"
Path("summary.txt").write_text(f"{uy[n + 1]}\n")
PYEOF
"""


def make(n=12, length=120.0, root=12.0, tip=8.0, load=-80.0, reverse=0, elsets=0) -> str:
    return (BASE.replace("__N__", str(n))
                .replace("__LEN__", repr(length))
                .replace("__ROOT__", repr(root))
                .replace("__TIP__", repr(tip))
                .replace("__LOAD__", repr(load))
                .replace("__REVERSE__", str(reverse))
                .replace("__ELSETS__", str(elsets)))


GOLD = make()
ALT = make(reverse=1, elsets=1)
ALT2 = make(elsets=1)
WRONG_LENGTH = make(n=10, length=100.0)
WRONG_ROOT = make(root=10.0)
WRONG_TIP = make(tip=10.0)
WRONG_LOAD = make(load=-100.0)
COARSE = make(n=6, length=120.0)

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = float(Path("/home/user/Desktop/summary.txt").read_text())
Path("/home/user/Desktop/summary.txt").write_text(f"{v * 1.10!r}\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.164' > summary.txt
"""

ENCODE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
import base64
from pathlib import Path
raw = Path("/home/user/Desktop/summary.txt").read_text().strip().encode()
Path("/home/user/Desktop/summary.txt").write_text(base64.b64encode(raw).decode() + "\n")
PYEOF
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N2 tip load tampered": "tampered_input",
    "N5 fabricated summary (+10%)": "fabricated_field",
    "N6 zero-byte solver output": "skipped_steps",
    "N7 metrics only": "metrics_only",
    "N8 encoded payload": "encoded_payload",
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

SPELLING_SOLUTION = r"""*Heading
VeriCAX task-0011 reconstructed stepped beam
*Node, NSET=VCAX_ALLNODES
1, 0.000000, 0.0
2, 10.000000, 0.0
3, 20.000000, 0.0
4, 30.000000, 0.0
5, 40.000000, 0.0
6, 50.000000, 0.0
7, 60.000000, 0.0
8, 70.000000, 0.0
9, 80.000000, 0.0
10, 90.000000, 0.0
11, 100.000000, 0.0
12, 110.000000, 0.0
13, 120.000000, 0.0
*Element, type=B31, elset=RootElems
1, 1, 2
2, 2, 3
3, 3, 4
4, 4, 5
5, 5, 6
6, 6, 7
7, 7, 8,
*Element, type=B31, elset=TipElems
8, 8, 9
9, 9, 10
10, 10, 11
11, 11, 12
12, 12, 13,
*Nset, nset=All_Nodes, GENERATE
1, 13, 1,
*Material, name=Steel
*Elastic
210000.0, 0.3,
*Beam Section, elset=RootElems, material=Steel, section=RECT
12.0, 12.0,
*Beam Section, elset=TipElems, material=Steel, section=RECT
8.0, 8.0,
*Boundary
VCAX_B1, 1, 6
** node sets named by the *Boundary rows
*Nset, nset=VCAX_B1
1,
** sets of one member, named by the load rows
*Nset, nset=VCAX_L1
13
*Step
*Static
*Cload
VCAX_L1, 2, -80.0
*Node Print, NSET=All_Nodes
U,
*End Step
"""

SPELLINGS = _re_spelled(GOLD, {'solution.inp': SPELLING_SOLUTION})

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (reversed ids, elset cards)", ALT, ("true",)),
    ("A2 alternative legal (elset cards)", ALT2, ("true",)),
    ("A3 alternative legal (every spelling at once)", SPELLINGS, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 tip load tampered", WRONG_LOAD, ("false",)),
    ("N3 wrong length", WRONG_LENGTH, ("false",)),
    ("N4 wrong root section", WRONG_ROOT, ("false",)),
    ("N5 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N6 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N7 metrics only", METRICS_ONLY, ("false",)),
    ("N8 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N9 wrong tip section", WRONG_TIP, ("false",)),
    ("N10 coarse mesh", COARSE, ("false",)),
]