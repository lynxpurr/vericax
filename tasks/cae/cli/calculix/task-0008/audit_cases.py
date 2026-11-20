"""Audit cases for cae--cli--calculix--task-0008 (exact_match, L4 chain).

Two static steps in one job: step 1 applies FY=-100 N, step 2 adds FX=+50 N
without removing the first load. The verifier checks the step-2 transverse
displacement still equals the step-1 value and the axial displacement matches
the axial extension.
"""

BASE = r"""
set -e
cd /home/user/Desktop
export STEP1_FY=__STEP1_FY__
export STEP2_MODE=__STEP2_MODE__
export STEP2_FX=__STEP2_FX__
export STEP2_FY=__STEP2_FY__
python3 - <<'PYEOF'
import os
from pathlib import Path

n = 10
fy1 = float(os.environ["STEP1_FY"])
mode = os.environ["STEP2_MODE"]
fx2 = float(os.environ["STEP2_FX"])
fy2 = float(os.environ["STEP2_FY"])

lines = ["*Heading", "VeriCAX task-0008 two-step superposition", "*Node"]
for i in range(n + 1, 0, -1):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(n, 0, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step, name=Step-1", "*Static", "*Cload", f"11, 2, {fy1}",
          "*Node Print, NSET=All_Nodes", "U", "*End Step",
          "*Step, name=Step-2", "*Static"]
if mode == "add":
    lines += ["*Cload", f"11, 1, {fx2}"]
elif mode == "mod":
    lines += ["*Cload, OP=MOD", f"11, 1, {fx2}"]
elif mode == "reset_both":
    lines += ["*Cload, OP=NEW", f"11, 1, {fx2}", f"11, 2, {fy2}"]
elif mode == "reset_fx":
    lines += ["*Cload, OP=NEW", f"11, 1, {fx2}"]
else:
    raise SystemExit(f"unknown mode {mode}")
lines += ["*Node Print, NSET=All_Nodes", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path

maps, current = [], None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
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
            current[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            pass
assert len(maps) >= 2 and 11 in maps[0] and 11 in maps[1], "parse failed"
Path("summary.txt").write_text(f"{maps[0][11][1]!r}, {maps[1][11][0]!r}, {maps[1][11][1]!r}\n")
PYEOF
"""


def make(step1_fy=-100.0, mode="add", step2_fx=50.0, step2_fy=-100.0) -> str:
    return (BASE.replace("__STEP1_FY__", repr(step1_fy))
                .replace("__STEP2_MODE__", mode)
                .replace("__STEP2_FX__", repr(step2_fx))
                .replace("__STEP2_FY__", repr(step2_fy)))


GOLD = make()
ALT = make(mode="mod")
ALT2 = make(mode="reset_both")
RESET_ONLY_FX = make(mode="reset_fx")
WRONG_FX = make(step2_fx=40.0)
WRONG_STEP1 = make(step1_fy=-80.0)

SWAP = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = open("/home/user/Desktop/summary.txt").read().strip().split(",")
Path("/home/user/Desktop/summary.txt").write_text(", ".join([v[0].strip(), v[2].strip(), v[1].strip()]) + "\n")
PYEOF
"""

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in open("/home/user/Desktop/summary.txt").read().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(", ".join(repr(x * 1.10) for x in v) + "\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

COARSE = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path
n = 5
lines = ["*Heading", "coarse two-step deck", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {20.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Eall")
for e in range(1, n + 1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += ["*Nset, nset=Tip", "6",
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=Eall, material=Steel, section=RECT", "10.0, 10.0",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step, name=Step-1", "*Static", "*Cload", "6, 2, -100.0",
          "*Node Print, NSET=Tip", "U", "*End Step",
          "*Step, name=Step-2", "*Static", "*Cload", "6, 1, 50.0",
          "*Node Print, NSET=Tip", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-coarse.log 2>&1 || { tail -25 /tmp/ccx-coarse.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path
maps, cur = [], None
for raw in Path("solution.dat").read_text(errors="ignore").splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        if "displacements" in s.lower():
            cur = {}; maps.append(cur)
        else:
            cur = None
        continue
    if cur is not None:
        p = s.split()
        try: cur[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError): pass
assert len(maps) >= 2 and 6 in maps[0] and 6 in maps[1]
Path("summary.txt").write_text(f"{maps[0][6][1]!r}, {maps[1][6][0]!r}, {maps[1][6][1]!r}\n")
PYEOF
"""

WRONG_SECTION = GOLD + r"""
sed -i 's/10.0, 10.0/12.0, 10.0/' /home/user/Desktop/solution.inp
"""

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.191155, 0.0002380952, -0.191155' > summary.txt
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
    "N2 load reset (FY dropped)": "tampered_input",
    "N6 fabricated summary (+10%)": "fabricated_field",
    "N7 zero-byte solver output": "skipped_steps",
    "N8 metrics only": "metrics_only",
    "N9 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (OP=MOD)", ALT, ("true",)),
    ("A2 alternative legal (OP=NEW, both loads)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 load reset (FY dropped)", RESET_ONLY_FX, ("false",)),
    ("N3 wrong axial load", WRONG_FX, ("false",)),
    ("N4 wrong step-1 load", WRONG_STEP1, ("false",)),
    ("N5 wrong section", WRONG_SECTION, ("false",)),
    ("N6 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N7 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N8 metrics only", METRICS_ONLY, ("false",)),
    ("N9 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N10 swapped summary", SWAP, ("false",)),
    ("N11 coarse mesh (5 elements)", COARSE, ("false",)),
]