"""Audit cases for cae--cli--calculix--task-0003 (exact_match, L4 chain).

Two load cases in one job; the verifier additionally requires the measured
step-2/step-1 displacement ratio to be exactly 2 (linear response). The negative
cases target the multi-step failure modes: load not changed, load accumulated,
summary values swapped, second step dropped.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
import re, subprocess
from pathlib import Path

n = 10
lines = ["*Heading", "VeriCAx task-0003 two load cases", "*Node"]
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
    "*Boundary", "1, 1, 6, 0.0",
    "*Step, name=Step-1", "*Static", "*Cload", "11, 2, -100.0",
    "*Node Print, NSET=All_Nodes", "U", "*End Step",
    "*Step, name=Step-2", "*Static", "*Cload, OP=NEW", "11, 2, -200.0",
    "*Node Print, NSET=All_Nodes", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
subprocess.run(["/usr/bin/ccx", "solution"], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

dat = Path("solution.dat").read_text(errors="ignore")
maps, current = [], None
for raw in dat.splitlines():
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
            current[int(p[0])] = float(p[2])
        except (ValueError, IndexError):
            pass
assert len(maps) >= 2 and 11 in maps[0] and 11 in maps[1], "parse failed"
Path("summary.txt").write_text(f"{maps[0][11]}, {maps[1][11]}\n")
PYEOF
"""

# Legal alternative: step cards written with the load line first, extra output
# requests, different set/section names, and *Node File alongside *Node Print.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
import re, subprocess
from pathlib import Path

n = 10
lines = ["*Heading", "alternative encoding", "*Node"]
for i in range(n + 1, 0, -1):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=Thin")
for e in range(10, 5, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines.append("*Element, type=B31, elset=Thick")
for e in range(5, 0, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [
    "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
    "*Beam Section, elset=Thin, material=Steel, section=RECT", "6.0, 6.0",
    "*Beam Section, elset=Thick, material=Steel, section=RECT", "10.0, 10.0",
    "*Nset, nset=Nall1", ", ".join(str(i) for i in range(1, n + 2)),
    "*Boundary", "1, 1, 6",
    "*Step, name=A", "*Static", "*Cload", "11, 2, -100",
    "*Node File", "U", "*Node Print, NSET=Nall1", "U", "*End Step",
    "*Step, name=B", "*Static", "*Cload, OP=NEW", "11, 2, -200",
    "*Node Print, NSET=Nall1", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
subprocess.run(["/usr/bin/ccx", "solution"], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
dat = Path("solution.dat").read_text(errors="ignore")
maps, current = [], None
for raw in dat.splitlines():
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
            current[int(p[0])] = float(p[2])
        except (ValueError, IndexError):
            pass
Path("summary.txt").write_text(f"{maps[0][11]}, {maps[1][11]}\n")
PYEOF
"""


def _variant(step2_load: str, label: str) -> str:
    """Rebuild the gold deck with a different step-2 load."""
    return GOLD.replace('"*Step, name=Step-2", "*Static", "*Cload, OP=NEW", "11, 2, -200.0"',
                        f'"*Step, name=Step-2", "*Static", "*Cload, OP=NEW", "11, 2, {step2_load}"')


SAME_LOAD = _variant("-100.0", "same load")
ACCUMULATED = _variant("-300.0", "accumulated load")

SWAP = r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/summary.txt")
a, b = [x.strip() for x in p.read_text().strip().split(",")]
p.write_text(f"{b}, {a}\n")
PYEOF
"""

ONE_STEP = r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/solution.inp")
text = p.read_text()
cut = text.index("*Step, name=Step-2")
p.write_text(text[:cut])
PYEOF
"""

CASES = [
    ("P1 positive (gold, two steps)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal encoding", ALT, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 step-2 load unchanged", SAME_LOAD, ("false",)),
    ("N3 load accumulated to -300 N", ACCUMULATED, ("false",)),
    ("N4 summary values swapped", GOLD + SWAP, ("false",)),
    ("N5 second step dropped", GOLD + ONE_STEP, ("false",)),
]
