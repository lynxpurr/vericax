"""Audit cases for cae--cli--calculix--task-0006 (exact_match, L1-L3).

The first case is the ground-truth source. Uniform steel cantilever column
(100 x 10 x 10 mm, 10 B31 elements) under a 1000 N axial reference load; the
reported quantities are the first buckling factor and the critical load.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

n = 10
lines = ["*Heading", "VeriCAX task-0006 reference solution", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Buckle", "1, 1", "*Cload",
          "11, 1, -1000.0",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path

armed, factor = False, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if "bucklingfactoroutput" in s.lower().replace(" ", ""):
        armed = True
        continue
    if not armed:
        continue
    parts = s.split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        continue
    if len(values) >= 2 and int(values[0]) == 1:
        factor = values[1]
        break
assert factor is not None, "buckling factor parse failed"
Path("summary.txt").write_text(f"{factor!r}, {factor * 1000.0!r}\n")
PYEOF
"""

# Legal alternative: reversed node lines, elements tip-first in two cards,
# separate elset cards, boundary without value, integer load.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

n = 10
lines = ["*Heading", "alternative legal buckling deck", "*Node"]
for i in range(n + 1, 0, -1):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31")
for e in range(10, 0, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Elset, elset=Root", ", ".join(str(e) for e in range(1, n + 1)),
          "*Nset, nset=Nall", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Root, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6",
          "*Step", "*Buckle", "1, 1", "*Cload",
          "11, 1, -1000",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt.log 2>&1 || { tail -25 /tmp/ccx-alt.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path

armed, factor = False, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if "bucklingfactoroutput" in s.lower().replace(" ", ""):
        armed = True
        continue
    if not armed:
        continue
    parts = s.split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        continue
    if len(values) >= 2 and int(values[0]) == 1:
        factor = values[1]
        break
assert factor is not None, "buckling factor parse failed"
Path("summary.txt").write_text(f"{factor!r}, {factor * 1000.0!r}\n")
PYEOF
"""

# Second legal alternative: separate elset cards, single-field *Buckle data.
ALT2 = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

n = 10
lines = ["*Heading", "alternative legal buckling deck (elset cards)", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Elset, elset=AllElems", ", ".join(str(e) for e in range(1, n + 1)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=AllElems, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Buckle", "1", "*Cload",
          "11, 1, -1000.0",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt2.log 2>&1 || { tail -25 /tmp/ccx-alt2.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path

armed, factor = False, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if "bucklingfactoroutput" in s.lower().replace(" ", ""):
        armed = True
        continue
    if not armed:
        continue
    parts = s.split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        continue
    if len(values) >= 2 and int(values[0]) == 1:
        factor = values[1]
        break
assert factor is not None, "buckling factor parse failed"
Path("summary.txt").write_text(f"{factor!r}, {factor * 1000.0!r}\n")
PYEOF
"""

WRONG_LOAD = GOLD + r"""
sed -i 's/11, 1, -1000.0/11, 1, -2000.0/' /home/user/Desktop/solution.inp
"""

WRONG_BC = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/solution.inp")
p.write_text(p.read_text().replace("*Boundary\n1, 1, 6, 0.0",
                                   "*Boundary\n1, 1, 6, 0.0\n11, 1, 3, 0.0"))
PYEOF
"""

WRONG_SECTION = GOLD + r"""
sed -i 's/10.0, 10.0/12.0, 10.0/' /home/user/Desktop/solution.inp
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
lines = ["*Heading", "coarse buckling deck", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {20.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Buckle", "1, 1", "*Cload",
          "6, 1, -1000.0", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-coarse.log 2>&1 || { tail -25 /tmp/ccx-coarse.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path
armed, factor = False, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if "bucklingfactoroutput" in s.lower().replace(" ", ""):
        armed = True
        continue
    if not armed:
        continue
    parts = s.split()
    try:
        values = [float(p) for p in parts]
    except ValueError:
        continue
    if len(values) >= 2 and int(values[0]) == 1:
        factor = values[1]
        break
assert factor is not None
Path("summary.txt").write_text(f"{factor!r}, {factor * 1000.0!r}\n")
PYEOF
"""

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '42.96557, 42965.57' > summary.txt
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
    "N2 reference load tampered": "tampered_input",
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
    ("N2 reference load tampered", WRONG_LOAD, ("false",)),
    ("N3 extra boundary constraint", WRONG_BC, ("false",)),
    ("N4 wrong section", WRONG_SECTION, ("false",)),
    ("N5 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N6 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N7 metrics only", METRICS_ONLY, ("false",)),
    ("N8 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N9 coarse mesh (5 elements)", COARSE, ("false",)),
]