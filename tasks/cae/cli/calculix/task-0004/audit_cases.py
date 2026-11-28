"""Audit cases for cae--cli--calculix--task-0004 (exact_match, L1-L3).

The first case is the ground-truth source. Plane-strain thick cylinder
(ri=10, ro=20) under 50 MPa internal pressure; the reported quantities are the
radial displacements of the inner and outer surfaces.
"""

BASE = r"""
set -e
cd /home/user/Desktop
export NRAD=__NRAD__
export RI=__RI__
export REVERSE=__REVERSE__
export ELSETS=__ELSETS__
python3 - <<'PYEOF'
import os
from pathlib import Path

nrad = int(os.environ["NRAD"])
ri = float(os.environ["RI"])
ro = 20.0
reverse = os.environ["REVERSE"] == "1"
elset_cards = os.environ["ELSETS"] == "1"
dz = 1.0
dr = (ro - ri) / nrad


def wrap(ids, per=16):
    ids = list(ids)
    return "\n".join(", ".join(str(v) for v in ids[i:i + per])
                     for i in range(0, len(ids), per))


def nid(i, j):
    return (i * 2 + j + 1) if not reverse else ((nrad - i) * 2 + j + 1)


lines = ["*Heading", "VeriCAX task-0004 reference solution", "*Node"]
for i in range(nrad + 1):
    r = ri + dr * i
    for j in range(2):
        lines.append(f"{nid(i,j)}, {r:.6f}, {dz*j:.6f}, 0.0")

if elset_cards:
    lines.append("*Element, type=CAX4")
    for i in range(nrad):
        e = i + 1
        lines.append(f"{e}, {nid(i,0)}, {nid(i+1,0)}, {nid(i+1,1)}, {nid(i,1)}")
    lines += ["*Elset, elset=Eall", wrap(range(1, nrad + 1)),
              "*Elset, elset=Inner", "1"]
    sec_elset = "Eall"
    load_elset = "Inner"
else:
    lines.append("*Element, type=CAX4, elset=Eall")
    for i in range(nrad):
        e = i + 1
        lines.append(f"{e}, {nid(i,0)}, {nid(i+1,0)}, {nid(i+1,1)}, {nid(i,1)}")
    lines.append("*Elset, elset=Inner")
    lines.append("1")
    sec_elset = "Eall"
    load_elset = "Inner"

all_nodes = [nid(i, j) for i in range(nrad + 1) for j in range(2)]
inner_nodes = [nid(0, j) for j in range(2)]
outer_nodes = [nid(nrad, j) for j in range(2)]
lines += ["*Nset, nset=AxialFix", wrap(all_nodes),
          "*Nset, nset=InnerNodes", wrap(inner_nodes),
          "*Nset, nset=OuterNodes", wrap(outer_nodes),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          f"*Solid Section, elset={sec_elset}, material=Steel",
          "*Boundary", "AxialFix, 2, 2, 0.0",
          "*Step", "*Static", "*Dload",
          f"{load_elset}, P4, 50.0",
          "*Node Print, NSET=InnerNodes", "U",
          "*Node Print, NSET=OuterNodes", "U",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import os
from pathlib import Path
import re

nrad = int(os.environ["NRAD"])
reverse = os.environ["REVERSE"] == "1"
inner_id = (nrad * 2 + 1) if reverse else 1
outer_id = 1 if reverse else (nrad * 2 + 1)

dat = Path("solution.dat").read_text(errors="ignore")
u, head = {}, None
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
            u[int(p[0])] = float(p[1])
        except (ValueError, IndexError):
            pass
assert inner_id in u and outer_id in u, "parse failed"
Path("summary.txt").write_text(f"{u[inner_id]}, {u[outer_id]}\n")
PYEOF
"""


def make(nrad=20, ri=10.0, reverse=0, elsets=0) -> str:
    return (BASE.replace("__NRAD__", str(nrad))
                .replace("__RI__", repr(ri))
                .replace("__REVERSE__", str(reverse))
                .replace("__ELSETS__", str(elsets)))


