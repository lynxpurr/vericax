"""Audit cases for cae--cli--cross-solver--task-0002 (software-selection).

Required tool: CalculiX (*BUCKLE linearized buckling of the P1 beam column,
compressed at the free end). The submitted native pair (.inp + .dat) must be
ccx's output for THIS deck: the verifier re-runs *BUCKLE and compares the
buckling factor and the printed eigenmode field node by node. dolfinx 0.10
cannot deliver this native family (no buckling solver, XDMF/HDF5 results), so
a foreign or fabricated native result is rejected.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

TOKEN = "VCAX_AUDIT_0002"
n = 10
lines = ["*Heading", "VeriCAX cross-solver task-0002 (buckling)", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [f"*Nset, nset={TOKEN}", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Buckle", "4,", "*Cload", "11, 1, -1000.0",
          f"*Node Print, NSET={TOKEN}", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path

compact = lambda s: re.sub(r"\s+", "", s).upper()
state = 0
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    c = compact(s)
    if re.match(r"^[A-Za-z*]", s):
        if state == 1 and "EIGENVALUENUMBER" in c:
            break
        if "BUCKLINGFACTOROUTPUT" in c:
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
                Path("summary.txt").write_text(repr(v) + "\n")
                raise SystemExit(0)
raise SystemExit(1)
PYEOF
"""

# Legal alternative: reversed node lines, element cards tip-first in two
# cards, separate elset cards, boundary without value, six eigenvalues.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

TOKEN = "VCAX_AUDIT_0002"
n = 10
lines = ["*Heading", "alternative legal buckling deck", "*Node"]
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
          "*Step", "*Buckle", "6,", "*Cload", "11, 1, -1000.0",
          f"*Node Print, NSET={TOKEN}", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path

compact = lambda s: re.sub(r"\s+", "", s).upper()
state = 0
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    c = compact(s)
    if re.match(r"^[A-Za-z*]", s):
        if state == 1 and "EIGENVALUENUMBER" in c:
            break
        if "BUCKLINGFACTOROUTPUT" in c:
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
                Path("summary.txt").write_text(repr(v) + "\n")
                raise SystemExit(0)
raise SystemExit(1)
PYEOF
"""

# Legal alternative 2: scientific-notation load literal and a different
# eigenvalue request; same physics, same token.
ALT2 = ALT.replace("alternative legal buckling deck",
                   "alternative legal buckling deck (scientific load)")
ALT2 = ALT2.replace('"*Step", "*Buckle", "6,", "*Cload", "11, 1, -1000.0",',
                    '"*Step", "*Buckle", "8,", "*Cload", "11, 1, -1.0e3",')

WRONG_SECTION = GOLD + r"""
sed -i 's/10.0, 10.0/12.0, 10.0/' /home/user/Desktop/solution.inp
"""

WRONG_LOAD = GOLD + r"""
sed -i 's/11, 1, -1000.0/11, 2, -1000.0/' /home/user/Desktop/solution.inp
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

TOKEN = "VCAX_AUDIT_0002"
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
sed -i 's/VCAX_AUDIT_0002/VCAX_OLD_0002/' /home/user/Desktop/solution.dat
"""

# Foreign native result: an XDMF-style file instead of a CalculiX .dat (the
# dolfinx result family of the merged image).
FOREIGN_RESULT = GOLD + r"""
cat > /home/user/Desktop/solution.dat <<'EOF'
<?xml version="1.0"?>
<Xdmf Version="3.0"><Domain><Grid Name="column"><Attribute Name="mode_1"/></Grid></Domain></Xdmf>
EOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf 'placeholder\n' > solution.inp
printf 'placeholder\n' > solution.dat
printf '%s\n' '43.28635' > summary.txt
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
TOKEN = "VCAX_AUDIT_0002"
n = 5
lines = ["*Heading", "coarse buckling deck", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {20.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [f"*Nset, nset={TOKEN}", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0", "*Step", "*Buckle", "4,",
          "*Cload", "11, 1, -1000.0",
          f"*Node Print, NSET={TOKEN}", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-coarse.log 2>&1 || { tail -25 /tmp/ccx-coarse.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path

compact = lambda s: re.sub(r"\s+", "", s).upper()
state = 0
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    c = compact(s)
    if re.match(r"^[A-Za-z*]", s):
        if state == 1 and "EIGENVALUENUMBER" in c:
            break
        if "BUCKLINGFACTOROUTPUT" in c:
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
                Path("summary.txt").write_text(repr(v) + "\n")
                raise SystemExit(0)
raise SystemExit(1)
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
    ("A2 alternative legal deck (split prints)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 section tampered", WRONG_SECTION, ("false",)),
    ("N3 load tampered", WRONG_LOAD, ("false",)),
    ("N4 fabricated summary (+10%)", FABRICATE_SUMMARY, ("false",)),
    ("N5 wrong token / replayed result", WRONG_TOKEN, ("false",)),
    ("N6 foreign native result", FOREIGN_RESULT, ("false",)),
    ("N7 fabricated mode field", FABRICATE_FIELD, ("false",)),
    ("N8 zero-byte native result", ZERO_DAT, ("false",)),
    ("N9 metrics only", METRICS_ONLY, ("false",)),
    ("N10 encoded summary", ENCODE_SUMMARY, ("false",)),
    ("N11 coarse mesh (5 elements)", COARSE, ("false",)),
]
