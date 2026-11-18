"""Audit cases for cae--cli--calculix--task-0002 (quantified_score).

The first case is the ground-truth source. Cases assert on the numeric verdict:
"ge" for accepted designs (score floor), "le" for rejected or baseline designs.

Reference design: a1=9.24, a2=6.68 mm. Beam theory gives |uy|=0.3479 mm and
sigma=max(76.0, 100.6)=100.6 MPa, both inside the limits, with mass 6500 ->
score 0.35. That is the analytic optimum of min mass s.t. |uy|<=0.35 (the stress
constraint is slack there): Lagrange gives a1/a2 = 7**(1/6) = 1.383.
"""

BASE = r"""
set -e
cd /home/user/Desktop
export A1=__A1__
export A2=__A2__
export ALT=__ALT__
python3 - <<'PYEOF'
import os, re, subprocess
from pathlib import Path

a1, a2 = float(os.environ["A1"]), float(os.environ["A2"])
reversed_order = os.environ["ALT"] == "1"

n = 10
lines = ["*Heading", "VeriCAX task-0002 submission", "*Node"]
order = range(n + 1, 0, -1) if reversed_order else range(1, n + 2)
for i in order:
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
if reversed_order:
    lines.append("*Element, type=B31, elset=TipSeg")
    for e in range(10, 5, -1):
        lines.append(f"{e}, {e}, {e + 1}")
    lines.append("*Element, type=B31, elset=RootSeg")
    for e in range(5, 0, -1):
        lines.append(f"{e}, {e}, {e + 1}")
    sec_order = [("TipSeg", a2), ("RootSeg", a1)]
else:
    lines.append("*Element, type=B31, elset=RootSeg")
    for e in range(1, 6):
        lines.append(f"{e}, {e}, {e + 1}")
    lines.append("*Element, type=B31, elset=TipSeg")
    for e in range(6, 11):
        lines.append(f"{e}, {e}, {e + 1}")
    sec_order = [("RootSeg", a1), ("TipSeg", a2)]

lines += ["*Material, name=Steel", "*Elastic", "210000.0, 0.3"]
for name, side in sec_order:
    lines += [f"*Beam Section, elset={name}, material=Steel, section=RECT",
              f"{side!r}, {side!r}"]
lines += ["*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
          "*Boundary", "1, 1, 6" if reversed_order else "1, 1, 6, 0.0",
          "*Step", "*Static", "*Cload", "11, 2, -100",
          "*Node Print, NSET=All_Nodes", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))

subprocess.run(["/usr/bin/ccx", "solution"], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
dat = Path("solution.dat").read_text(errors="ignore")
uy, head = None, None
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
            if int(p[0]) == 11:
                uy = float(p[2])
        except (ValueError, IndexError):
            pass
assert uy is not None, "parse failed"
Path("summary.txt").write_text(f"{a1}, {a2}, {uy}\n")
PYEOF
"""


def make(a1: float, a2: float, alt: bool = False) -> str:
    return (BASE.replace("__A1__", repr(a1))
                .replace("__A2__", repr(a2))
                .replace("__ALT__", "1" if alt else "0"))


GOLD = make(9.24, 6.68)
ALT = make(9.24, 6.68, alt=True)
# Deflection-only violation: |uy| ~ 0.591 mm, sigma max 138.9 MPa (inside 140).
WEAK_ROOT = make(8.0, 6.0)
# Strength-only violation: sigma at the step 180.3 MPa, |uy| ~ 0.341 mm (inside 0.35).
WEAK_TIP = make(12.0, 5.5)
# Variable outside the declared bounds.
OUT_OF_BOUNDS = make(15.0, 4.0)
# Feasible but no improvement over the uniform baseline.
BASELINE = make(10.0, 10.0)

# Fabricated summary: keep the gold deck and solver output, lie about sections.
FABRICATE = r"""
python3 - <<'PYEOF'
from pathlib import Path
Path("/home/user/Desktop/summary.txt").write_text("6.0, 4.0, -0.35\n")
PYEOF
"""

CASES = [
    ("P1 positive (gold optimum)", GOLD, ("ge", 0.34)),
    ("P2 robust (gold re-run)", GOLD, ("ge", 0.34)),
    ("A1 alternative legal encoding", ALT, ("ge", 0.34)),
    ("N1 empty delivery", "", ("le", 0.0)),
    ("N2 deflection-only violation", WEAK_ROOT, ("le", 0.0)),
    ("N3 strength-only violation", WEAK_TIP, ("le", 0.0)),
    ("N4 variable out of bounds", OUT_OF_BOUNDS, ("le", 0.0)),
    ("N5 fabricated summary", GOLD + FABRICATE, ("le", 0.0)),
    ("N6 baseline copied (no gain)", BASELINE, ("le", 0.001)),
]
