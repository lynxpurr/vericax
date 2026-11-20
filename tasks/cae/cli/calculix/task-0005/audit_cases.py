"""Audit cases for cae--cli--calculix--task-0005 (exact_match, L1-L3).

The first case is the ground-truth source. Uniform steel cantilever
(100 x 10 x 10 mm, 10 B31 elements); the reported quantities are the first
eigenvalue and its frequency in Hz.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

n = 10
lines = ["*Heading", "VeriCAX task-0005 reference solution", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Density", "7.85e-09",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Frequency", "1, 1",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path

armed = False
pair = None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if "eigenvalueoutput" in s.lower().replace(" ", ""):
        armed = True
        continue
    if not armed:
        continue
    parts = s.split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        continue
    if len(values) >= 4 and int(values[0]) == 1:
        pair = (values[1], values[3])
        break
assert pair is not None, "eigenvalue parse failed"
Path("summary.txt").write_text(f"{pair[0]!r}, {pair[1]!r}\n")
PYEOF
"""

# Legal alternative: reversed node lines, elements tip-first in two cards,
# separate elset cards, boundary without value.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

n = 10
lines = ["*Heading", "alternative legal modal deck", "*Node"]
for i in range(n + 1, 0, -1):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31")
for e in range(10, 0, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Elset, elset=Root", ", ".join(str(e) for e in range(1, n + 1)),
          "*Nset, nset=Nall", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Density", "7.85e-09",
          "*Beam Section, elset=Root, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6",
          "*Step", "*Frequency", "1, 1",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt.log 2>&1 || { tail -25 /tmp/ccx-alt.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path

armed, pair = False, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if "eigenvalueoutput" in s.lower().replace(" ", ""):
        armed = True
        continue
    if not armed:
        continue
    parts = s.split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        continue
    if len(values) >= 4 and int(values[0]) == 1:
        pair = (values[1], values[3])
        break
assert pair is not None, "eigenvalue parse failed"
Path("summary.txt").write_text(f"{pair[0]!r}, {pair[1]!r}\n")
PYEOF
"""

# Second legal alternative: single-field *Frequency data, element set cards
# after a bare *Element block, ascending order but its own print set.
ALT2 = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

n = 10
lines = ["*Heading", "alternative legal modal deck (elset cards)", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Elset, elset=AllElems", ", ".join(str(e) for e in range(1, n + 1)),
          "*Nset, nset=Fixed", "1",
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Density", "7.85e-09",
          "*Beam Section, elset=AllElems, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Frequency", "1",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt2.log 2>&1 || { tail -25 /tmp/ccx-alt2.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path

armed, pair = False, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if "eigenvalueoutput" in s.lower().replace(" ", ""):
        armed = True
        continue
    if not armed:
        continue
    parts = s.split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        continue
    if len(values) >= 4 and int(values[0]) == 1:
        pair = (values[1], values[3])
        break
assert pair is not None, "eigenvalue parse failed"
Path("summary.txt").write_text(f"{pair[0]!r}, {pair[1]!r}\n")
PYEOF
"""

WRONG_DENSITY = GOLD + r"""
sed -i 's/7.85e-09/7.85e-08/' /home/user/Desktop/solution.inp
"""

WRONG_SECTION = GOLD + r"""
sed -i 's/10.0, 10.0/12.0, 10.0/' /home/user/Desktop/solution.inp
"""

EXTRA_BC = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/solution.inp")
p.write_text(p.read_text().replace("*Boundary\n1, 1, 6, 0.0",
                                   "*Boundary\n1, 1, 6, 0.0\n11, 1, 3, 0.0"))
PYEOF
"""

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in Path("/home/user/Desktop/summary.txt").read_text().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(f"{v[0] * 1.10!r}, {v[1] * 1.10!r}\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

COARSE = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

n = 5
lines = ["*Heading", "coarse modal deck", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {20.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Density", "7.85e-09",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0", "*Step", "*Frequency", "1, 1",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-coarse.log 2>&1 || { tail -25 /tmp/ccx-coarse.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path
armed, pair = False, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if "eigenvalueoutput" in s.lower().replace(" ", ""):
        armed = True
        continue
    if not armed:
        continue
    parts = s.split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        continue
    if len(values) >= 4 and int(values[0]) == 1:
        pair = (values[1], values[3])
        break
assert pair is not None
Path("summary.txt").write_text(f"{pair[0]!r}, {pair[1]!r}\n")
PYEOF
"""

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '27302570.0, 831.6142' > summary.txt
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
    "N2 density tampered": "tampered_input",
    "N5 fabricated summary (+10%)": "fabricated_field",
    "N6 zero-byte solver output": "skipped_steps",
    "N7 metrics only": "metrics_only",
    "N8 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal deck", ALT, ("true",)),
    ("A2 alternative legal deck (elset cards)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 density tampered", WRONG_DENSITY, ("false",)),
    ("N3 wrong section", WRONG_SECTION, ("false",)),
    ("N4 extra boundary constraint", EXTRA_BC, ("false",)),
    ("N5 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N6 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N7 metrics only", METRICS_ONLY, ("false",)),
    ("N8 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N9 coarse mesh (5 elements)", COARSE, ("false",)),
]