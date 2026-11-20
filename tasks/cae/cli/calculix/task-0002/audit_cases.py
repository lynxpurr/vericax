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
alt_mode = os.environ["ALT"]
reversed_order = alt_mode == "1"
elset_cards = alt_mode == "2"

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
elif not elset_cards:
    lines.append("*Element, type=B31, elset=RootSeg")
    for e in range(1, 6):
        lines.append(f"{e}, {e}, {e + 1}")
    lines.append("*Element, type=B31, elset=TipSeg")
    for e in range(6, 11):
        lines.append(f"{e}, {e}, {e + 1}")
    sec_order = [("RootSeg", a1), ("TipSeg", a2)]

else:
    lines.append("*Element, type=B31")
    for e in range(1, n + 1):
        lines.append(f"{e}, {e}, {e + 1}")
    lines += [
        "*Elset, elset=SegRoot", ", ".join(str(e) for e in range(1, 6)),
        "*Elset, elset=SegTip", ", ".join(str(e) for e in range(6, 11)),
    ]
    sec_order = [("SegTip", a2), ("SegRoot", a1)]

print_set = "PrintNodes" if elset_cards else "All_Nodes"
lines += ["*Material, name=Steel", "*Elastic", "210000.0, 0.3"]
for name, side in sec_order:
    lines += [f"*Beam Section, elset={name}, material=Steel, section=RECT",
              f"{side!r}, {side!r}"]
lines += [f"*Nset, nset={print_set}", ", ".join(str(i) for i in range(1, n + 2)),
          "*Boundary", "1, 1, 6" if reversed_order else "1, 1, 6, 0.0",
          "*Step", "*Static", "*Cload",
          "11, 2, -100.0" if elset_cards else "11, 2, -100",
          f"*Node Print, NSET={print_set}", "U", "*End Step", ""]
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


def make(a1: float, a2: float, alt=0) -> str:
    mode = str(alt)
    return (BASE.replace("__A1__", repr(a1))
                .replace("__A2__", repr(a2))
                .replace("__ALT__", mode))


GOLD = make(9.24, 6.68)
ALT = make(9.24, 6.68, alt=1)
ALT2 = make(9.24, 6.68, alt=2)
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

# Only the metrics, no deck or solver output (kind: metrics_only).
METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '9.24, 6.68, -0.3479' > summary.txt
"""

# Solver output skipped entirely (kind: skipped_steps).
SKIP_SOLVER = GOLD + """
rm -f solution.dat
"""

# Required artifact replaced by an encoded payload (kind: encoded_payload).
ENCODE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
import base64
from pathlib import Path
Path("/home/user/Desktop/summary.txt").write_text(
    base64.b64encode(b"9.24, 6.68, -0.3479").decode() + "\n")
PYEOF
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N4 variable out of bounds": "tampered_input",
    "N5 fabricated summary": "fabricated_field",
    "N7 metrics only": "metrics_only",
    "N8 skipped solver output": "skipped_steps",
    "N9 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold optimum)", GOLD, ("ge", 0.34)),
    ("P2 robust (gold re-run)", GOLD, ("ge", 0.34)),
    ("A1 alternative legal encoding", ALT, ("ge", 0.34)),
    ("A2 alternative legal encoding (elset cards)", ALT2, ("ge", 0.34)),
    ("N1 empty delivery", "", ("le", 0.0)),
    ("N2 deflection-only violation", WEAK_ROOT, ("le", 0.0)),
    ("N3 strength-only violation", WEAK_TIP, ("le", 0.0)),
    ("N4 variable out of bounds", OUT_OF_BOUNDS, ("le", 0.0)),
    ("N5 fabricated summary", GOLD + FABRICATE, ("le", 0.0)),
    ("N6 baseline copied (no gain)", BASELINE, ("le", 0.001)),
    ("N7 metrics only", METRICS_ONLY, ("le", 0.0)),
    ("N8 skipped solver output", SKIP_SOLVER, ("le", 0.0)),
    ("N9 encoded payload", ENCODE_SUMMARY, ("le", 0.0)),
]