GOLD = make()
# Legal alternative: reversed node ids, separate elset cards, no BC value.
ALT = make(reverse=1, elsets=1)
# Legal alternative: same mesh, pressure applied through an explicit elset card
# and the integer load form; node ids unchanged (different element order).
ALT2 = make(elsets=1)

# Wrong pressure (keeps the gold summary -> A vs B mismatch).
WRONG_PRESSURE = GOLD + r"""
sed -i 's/Inner, P4, 50.0/Inner, P4, 40.0/' /home/user/Desktop/solution.inp
"""

# Pressure applied to the outer surface instead of the inner one.
OUTER_PRESSURE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/solution.inp")
p.write_text(p.read_text().replace("Inner, P4, 50.0", "Eall, P4, 50.0"))
PYEOF
"""

# Wrong material (L2 must reject).
WRONG_MATERIAL = GOLD + r"""
sed -i 's/210000.0, 0.3/70000.0, 0.3/' /home/user/Desktop/solution.inp
"""

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in Path("/home/user/Desktop/summary.txt").read_text().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(f"{v[0] * 1.10}, {v[1] * 1.10}\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

COARSE = make(nrad=10)

WRONG_RADIUS = make(ri=8.0)

# Only the metrics, no deck or solver output (kind: metrics_only).
METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '0.00454, 0.00293' > summary.txt
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
    "N2 pressure tampered": "tampered_input",
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
VeriCAX task-0004 reference solution
*Node, NSET=VCAX_ALLNODES
1, 10.000000, 0.000000
2, 10.000000, 1.000000
3, 10.500000, 0.000000
4, 10.500000, 1.000000
5, 11.000000, 0.000000
6, 11.000000, 1.000000
7, 11.500000, 0.000000
8, 11.500000, 1.000000
9, 12.000000, 0.000000
10, 12.000000, 1.000000
11, 12.500000, 0.000000
12, 12.500000, 1.000000
13, 13.000000, 0.000000
14, 13.000000, 1.000000
15, 13.500000, 0.000000
16, 13.500000, 1.000000
17, 14.000000, 0.000000
18, 14.000000, 1.000000
19, 14.500000, 0.000000
20, 14.500000, 1.000000
21, 15.000000, 0.000000
22, 15.000000, 1.000000
23, 15.500000, 0.000000
24, 15.500000, 1.000000
25, 16.000000, 0.000000
26, 16.000000, 1.000000
27, 16.500000, 0.000000
28, 16.500000, 1.000000
29, 17.000000, 0.000000
30, 17.000000, 1.000000
31, 17.500000, 0.000000
32, 17.500000, 1.000000
33, 18.000000, 0.000000
34, 18.000000, 1.000000
35, 18.500000, 0.000000
36, 18.500000, 1.000000
37, 19.000000, 0.000000
38, 19.000000, 1.000000
39, 19.500000, 0.000000
40, 19.500000, 1.000000
41, 20.000000, 0.000000
42, 20.000000, 1.000000
*Element, type=CAX4, elset=Eall
1, 1, 3, 4, 2
2, 3, 5, 6, 4
3, 5, 7, 8, 6
4, 7, 9, 10, 8
5, 9, 11, 12, 10
6, 11, 13, 14, 12
7, 13, 15, 16, 14
8, 15, 17, 18, 16
9, 17, 19, 20, 18
10, 19, 21, 22, 20
11, 21, 23, 24, 22
12, 23, 25, 26, 24
13, 25, 27, 28, 26
14, 27, 29, 30, 28
15, 29, 31, 32, 30
16, 31, 33, 34, 32
17, 33, 35, 36, 34
18, 35, 37, 38, 36
19, 37, 39, 40, 38
20, 39, 41, 42, 40,
*Elset, elset=Inner
1,
*Nset, nset=AxialFix, GENERATE
1, 42, 1,
*Nset, nset=InnerNodes, GENERATE
1, 2, 1,
*Nset, nset=OuterNodes, GENERATE
41, 42, 1,
*Material, name=Steel
*Elastic
210000.0, 0.3,
*Solid Section, elset=Eall, material=Steel
*Boundary
AxialFix, 2
** node sets named by the *Boundary rows
** sets of one member, named by the load rows
*Step
*Static
*Dload
1, P4, 50.0
*Node Print, NSET=InnerNodes
U,
*Node Print, NSET=OuterNodes
U,
*End Step
"""

