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

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal deck", ALT, ("true",)),
    ("A2 alternative legal deck (elset cards)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 fabricated summary", GOLD + FABRICATE, ("false",)),
    ("N3 zero-byte solver output", GOLD + ZERO_DAT, ("false",)),
    ("N4 tampered sections", GOLD + TAMPER, ("false",)),
    ("N5 metrics only", METRICS_ONLY, ("false",)),
    ("N6 encoded payload", GOLD + ENCODED_PAYLOAD, ("false",)),
]
