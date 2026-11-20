"""Audit cases for cae--cli--cross-solver--task-0001 (L6 prototype).

The first case is the ground-truth source. The task validates the rejection
half of L6: the submitted full-field .dat must equal the verifier's fresh ccx
run, and the challenge set name must be present. A fabricated non-empty .dat,
a replayed/wrong-token result, and a foreign native result are rejected.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

TOKEN = "VCAX_AUDIT_0001"
n = 10
lines = ["*Heading", "VeriCAX cross-solver task-0001 (L6 prototype)", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [f"*Nset, nset={TOKEN}", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Static", "*Cload", "11, 2, -100.0",
          f"*Node Print, NSET={TOKEN}", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path

TOKEN = "VCAX_AUDIT_0001"
field, current = None, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        if "displacements" in s.lower() and TOKEN.lower() in s.lower():
            current = {}
            field = current
        else:
            current = None
        continue
    if current is not None:
        p = s.split()
        try:
            current[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            pass
assert field and 11 in field, "parse failed"
Path("summary.txt").write_text(f"{field[11][1]}\n")
PYEOF
"""

# Legal alternative: reversed node lines, element cards tip-first in two cards,
# separate elset cards, boundary without value, integer load.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

TOKEN = "VCAX_AUDIT_0001"
n = 10
lines = ["*Heading", "alternative legal L6 deck", "*Node"]
for i in range(n + 1, 0, -1):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31")
for e in range(10, 0, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Elset, elset=AllElems", ", ".join(str(e) for e in range(1, n + 1)),
          f"*Nset, nset={TOKEN}", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=AllElems, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6",
          "*Step", "*Static", "*Cload", "11, 2, -100",
          f"*Node Print, NSET={TOKEN}", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt.log 2>&1 || { tail -25 /tmp/ccx-alt.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path

TOKEN = "VCAX_AUDIT_0001"
field, current = None, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        if "displacements" in s.lower() and TOKEN.lower() in s.lower():
            current = {}
            field = current
        else:
            current = None
        continue
    if current is not None:
        p = s.split()
        try:
            current[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            pass
assert field and 11 in field
Path("summary.txt").write_text(f"{field[11][1]}\n")
PYEOF
"""

# Second legal alternative: elset cards after a bare *Element block, integer
# load, same challenge set.
ALT2 = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

TOKEN = "VCAX_AUDIT_0001"
n = 10
lines = ["*Heading", "alternative legal L6 deck (elset cards)", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Elset, elset=EveryElem", ", ".join(str(e) for e in range(1, n + 1)),
          f"*Nset, nset={TOKEN}", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=EveryElem, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Static", "*Cload", "11, 2, -100",
          f"*Node Print, NSET={TOKEN}", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt2.log 2>&1 || { tail -25 /tmp/ccx-alt2.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path

TOKEN = "VCAX_AUDIT_0001"
field, current = None, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        if "displacements" in s.lower() and TOKEN.lower() in s.lower():
            current = {}
            field = current
        else:
            current = None
        continue
    if current is not None:
        p = s.split()
        try:
            current[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            pass
assert field and 11 in field
Path("summary.txt").write_text(f"{field[11][1]}\n")
PYEOF
"""

WRONG_SECTION = GOLD + r"""
sed -i 's/10.0, 10.0/12.0, 10.0/' /home/user/Desktop/solution.inp
"""

WRONG_LOAD = GOLD + r"""
sed -i 's/11, 2, -100.0/11, 2, -80.0/' /home/user/Desktop/solution.inp
"""

FABRICATE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = float(Path("/home/user/Desktop/summary.txt").read_text())
Path("/home/user/Desktop/summary.txt").write_text(f"{v * 1.10!r}\n")
PYEOF
"""

# Non-empty fabricated full-field result: perturb every displacement by 2%.
FABRICATE_FIELD = GOLD + r"""
python3 - <<'PYEOF'
import re
from pathlib import Path

TOKEN = "VCAX_AUDIT_0001"
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
sed -i 's/VCAX_AUDIT_0001/VCAX_OLD_0001/' /home/user/Desktop/solution.dat
"""

# Foreign native result: an XDMF-style file instead of a CalculiX .dat.
FOREIGN_RESULT = GOLD + r"""
cat > /home/user/Desktop/solution.dat <<'EOF'
<?xml version="1.0"?>
<Xdmf Version="3.0"><Domain><Grid Name="beam"><Attribute Name="u"/></Grid></Domain></Xdmf>
EOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

COARSE = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path
TOKEN = "VCAX_AUDIT_0001"
n = 5
lines = ["*Heading", "coarse L6 deck", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {20.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [f"*Nset, nset={TOKEN}", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0", "*Step", "*Static", "*Cload", "6, 2, -100.0",
          f"*Node Print, NSET={TOKEN}", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-coarse.log 2>&1 || { tail -25 /tmp/ccx-coarse.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path
TOKEN = "VCAX_AUDIT_0001"
field, cur = None, None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        if "displacements" in s.lower() and TOKEN.lower() in s.lower():
            cur = {}; field = cur
        else:
            cur = None
        continue
    if cur is not None:
        p = s.split()
        try: cur[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError): pass
assert field and 6 in field
Path("summary.txt").write_text(f"{field[6][1]}\n")
PYEOF
"""

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.191155' > summary.txt
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
    "N2 section tampered": "tampered_input",
    "N7 fabricated full-field dat": "fabricated_field",
    "N8 zero-byte native result": "skipped_steps",
    "N9 metrics only": "metrics_only",
    "N10 encoded summary": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal deck", ALT, ("true",)),
    ("A2 alternative legal deck (elset cards)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 section tampered", WRONG_SECTION, ("false",)),
    ("N3 load tampered", WRONG_LOAD, ("false",)),
    ("N4 fabricated summary (+10%)", FABRICATE_SUMMARY, ("false",)),
    ("N5 wrong token / replayed result", WRONG_TOKEN, ("false",)),
    ("N6 foreign native result", FOREIGN_RESULT, ("false",)),
    ("N7 fabricated full-field dat", FABRICATE_FIELD, ("false",)),
    ("N8 zero-byte native result", ZERO_DAT, ("false",)),
    ("N9 metrics only", METRICS_ONLY, ("false",)),
    ("N10 encoded summary", ENCODE_SUMMARY, ("false",)),
    ("N11 coarse mesh (5 elements)", COARSE, ("false",)),
]