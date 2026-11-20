"""Audit cases for cae--cli--calculix--task-0004 (exact_match, L1-L3).

The first case is the ground-truth source. Plane-strain thick cylinder
(ri=10, ro=20) under 50 MPa internal pressure; the reported quantities are the
radial displacements of the inner and outer surfaces.
"""

BASE = r"""
set -e
cd /home/user/Desktop
export NRAD=__NRAD__
export RI=__RI__
export REVERSE=__REVERSE__
export ELSETS=__ELSETS__
python3 - <<'PYEOF'
import os
from pathlib import Path

nrad = int(os.environ["NRAD"])
ri = float(os.environ["RI"])
ro = 20.0
reverse = os.environ["REVERSE"] == "1"
elset_cards = os.environ["ELSETS"] == "1"
dz = 1.0
dr = (ro - ri) / nrad


def wrap(ids, per=16):
    ids = list(ids)
    return "\n".join(", ".join(str(v) for v in ids[i:i + per])
                     for i in range(0, len(ids), per))


def nid(i, j):
    return (i * 2 + j + 1) if not reverse else ((nrad - i) * 2 + j + 1)


lines = ["*Heading", "VeriCAX task-0004 reference solution", "*Node"]
for i in range(nrad + 1):
    r = ri + dr * i
    for j in range(2):
        lines.append(f"{nid(i,j)}, {r:.6f}, {dz*j:.6f}, 0.0")

if elset_cards:
    lines.append("*Element, type=CAX4")
    for i in range(nrad):
        e = i + 1
        lines.append(f"{e}, {nid(i,0)}, {nid(i+1,0)}, {nid(i+1,1)}, {nid(i,1)}")
    lines += ["*Elset, elset=Eall", wrap(range(1, nrad + 1)),
              "*Elset, elset=Inner", "1"]
    sec_elset = "Eall"
    load_elset = "Inner"
else:
    lines.append("*Element, type=CAX4, elset=Eall")
    for i in range(nrad):
        e = i + 1
        lines.append(f"{e}, {nid(i,0)}, {nid(i+1,0)}, {nid(i+1,1)}, {nid(i,1)}")
    lines.append("*Elset, elset=Inner")
    lines.append("1")
    sec_elset = "Eall"
    load_elset = "Inner"

all_nodes = [nid(i, j) for i in range(nrad + 1) for j in range(2)]
inner_nodes = [nid(0, j) for j in range(2)]
outer_nodes = [nid(nrad, j) for j in range(2)]
lines += ["*Nset, nset=AxialFix", wrap(all_nodes),
          "*Nset, nset=InnerNodes", wrap(inner_nodes),
          "*Nset, nset=OuterNodes", wrap(outer_nodes),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          f"*Solid Section, elset={sec_elset}, material=Steel",
          "*Boundary", "AxialFix, 2, 2, 0.0",
          "*Step", "*Static", "*Dload",
          f"{load_elset}, P4, 50.0",
          "*Node Print, NSET=InnerNodes", "U",
          "*Node Print, NSET=OuterNodes", "U",
          "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import os
from pathlib import Path
import re

nrad = int(os.environ["NRAD"])
reverse = os.environ["REVERSE"] == "1"
inner_id = (nrad * 2 + 1) if reverse else 1
outer_id = 1 if reverse else (nrad * 2 + 1)

dat = Path("solution.dat").read_text(errors="ignore")
u, head = {}, None
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
            u[int(p[0])] = float(p[1])
        except (ValueError, IndexError):
            pass
assert inner_id in u and outer_id in u, "parse failed"
Path("summary.txt").write_text(f"{u[inner_id]}, {u[outer_id]}\n")
PYEOF
"""


def make(nrad=20, ri=10.0, reverse=0, elsets=0) -> str:
    return (BASE.replace("__NRAD__", str(nrad))
                .replace("__RI__", repr(ri))
                .replace("__REVERSE__", str(reverse))
                .replace("__ELSETS__", str(elsets)))


GOLD = make()
# Legal alternative: reversed node ids, separate elset cards, no BC value.
ALT = make(reverse=1, elsets=1)
# Legal alternative: same mesh, pressure applied through an explicit elset card
# and the integer load form; node ids unchanged (different element order).
ALT2 = make(elsets=1)

# Wrong pressure (keeps the gold summary -> A vs B mismatch).
WRONG_PRESSURE = GOLD + r"""
sed -i 's/Inner, P4, 50.0/Inner, P4, 40.0/' /home/user/Desktop/solution.inp
"""

# Pressure applied to the outer surface instead of the inner one.
OUTER_PRESSURE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/solution.inp")
p.write_text(p.read_text().replace("Inner, P4, 50.0", "Eall, P4, 50.0"))
PYEOF
"""

# Wrong material (L2 must reject).
WRONG_MATERIAL = GOLD + r"""
sed -i 's/210000.0, 0.3/70000.0, 0.3/' /home/user/Desktop/solution.inp
"""

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in Path("/home/user/Desktop/summary.txt").read_text().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(f"{v[0] * 1.10}, {v[1] * 1.10}\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

COARSE = make(nrad=10)

WRONG_RADIUS = make(ri=8.0)

# Only the metrics, no deck or solver output (kind: metrics_only).
METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '0.00454, 0.00293' > summary.txt
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
    "N2 pressure tampered": "tampered_input",
    "N5 fabricated summary (+10%)": "fabricated_field",
    "N6 zero-byte solver output": "skipped_steps",
    "N7 metrics only": "metrics_only",
    "N8 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (reversed ids, elset cards)", ALT, ("true",)),
    ("A2 alternative legal (explicit elset cards)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 pressure tampered", WRONG_PRESSURE, ("false",)),
    ("N3 pressure on outer surface", OUTER_PRESSURE, ("false",)),
    ("N4 wrong material", WRONG_MATERIAL, ("false",)),
    ("N5 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N6 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N7 metrics only", METRICS_ONLY, ("false",)),
    ("N8 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N9 coarse mesh (10 elements)", COARSE, ("false",)),
    ("N10 wrong inner radius", WRONG_RADIUS, ("false",)),
]