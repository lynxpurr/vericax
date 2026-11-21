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

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal deck", ALT, ("true",)),
    ("A2 alternative legal deck (eigen count 8)", ALT2, ("true",)),
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