SPELLINGS = _re_spelled(GOLD, {'solution.inp': SPELLING_SOLUTION})

SPELLING_DSLOAD = r"""*Heading
VeriCAX task-0004 reference solution
*Node, NSET=VCAX_ALLNODES
1, 10.000000, 0.000000
2, 10.000000, 1.000000
3, 10.500000, 0.000000
4, 10.500000, 1.000000
5, 11.000000, 0.000000
6, 11.000000, 1.000000
7, 11.500000, 0.000000
8, 11.500000, 1.000000
9, 12.000000, 0.000000
10, 12.000000, 1.000000
11, 12.500000, 0.000000
12, 12.500000, 1.000000
13, 13.000000, 0.000000
14, 13.000000, 1.000000
15, 13.500000, 0.000000
16, 13.500000, 1.000000
17, 14.000000, 0.000000
18, 14.000000, 1.000000
19, 14.500000, 0.000000
20, 14.500000, 1.000000
21, 15.000000, 0.000000
22, 15.000000, 1.000000
23, 15.500000, 0.000000
24, 15.500000, 1.000000
25, 16.000000, 0.000000
26, 16.000000, 1.000000
27, 16.500000, 0.000000
28, 16.500000, 1.000000
29, 17.000000, 0.000000
30, 17.000000, 1.000000
31, 17.500000, 0.000000
32, 17.500000, 1.000000
33, 18.000000, 0.000000
34, 18.000000, 1.000000
35, 18.500000, 0.000000
36, 18.500000, 1.000000
37, 19.000000, 0.000000
38, 19.000000, 1.000000
39, 19.500000, 0.000000
40, 19.500000, 1.000000
41, 20.000000, 0.000000
42, 20.000000, 1.000000
*Element, type=CAX4, elset=Eall
1, 1, 3, 4, 2
2, 3, 5, 6, 4
3, 5, 7, 8, 6
4, 7, 9, 10, 8
5, 9, 11, 12, 10
6, 11, 13, 14, 12
7, 13, 15, 16, 14
8, 15, 17, 18, 16
9, 17, 19, 20, 18
10, 19, 21, 22, 20
11, 21, 23, 24, 22
12, 23, 25, 26, 24
13, 25, 27, 28, 26
14, 27, 29, 30, 28
15, 29, 31, 32, 30
16, 31, 33, 34, 32
17, 33, 35, 36, 34
18, 35, 37, 38, 36
19, 37, 39, 40, 38
20, 39, 41, 42, 40,
*Nset, nset=AxialFix, GENERATE
1, 42, 1,
*Nset, nset=InnerNodes, GENERATE
1, 2, 1,
*Nset, nset=OuterNodes, GENERATE
41, 42, 1,
*Material, name=Steel
*Elastic
210000.0, 0.3,
*Solid Section, elset=Eall, material=Steel
*Boundary
AxialFix, 2
** node sets named by the *Boundary rows
** sets of one member, named by the load rows
*Step
*Static
*DSLOAD
1, P4, 50.0
*Node Print, NSET=InnerNodes
U,
*Node Print, NSET=OuterNodes
U,
*End Step
"""

DSLOAD_CASE = _re_spelled(GOLD, {"solution.inp": SPELLING_DSLOAD})

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (reversed ids, elset cards)", ALT, ("true",)),
    ("A2 alternative legal (explicit elset cards)", ALT2, ("true",)),
    ("A3 alternative legal (every spelling at once)", SPELLINGS, ("true",)),
    ("A4 alternative legal (*DSLOAD and the element number for the pressure)", DSLOAD_CASE, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 pressure tampered", WRONG_PRESSURE, ("false",)),
    ("N3 pressure on outer surface", OUTER_PRESSURE, ("false",)),
    ("N4 wrong material", WRONG_MATERIAL, ("false",)),
    ("N5 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N6 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N7 metrics only", METRICS_ONLY, ("false",)),
    ("N8 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N9 coarse mesh (10 elements)", COARSE, ("false",)),
    ("N10 wrong inner radius", WRONG_RADIUS, ("false",)),
]