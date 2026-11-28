"""Audit cases for cae--cli--calculix--task-0012 (report reconstruction).

The first case is the ground-truth source. The report specifies a 2-bar truss;
the verifier checks the reconstructed T3D2 model and re-solves it.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

lines = ["*Heading", "VeriCAX task-0012 reconstructed truss", "*Node",
         "1, 0.0, 0.0, 0.0", "2, 1000.0, 0.0, 0.0", "3, 500.0, 500.0, 0.0",
         "*Element, type=T3D2, elset=Bars", "1, 1, 3", "2, 2, 3",
         "*Nset, nset=Pin1", "1", "*Nset, nset=Pin2", "2",
         "*Nset, nset=Tip", "3", "*Nset, nset=AllNodes", "1, 2, 3",
         "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
         "*Solid Section, elset=Bars, material=Steel", "100.0",
         "*Boundary", "Pin1, 1, 2, 0.0", "Pin2, 1, 2, 0.0", "AllNodes, 3, 3, 0.0",
         "*Step", "*Static", "*Cload", "3, 2, -1000.0",
         "*Node Print, NSET=Tip", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path
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
            u[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            pass
assert 3 in u, "parse failed"
Path("summary.txt").write_text(f"{u[3][0]!r}, {u[3][1]!r}\n")
PYEOF
"""

ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path
lines = ["*Heading", "alternative truss encoding", "*Node",
         "3, 500.0, 500.0, 0.0", "2, 1000.0, 0.0, 0.0", "1, 0.0, 0.0, 0.0",
         "*Element, type=T3D2", "2, 3, 2", "1, 3, 1",
         "*Elset, elset=AllBars", "1, 2",
         "*Nset, nset=Base", "1, 2", "*Nset, nset=Tip", "3",
         "*Nset, nset=AllNodes", "1, 2, 3",
         "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
         "*Solid Section, elset=AllBars, material=Steel", "100.0",
         "*Boundary", "Base, 1, 2, 0.0", "AllNodes, 3, 3, 0.0",
         "*Step", "*Static", "*Cload", "3, 2, -1000",
         "*Node Print, NSET=Tip", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt.log 2>&1 || { tail -25 /tmp/ccx-alt.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path
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
            u[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            pass
assert 3 in u
Path("summary.txt").write_text(f"{u[3][0]!r}, {u[3][1]!r}\n")
PYEOF
"""

ALT2 = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path
lines = ["*Heading", "alternative truss encoding (per-node supports)", "*Node",
         "1, 0.0, 0.0, 0.0", "2, 1000.0, 0.0, 0.0", "3, 500.0, 500.0, 0.0",
         "*Element, type=T3D2, elset=Bars", "2, 2, 3", "1, 1, 3",
         "*Nset, nset=Nall", "1, 2, 3",
         "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
         "*Solid Section, elset=Bars, material=Steel", "100.0",
         "*Boundary", "1, 1, 3", "2, 1, 3", "3, 3, 3",
         "*Step", "*Static", "*Cload", "3, 2, -1000",
         "*Node Print, NSET=Nall", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt2.log 2>&1 || { tail -25 /tmp/ccx-alt2.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path
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
            u[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            pass
assert 3 in u
Path("summary.txt").write_text(f"{u[3][0]!r}, {u[3][1]!r}\n")
PYEOF
"""

WRONG_AREA = GOLD + r"""
sed -i 's/^100.0$/50.0/' /home/user/Desktop/solution.inp
"""

WRONG_LOAD = GOLD + r"""
sed -i 's/3, 2, -1000.0/3, 2, -800.0/' /home/user/Desktop/solution.inp
"""

ROLLER = GOLD + r"""
sed -i 's/Pin2, 1, 2, 0.0/Pin2, 2, 2, 0.0/' /home/user/Desktop/solution.inp
"""

WRONG_NODE = GOLD + r"""
sed -i 's/3, 500.0, 500.0, 0.0/3, 500.0, 400.0, 0.0/' /home/user/Desktop/solution.inp
"""

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in Path("/home/user/Desktop/summary.txt").read_text().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(f"{v[0]!r}, {v[1] * 1.10!r}\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '0.0, -0.0336718' > summary.txt
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
    "N2 area tampered": "tampered_input",
    "N6 fabricated summary (+10%)": "fabricated_field",
    "N7 zero-byte solver output": "skipped_steps",
    "N8 metrics only": "metrics_only",
    "N9 encoded payload": "encoded_payload",
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
VeriCAX task-0012 reconstructed truss
*Node, NSET=VCAX_ALLNODES
1, 0.0, 0.0
2, 1000.0, 0.0
3, 500.0, 500.0
*Element, type=T3D2, elset=Bars
1, 1, 3
2, 2, 3,
*Nset, nset=Pin1
1,
*Nset, nset=Pin2
2,
*Nset, nset=Tip
3,
*Nset, nset=AllNodes, GENERATE
1, 3, 1,
*Material, name=Steel
*Elastic
210000.0, 0.3,
*Solid Section, elset=Bars, material=Steel
100.0,
*Boundary
Pin1, 1, 2
Pin2, 1, 2
AllNodes, 3
** node sets named by the *Boundary rows
** sets of one member, named by the load rows
*Nset, nset=VCAX_L1
3
*Step
*Static
*Cload
VCAX_L1, 2, -1000.0
*Node Print, NSET=Tip
U,
*End Step
"""

SPELLINGS = _re_spelled(GOLD, {'solution.inp': SPELLING_SOLUTION})

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal deck", ALT, ("true",)),
    ("A2 alternative legal deck (per-node supports)", ALT2, ("true",)),
    ("A3 alternative legal (every spelling at once)", SPELLINGS, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 area tampered", WRONG_AREA, ("false",)),
    ("N3 load tampered", WRONG_LOAD, ("false",)),
    ("N4 roller support (mechanism)", ROLLER, ("false",)),
    ("N5 wrong node coordinates", WRONG_NODE, ("false",)),
    ("N6 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N7 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N8 metrics only", METRICS_ONLY, ("false",)),
    ("N9 encoded payload", ENCODE_SUMMARY, ("false",)),
]