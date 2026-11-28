"""Audit cases for cae--cli--calculix--task-0001 (exact_match).

Each entry is (label, bash script, expectation). The harness runs the first
script as the ground-truth source, so keep GOLD canonical.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path
n = 10
lines = ["*Heading", "VeriCAx task-0001 reference solution", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=RootElems")
for e in range(1, 6):
    lines.append(f"{e}, {e}, {e + 1}")
lines.append("*Element, type=B31, elset=TipElems")
for e in range(6, 11):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [
    "*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
    "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
    "*Beam Section, elset=RootElems, material=Steel, section=RECT", "10.0, 10.0",
    "*Beam Section, elset=TipElems, material=Steel, section=RECT", "6.0, 6.0",
    "*Boundary", "1, 1, 6, 0.0", "*Step", "*Static", "*Cload", f"{n + 1}, 2, -100.0",
    "*Node Print, NSET=All_Nodes", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path
import re
dat = Path("solution.dat").read_text(errors="ignore")
uy = {}
head = None
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
assert 6 in uy and 11 in uy, "parse failed"
Path("summary.txt").write_text(f"{uy[6]}, {uy[11]}\n")
PYEOF
"""

# Legal alternative: nodes descending, elements tip-first in two cards,
# sections in the opposite order, BC without value, integer load, own set name.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path
n = 10
lines = ["*Heading", "alternative legal deck", "*Node"]
for i in range(n + 1, 0, -1):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=TipElems")
for e in range(10, 5, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines.append("*Element, type=B31, elset=RootElems")
for e in range(5, 0, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [
    "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
    "*Beam Section, elset=TipElems, material=Steel, section=RECT", "6.0, 6.0",
    "*Beam Section, elset=RootElems, material=Steel, section=RECT", "10.0, 10.0",
    "*Nset, nset=PrintNodes", ", ".join(str(i) for i in range(1, n + 2)),
    "*Boundary", "1, 1, 6", "*Step", "*Static", "*Cload", "11, 2, -100",
    "*Node Print, NSET=PrintNodes", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt.log 2>&1 || { tail -25 /tmp/ccx-alt.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path
import re
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
Path("summary.txt").write_text(f"{uy[6]}, {uy[11]}\n")
PYEOF
"""

FABRICATE = "\nprintf '%s\\n' '-0.01, -0.10' > /home/user/Desktop/summary.txt\n"
ZERO_DAT = "\n: > /home/user/Desktop/solution.dat\n"
TAMPER = r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/solution.inp")
p.write_text(p.read_text().replace(
    "*Beam Section, elset=TipElems, material=Steel, section=RECT\n6.0, 6.0",
    "*Beam Section, elset=TipElems, material=Steel, section=RECT\n10.0, 10.0"))
PYEOF
"""

# Second legal alternative: separate *Elset cards instead of ELSET= on the
# *Element cards, ascending node order, its own print set name.
ALT2 = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path
n = 10
lines = ["*Heading", "alternative legal deck (elset cards)", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [
    "*Elset, elset=Root",
    ", ".join(str(e) for e in range(1, 6)),
    "*Elset, elset=Tip",
    ", ".join(str(e) for e in range(6, 11)),
    "*Nset, nset=PrintAll", ", ".join(str(i) for i in range(1, n + 2)),
    "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
    "*Beam Section, elset=Root, material=Steel, section=RECT", "10.0, 10.0",
    "*Beam Section, elset=Tip, material=Steel, section=RECT", "6.0, 6.0",
    "*Boundary", "1, 1, 6, 0.0", "*Step", "*Static", "*Cload", "11, 2, -100",
    "*Node Print, NSET=PrintAll", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt2.log 2>&1 || { tail -25 /tmp/ccx-alt2.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path
import re
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
Path("summary.txt").write_text(f"{uy[6]}, {uy[11]}\n")
PYEOF
"""

# Only the metrics, no artifacts (negative group kind: metrics_only).
METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.0598, -0.3464' > summary.txt
"""

# Required artifact replaced by an encoded payload (kind: encoded_payload).
ENCODED_PAYLOAD = r"""
python3 - <<'PYEOF'
import base64
from pathlib import Path
Path("/home/user/Desktop/summary.txt").write_text(
    base64.b64encode(b"-0.0598, -0.3464").decode() + "\n")
PYEOF
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N2 fabricated summary": "fabricated_field",
    "N3 zero-byte solver output": "skipped_steps",
    "N4 tampered sections": "tampered_input",
    "N5 metrics only": "metrics_only",
    "N6 encoded payload": "encoded_payload",
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
VeriCAx task-0001 reference solution
*Node, NSET=VCAX_ALLNODES
1, 0.0, 0.0
2, 10.0, 0.0
3, 20.0, 0.0
4, 30.0, 0.0
5, 40.0, 0.0
6, 50.0, 0.0
7, 60.0, 0.0
8, 70.0, 0.0
9, 80.0, 0.0
10, 90.0, 0.0
11, 100.0, 0.0
*Element, type=B31, elset=RootElems
1, 1, 2
2, 2, 3
3, 3, 4
4, 4, 5
5, 5, 6,
*Element, type=B31, elset=TipElems
6, 6, 7
7, 7, 8
8, 8, 9
9, 9, 10
10, 10, 11,
*Nset, nset=All_Nodes, GENERATE
1, 11, 1,
*Material, name=Steel
*Elastic
210000.0, 0.3,
*Beam Section, elset=RootElems, material=Steel, section=RECT
10.0, 10.0,
*Beam Section, elset=TipElems, material=Steel, section=RECT
6.0, 6.0,
*Boundary
VCAX_B1, 1, 6
** node sets named by the *Boundary rows
*Nset, nset=VCAX_B1
1,
** sets of one member, named by the load rows
*Nset, nset=VCAX_L1
11
*Step
*Static
*Cload
VCAX_L1, 2, -100.0
*Node Print, NSET=All_Nodes
U,
*End Step
"""

SPELLINGS = _re_spelled(GOLD, {'solution.inp': SPELLING_SOLUTION})

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal deck", ALT, ("true",)),
    ("A2 alternative legal deck (elset cards)", ALT2, ("true",)),
    ("A3 alternative legal (every spelling at once)", SPELLINGS, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 fabricated summary", GOLD + FABRICATE, ("false",)),
    ("N3 zero-byte solver output", GOLD + ZERO_DAT, ("false",)),
    ("N4 tampered sections", GOLD + TAMPER, ("false",)),
    ("N5 metrics only", METRICS_ONLY, ("false",)),
    ("N6 encoded payload", GOLD + ENCODED_PAYLOAD, ("false",)),
]
