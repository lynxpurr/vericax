"""Audit cases for cae--cli--cross-solver--task-0005 (software-selection).

Required tool: CalculiX (*FREQUENCY modal analysis of a clamped CPS4 plate).
The submitted native pair (.inp + .dat) must be ccx's output for THIS deck:
the verifier re-runs *FREQUENCY and compares the eigenvalue table and the
printed mode-1 shape node by node. dolfinx cannot deliver this native family
(its checkpoints are XDMF/HDF5), so a foreign or fabricated native result is
rejected.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

TOKEN = "VCAX_AUDIT_0005"
def _wrap(ids):
    return chr(10).join(", ".join(str(i) for i in ids[k:k + 16])
                        for k in range(0, len(ids), 16))

g = 10
npe = g + 1
lines = ["*Heading", "VeriCAX cross-solver task-0005 (modal)", "*Node"]
for nid in range(1, npe ** 2 + 1):
    gx = (nid - 1) % npe
    gy = (nid - 1) // npe
    lines.append(f"{nid}, {10.0 * gx:.1f}, {10.0 * gy:.1f}, 0.0")
lines.append("*Element, type=CPS4, elset=Eall")
for gy in range(g):
    for gx in range(g):
        n1 = gy * npe + gx + 1
        n2 = n1 + 1
        n3 = n1 + npe
        n4 = n3 + 1
        lines.append(f"{g * gy + gx + 1}, {n1}, {n2}, {n4}, {n3}")
clamped = ", ".join(str(r * npe + 1) for r in range(npe))
lines += [f"*Nset, nset={TOKEN}", _wrap(range(1, npe ** 2 + 1)),
          "*Nset, nset=Clamped", clamped,
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Density", "7.85e-9",
          "*Solid Section, elset=Eall, material=Steel", "1.0",
          "*Boundary", "Clamped, 1, 2, 0.0",
          "*Step", "*Frequency", "4,", f"*Node Print, NSET={TOKEN}", "U",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import math
import re
from pathlib import Path

compact = lambda s: re.sub(r"\s+", "", s).upper()
state, lam1 = 0, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    c = compact(s)
    if re.match(r"^[A-Za-z*]", s):
        if "EIGENVALUEOUTPUT" in c:
            state = 1
        continue
    if state == 1:
        pp = s.split()
        if len(pp) >= 2:
            try:
                m = int(pp[0]); v = float(pp[1])
            except ValueError:
                continue
            if m == 1:
                lam1 = v
                break
assert lam1, "no eigenvalue table found"
f1 = math.sqrt(lam1) / (2.0 * math.pi)
Path("summary.txt").write_text(f"{f1!r}\n")
PYEOF
"""

# Legal alternative: two separate elset cards, boundary by explicit node
# lines, six eigenvalues, scientific thickness literal.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

TOKEN = "VCAX_AUDIT_0005"
def _wrap(ids):
    return chr(10).join(", ".join(str(i) for i in ids[k:k + 16])
                        for k in range(0, len(ids), 16))

g = 10
npe = g + 1
lines = ["*Heading", "alternative legal modal deck", "*Node"]
for nid in range(1, npe ** 2 + 1):
    gx = (nid - 1) % npe
    gy = (nid - 1) // npe
    lines.append(f"{nid}, {10.0 * gx:.1f}, {10.0 * gy:.1f}, 0.0")
lines.append("*Element, type=CPS4")
for gy in range(g):
    for gx in range(g):
        n1 = gy * npe + gx + 1
        n2 = n1 + 1
        n3 = n1 + npe
        n4 = n3 + 1
        lines.append(f"{g * gy + gx + 1}, {n1}, {n2}, {n4}, {n3}")
