"""Audit cases for cae--cli--calculix--task-0003 (exact_match, L4 chain).

Two load cases in one job; the verifier additionally requires the measured
step-2/step-1 displacement ratio to be exactly 2 (linear response). The negative
cases target the multi-step failure modes: load not changed, load accumulated,
summary values swapped, second step dropped.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
import re, subprocess
from pathlib import Path

n = 10
lines = ["*Heading", "VeriCAx task-0003 two load cases", "*Node"]
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
    "*Boundary", "1, 1, 6, 0.0",
    "*Step, name=Step-1", "*Static", "*Cload", "11, 2, -100.0",
    "*Node Print, NSET=All_Nodes", "U", "*End Step",
    "*Step, name=Step-2", "*Static", "*Cload, OP=NEW", "11, 2, -200.0",
    "*Node Print, NSET=All_Nodes", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
subprocess.run(["/usr/bin/ccx", "solution"], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

dat = Path("solution.dat").read_text(errors="ignore")
maps, current = [], None
for raw in dat.splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        if "displacements" in s.lower():
            current = {}
            maps.append(current)
        else:
            current = None
        continue
    if current is not None:
        p = s.split()
        try:
            current[int(p[0])] = float(p[2])
        except (ValueError, IndexError):
            pass
assert len(maps) >= 2 and 11 in maps[0] and 11 in maps[1], "parse failed"
Path("summary.txt").write_text(f"{maps[0][11]}, {maps[1][11]}\n")
PYEOF
"""

# Legal alternative: step cards written with the load line first, extra output
# requests, different set/section names, and *Node File alongside *Node Print.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
import re, subprocess
from pathlib import Path

n = 10
lines = ["*Heading", "alternative encoding", "*Node"]
for i in range(n + 1, 0, -1):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Thin")
for e in range(10, 5, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines.append("*Element, type=B31, elset=Thick")
for e in range(5, 0, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [
    "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
    "*Beam Section, elset=Thin, material=Steel, section=RECT", "6.0, 6.0",
    "*Beam Section, elset=Thick, material=Steel, section=RECT", "10.0, 10.0",
    "*Nset, nset=Nall1", ", ".join(str(i) for i in range(1, n + 2)),
    "*Boundary", "1, 1, 6",
    "*Step, name=A", "*Static", "*Cload", "11, 2, -100",
    "*Node File", "U", "*Node Print, NSET=Nall1", "U", "*End Step",
    "*Step, name=B", "*Static", "*Cload, OP=NEW", "11, 2, -200",
    "*Node Print, NSET=Nall1", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
subprocess.run(["/usr/bin/ccx", "solution"], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
dat = Path("solution.dat").read_text(errors="ignore")
maps, current = [], None
for raw in dat.splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        if "displacements" in s.lower():
            current = {}
            maps.append(current)
        else:
            current = None
        continue
    if current is not None:
        p = s.split()
        try:
            current[int(p[0])] = float(p[2])
        except (ValueError, IndexError):
            pass
Path("summary.txt").write_text(f"{maps[0][11]}, {maps[1][11]}\n")
PYEOF
"""


def _variant(step2_load: str, label: str) -> str:
    """Rebuild the gold deck with a different step-2 load."""
    return GOLD.replace('"*Step, name=Step-2", "*Static", "*Cload, OP=NEW", "11, 2, -200.0"',
                        f'"*Step, name=Step-2", "*Static", "*Cload, OP=NEW", "11, 2, {step2_load}"')


SAME_LOAD = _variant("-100.0", "same load")
ACCUMULATED = _variant("-300.0", "accumulated load")

SWAP = r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/summary.txt")
a, b = [x.strip() for x in p.read_text().strip().split(",")]
p.write_text(f"{b}, {a}\n")
PYEOF
"""

ONE_STEP = r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/solution.inp")
text = p.read_text()
cut = text.index("*Step, name=Step-2")
p.write_text(text[:cut])
PYEOF
"""


# Second legal alternative: one *Element block with separate *Elset cards,
# ascending node order, its own print-set name and float load values.
ALT2 = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
import re, subprocess
from pathlib import Path

n = 10
lines = ["*Heading", "alternative encoding (elset cards)", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [
    "*Elset, elset=Thick", ", ".join(str(e) for e in range(1, 6)),
    "*Elset, elset=Thin", ", ".join(str(e) for e in range(6, 11)),
    "*Nset, nset=PrintAll", ", ".join(str(i) for i in range(1, n + 2)),
    "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
    "*Beam Section, elset=Thick, material=Steel, section=RECT", "10.0, 10.0",
    "*Beam Section, elset=Thin, material=Steel, section=RECT", "6.0, 6.0",
    "*Boundary", "1, 1, 6, 0.0",
    "*Step, name=Load-1", "*Static", "*Cload", "11, 2, -100.0",
    "*Node Print, NSET=PrintAll", "U", "*End Step",
    "*Step, name=Load-2", "*Static", "*Cload, OP=NEW", "11, 2, -200.0",
    "*Node Print, NSET=PrintAll", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
subprocess.run(["/usr/bin/ccx", "solution"], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
dat = Path("solution.dat").read_text(errors="ignore")
maps, current = [], None
for raw in dat.splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        if "displacements" in s.lower():
            current = {}
            maps.append(current)
        else:
            current = None
        continue
    if current is not None:
        p = s.split()
        try:
            current[int(p[0])] = float(p[2])
        except (ValueError, IndexError):
            pass
assert len(maps) >= 2 and 11 in maps[0] and 11 in maps[1], "parse failed"
Path("summary.txt").write_text(f"{maps[0][11]}, {maps[1][11]}\n")
PYEOF
"""

# Only the metrics, no artifacts (kind: metrics_only).
METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.3464, -0.6928' > summary.txt
"""

# Required artifact replaced by an encoded payload (kind: encoded_payload).
ENCODE_SUMMARY = r"""
python3 - <<'PYEOF'
import base64
from pathlib import Path
Path("/home/user/Desktop/summary.txt").write_text(
    base64.b64encode(b"-0.3464, -0.6928").decode() + "\n")
PYEOF
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N2 step-2 load unchanged": "tampered_input",
    "N3 load accumulated to -300 N": "tampered_input",
    "N4 summary values swapped": "fabricated_field",
    "N5 second step dropped": "skipped_steps",
    "N6 metrics only": "metrics_only",
    "N7 encoded payload": "encoded_payload",
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
VeriCAx task-0003 two load cases
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
*Nset, nset=VCAX_L2
11
*Step, name=Step-1
*Static
*Cload
VCAX_L1, 2, -100.0
*Node Print, NSET=All_Nodes
U,
*End Step
*Step, name=Step-2
*Static
*Cload, OP=NEW
VCAX_L2, 2, -200.0
*Node Print, NSET=All_Nodes
U,
*End Step
"""

SPELLINGS = _re_spelled(GOLD, {'solution.inp': SPELLING_SOLUTION})

CASES = [
    ("P1 positive (gold, two steps)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal encoding", ALT, ("true",)),
    ("A2 alternative legal encoding (elset cards)", ALT2, ("true",)),
    ("A3 alternative legal (every spelling at once)", SPELLINGS, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 step-2 load unchanged", SAME_LOAD, ("false",)),
    ("N3 load accumulated to -300 N", ACCUMULATED, ("false",)),
    ("N4 summary values swapped", GOLD + SWAP, ("false",)),
    ("N5 second step dropped", GOLD + ONE_STEP, ("false",)),
    ("N6 metrics only", METRICS_ONLY, ("false",)),
    ("N7 encoded payload", GOLD + ENCODE_SUMMARY, ("false",)),
]