rows = ", ".join(str(r * npe + 1) for r in range(npe))
lines += ["*Elset, elset=AllElems", _wrap(range(1, g ** 2 + 1)),
          f"*Nset, nset={TOKEN}", _wrap(range(1, npe ** 2 + 1)),
          "*Nset, nset=Clamped", rows,
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Density", "7.85e-9",
          "*Solid Section, elset=AllElems, material=Steel", "1.0e0",
          "*Boundary", "Clamped, 1, 2",
          "*Step", "*Frequency", "6,", f"*Node Print, NSET={TOKEN}", "U",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import math
import re
from pathlib import Path

compact = lambda s: re.sub(r"\s+", "", s).upper()
state, lam1 = 0, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    c = compact(s)
    if re.match(r"^[A-Za-z*]", s):
        if "EIGENVALUEOUTPUT" in c:
            state = 1
        continue
    if state == 1:
        pp = s.split()
        if len(pp) >= 2:
            try:
                m = int(pp[0]); v = float(pp[1])
            except ValueError:
                continue
            if m == 1:
                lam1 = v
                break
assert lam1, "no eigenvalue table found"
f1 = math.sqrt(lam1) / (2.0 * math.pi)
Path("summary.txt").write_text(f"{f1!r}\n")
PYEOF
"""

# Legal alternative 2: scientific-notation load literal and a different
# eigenvalue request; same physics, same token.
ALT2 = ALT.replace("alternative legal modal deck",
                   "alternative legal modal deck (scientific load)")
ALT2 = ALT2.replace('"*Step", "*Buckle", "6,", "*Cload", "11, 1, -1000.0",',
                    '"*Step", "*Buckle", "8,", "*Cload", "11, 1, -1.0e3",')

WRONG_SECTION = GOLD + r"""
sed -i 's/10.0, 10.0/12.0, 10.0/' /home/user/Desktop/solution.inp
"""

WRONG_LOAD = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/solution.inp")
p.write_text(p.read_text().replace("210000.0, 0.3", "190000.0, 0.3"))
PYEOF
"""

FABRICATE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = float(Path("/home/user/Desktop/summary.txt").read_text())
Path("/home/user/Desktop/summary.txt").write_text(f"{v * 1.10!r}\n")
PYEOF
"""

# Non-empty fabricated native result: perturb every eigenmode value by 2%.
FABRICATE_FIELD = GOLD + r"""
python3 - <<'PYEOF'
import re
from pathlib import Path

TOKEN = "VCAX_AUDIT_0005"
lines, inside = [], False
for raw in Path("/home/user/Desktop/solution.dat").read_text().splitlines():
    s = raw.strip()
    if re.match(r"^[A-Za-z*]", s):
        inside = ("displacements" in s.lower() and TOKEN.lower() in s.lower())
        lines.append(raw)
        continue
    if inside and s:
        p = s.split()
        try:
            vals = [float(x) for x in p[1:4]]
            lines.append(f"{p[0]}  {vals[0] * 1.02:.8E}  {vals[1] * 1.02:.8E}  {vals[2] * 1.02:.8E}")
            continue
        except (ValueError, IndexError):
            pass
    lines.append(raw)
Path("/home/user/Desktop/solution.dat").write_text("\n".join(lines) + "\n")
PYEOF
"""

# Replayed / wrong token: the native result no longer carries the challenge set.
WRONG_TOKEN = GOLD + r"""
sed -i 's/VCAX_AUDIT_0005/VCAX_OLD_0005/' /home/user/Desktop/solution.dat
"""

# Foreign native result: an XDMF-style file instead of a CalculiX .dat (the
# dolfinx result family of the merged image).
FOREIGN_RESULT = GOLD + r"""
cat > /home/user/Desktop/solution.dat <<'EOF'
<?xml version="1.0"?>
<Xdmf Version="3.0"><Domain><Grid Name="plate"><Attribute Name="mode_1"/></Grid></Domain></Xdmf>
EOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf 'placeholder\n' > solution.inp
printf 'placeholder\n' > solution.dat
printf '%s\n' '42.6' > summary.txt
"""

ENCODE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
import base64
from pathlib import Path
raw = Path("/home/user/Desktop/summary.txt").read_text().strip().encode()
Path("/home/user/Desktop/summary.txt").write_text(base64.b64encode(raw).decode() + "\n")
PYEOF
"""

COARSE = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

TOKEN = "VCAX_AUDIT_0005"
def _wrap(ids):
    return chr(10).join(", ".join(str(i) for i in ids[k:k + 16])
                        for k in range(0, len(ids), 16))

g = 5
npe = g + 1
lines = ["*Heading", "coarse modal deck", "*Node"]
for nid in range(1, npe ** 2 + 1):
    gx = (nid - 1) % npe
    gy = (nid - 1) // npe
    lines.append(f"{nid}, {10.0 * gx:.1f}, {10.0 * gy:.1f}, 0.0")
lines.append("*Element, type=CPS4, elset=Eall")
for gy in range(g):
    for gx in range(g):
        n1 = gy * npe + gx + 1
        n2 = n1 + 1
        n3 = n1 + npe
        n4 = n3 + 1
        lines.append(f"{g * gy + gx + 1}, {n1}, {n2}, {n4}, {n3}")
rows = ", ".join(str(r * npe + 1) for r in range(npe))
lines += [f"*Nset, nset={TOKEN}", _wrap(range(1, npe ** 2 + 1)),
          "*Nset, nset=Clamped", rows,
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Density", "7.85e-9",
          "*Solid Section, elset=Eall, material=Steel", "1.0",
          "*Boundary", "Clamped, 1, 2, 0.0",
          "*Step", "*Frequency", "4,", f"*Node Print, NSET={TOKEN}", "U",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-coarse.log 2>&1 || { tail -25 /tmp/ccx-coarse.log; exit 1; }
python3 - <<'PYEOF'
import math
import re
from pathlib import Path

compact = lambda s: re.sub(r"\s+", "", s).upper()
state, lam1 = 0, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    c = compact(s)
    if re.match(r"^[A-Za-z*]", s):
        if "EIGENVALUEOUTPUT" in c:
            state = 1
        continue
    if state == 1:
        pp = s.split()
        if len(pp) >= 2:
            try:
                m = int(pp[0]); v = float(pp[1])
            except ValueError:
                continue
            if m == 1:
                lam1 = v
                break
assert lam1, "no eigenvalue table found"
f1 = math.sqrt(lam1) / (2.0 * math.pi)
Path("summary.txt").write_text(f"{f1!r}\n")
PYEOF
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N2 section tampered": "tampered_input",
    "N7 fabricated mode field": "fabricated_field",
    "N8 zero-byte native result": "skipped_steps",
    "N9 metrics only": "metrics_only",
    "N10 encoded summary": "encoded_payload",
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
VeriCAX cross-solver task-0005 (modal)
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
12, 0.0, 10.0
13, 10.0, 10.0
14, 20.0, 10.0
15, 30.0, 10.0
16, 40.0, 10.0
17, 50.0, 10.0
18, 60.0, 10.0
19, 70.0, 10.0
20, 80.0, 10.0
21, 90.0, 10.0
22, 100.0, 10.0
23, 0.0, 20.0
24, 10.0, 20.0
25, 20.0, 20.0
26, 30.0, 20.0
27, 40.0, 20.0
28, 50.0, 20.0
29, 60.0, 20.0
30, 70.0, 20.0
31, 80.0, 20.0
32, 90.0, 20.0
33, 100.0, 20.0
34, 0.0, 30.0
35, 10.0, 30.0
36, 20.0, 30.0
37, 30.0, 30.0
38, 40.0, 30.0
39, 50.0, 30.0
40, 60.0, 30.0
41, 70.0, 30.0
42, 80.0, 30.0
43, 90.0, 30.0
44, 100.0, 30.0
45, 0.0, 40.0
46, 10.0, 40.0
47, 20.0, 40.0
48, 30.0, 40.0
49, 40.0, 40.0
50, 50.0, 40.0
51, 60.0, 40.0
52, 70.0, 40.0
53, 80.0, 40.0
54, 90.0, 40.0
55, 100.0, 40.0
56, 0.0, 50.0
57, 10.0, 50.0
58, 20.0, 50.0
59, 30.0, 50.0
60, 40.0, 50.0
61, 50.0, 50.0
62, 60.0, 50.0
63, 70.0, 50.0
64, 80.0, 50.0
65, 90.0, 50.0
66, 100.0, 50.0
67, 0.0, 60.0
68, 10.0, 60.0
69, 20.0, 60.0
70, 30.0, 60.0
71, 40.0, 60.0
72, 50.0, 60.0
73, 60.0, 60.0
74, 70.0, 60.0
75, 80.0, 60.0
76, 90.0, 60.0
77, 100.0, 60.0
78, 0.0, 70.0
79, 10.0, 70.0
80, 20.0, 70.0
81, 30.0, 70.0
82, 40.0, 70.0
83, 50.0, 70.0
84, 60.0, 70.0
85, 70.0, 70.0
86, 80.0, 70.0
87, 90.0, 70.0
88, 100.0, 70.0
89, 0.0, 80.0
90, 10.0, 80.0
91, 20.0, 80.0
92, 30.0, 80.0
93, 40.0, 80.0
94, 50.0, 80.0
95, 60.0, 80.0
96, 70.0, 80.0
97, 80.0, 80.0
98, 90.0, 80.0
99, 100.0, 80.0
100, 0.0, 90.0
101, 10.0, 90.0
102, 20.0, 90.0
103, 30.0, 90.0
104, 40.0, 90.0
105, 50.0, 90.0
106, 60.0, 90.0
107, 70.0, 90.0
108, 80.0, 90.0
109, 90.0, 90.0
110, 100.0, 90.0
111, 0.0, 100.0
112, 10.0, 100.0
113, 20.0, 100.0
114, 30.0, 100.0
115, 40.0, 100.0
116, 50.0, 100.0
117, 60.0, 100.0
118, 70.0, 100.0
119, 80.0, 100.0
120, 90.0, 100.0
121, 100.0, 100.0
*Element, type=CPS4, elset=Eall
1, 1, 2, 13, 12
2, 2, 3, 14, 13
3, 3, 4, 15, 14
4, 4, 5, 16, 15
5, 5, 6, 17, 16
6, 6, 7, 18, 17
7, 7, 8, 19, 18
8, 8, 9, 20, 19
9, 9, 10, 21, 20
10, 10, 11, 22, 21
11, 12, 13, 24, 23
12, 13, 14, 25, 24
13, 14, 15, 26, 25
14, 15, 16, 27, 26
15, 16, 17, 28, 27
16, 17, 18, 29, 28
17, 18, 19, 30, 29
18, 19, 20, 31, 30
19, 20, 21, 32, 31
20, 21, 22, 33, 32
21, 23, 24, 35, 34
22, 24, 25, 36, 35
23, 25, 26, 37, 36
24, 26, 27, 38, 37
25, 27, 28, 39, 38
26, 28, 29, 40, 39
27, 29, 30, 41, 40
28, 30, 31, 42, 41
29, 31, 32, 43, 42
30, 32, 33, 44, 43
31, 34, 35, 46, 45
32, 35, 36, 47, 46
33, 36, 37, 48, 47
34, 37, 38, 49, 48
35, 38, 39, 50, 49
36, 39, 40, 51, 50
37, 40, 41, 52, 51
38, 41, 42, 53, 52
39, 42, 43, 54, 53
40, 43, 44, 55, 54
41, 45, 46, 57, 56
42, 46, 47, 58, 57
43, 47, 48, 59, 58
44, 48, 49, 60, 59
45, 49, 50, 61, 60
46, 50, 51, 62, 61
47, 51, 52, 63, 62
48, 52, 53, 64, 63
49, 53, 54, 65, 64
50, 54, 55, 66, 65
51, 56, 57, 68, 67
52, 57, 58, 69, 68
53, 58, 59, 70, 69
54, 59, 60, 71, 70
55, 60, 61, 72, 71
56, 61, 62, 73, 72
57, 62, 63, 74, 73
58, 63, 64, 75, 74
59, 64, 65, 76, 75
60, 65, 66, 77, 76
61, 67, 68, 79, 78
62, 68, 69, 80, 79
63, 69, 70, 81, 80
64, 70, 71, 82, 81
65, 71, 72, 83, 82
66, 72, 73, 84, 83
67, 73, 74, 85, 84
68, 74, 75, 86, 85
69, 75, 76, 87, 86
70, 76, 77, 88, 87
71, 78, 79, 90, 89
72, 79, 80, 91, 90
73, 80, 81, 92, 91
74, 81, 82, 93, 92
75, 82, 83, 94, 93
76, 83, 84, 95, 94
77, 84, 85, 96, 95
78, 85, 86, 97, 96
79, 86, 87, 98, 97
80, 87, 88, 99, 98
81, 89, 90, 101, 100
82, 90, 91, 102, 101
83, 91, 92, 103, 102
84, 92, 93, 104, 103
85, 93, 94, 105, 104
86, 94, 95, 106, 105
87, 95, 96, 107, 106
88, 96, 97, 108, 107
89, 97, 98, 109, 108
90, 98, 99, 110, 109
91, 100, 101, 112, 111
92, 101, 102, 113, 112
93, 102, 103, 114, 113
94, 103, 104, 115, 114
95, 104, 105, 116, 115
96, 105, 106, 117, 116
97, 106, 107, 118, 117
98, 107, 108, 119, 118
99, 108, 109, 120, 119
100, 109, 110, 121, 120,
*Nset, nset=VCAX_AUDIT_0005, GENERATE
1, 121, 1,
*Nset, nset=Clamped, GENERATE
1, 111, 11,
*Material, name=Steel
*Elastic
210000.0, 0.3,
*Density
7.85e-9,
*Solid Section, elset=Eall, material=Steel
1.0,
*Boundary
Clamped, 1, 2
** node sets named by the *Boundary rows
*Step
*Frequency
4,
*Node Print, NSET=VCAX_AUDIT_0005
U,
*End Step
"""

SPELLINGS = _re_spelled(GOLD, {'solution.inp': SPELLING_SOLUTION})

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal deck", ALT, ("true",)),
    ("A2 alternative legal deck (eigen count 8)", ALT2, ("true",)),
    ("A3 alternative legal (every spelling at once)", SPELLINGS, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 section tampered", WRONG_SECTION, ("false",)),
    ("N3 material tampered", WRONG_LOAD, ("false",)),
    ("N4 fabricated summary (+10%)", FABRICATE_SUMMARY, ("false",)),
    ("N5 wrong token / replayed result", WRONG_TOKEN, ("false",)),
    ("N6 foreign native result", FOREIGN_RESULT, ("false",)),
    ("N7 fabricated mode field", FABRICATE_FIELD, ("false",)),
    ("N8 zero-byte native result", ZERO_DAT, ("false",)),
    ("N9 metrics only", METRICS_ONLY, ("false",)),
    ("N10 encoded summary", ENCODE_SUMMARY, ("false",)),
    ("N11 coarse mesh (5 elements)", COARSE, ("false",)),
]
