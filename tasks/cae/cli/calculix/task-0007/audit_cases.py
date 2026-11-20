"""Audit cases for cae--cli--calculix--task-0007 (exact_match, L1-L3).

The first case is the ground-truth source. 3D cantilever block (100 x 10 x 10
mm, 40 x 4 x 4 C3D8 elements), clamped at x=0, -100 N tip load in y.
"""

BASE = r"""
set -e
cd /home/user/Desktop
export NX=__NX__
export NY=__NY__
export NZ=__NZ__
export ORDER=__ORDER__
export ELSETS=__ELSETS__
export LOAD=__LOAD__
export CLAMP=__CLAMP__
export LENGTH=__LENGTH__
export ELASTIC="__ELASTIC__"
python3 - <<'PYEOF'
import os
from pathlib import Path

nx, ny, nz = int(os.environ["NX"]), int(os.environ["NY"]), int(os.environ["NZ"])
order = os.environ["ORDER"]
elset_cards = os.environ["ELSETS"] == "1"
load_total = float(os.environ["LOAD"])
clamp_mode = os.environ["CLAMP"]
length = float(os.environ["LENGTH"])
elastic = os.environ["ELASTIC"]
L, W, H = length, 10.0, 10.0
dx, dy, dz = L / nx, W / ny, H / nz


def nid(i, j, k):
    if order == "i":
        return (j * (nz + 1) + k) * (nx + 1) + i + 1
    return (i * (ny + 1) + j) * (nz + 1) + k + 1


def wrap(ids, per=16):
    ids = list(ids)
    return "\n".join(", ".join(str(v) for v in ids[i:i + per])
                     for i in range(0, len(ids), per))


lines = ["*Heading", "VeriCAX task-0007 reference solution", "*Node"]
for i in range(nx + 1):
    for j in range(ny + 1):
        for k in range(nz + 1):
            lines.append(f"{nid(i,j,k)}, {dx*i:.6f}, {dy*j:.6f}, {dz*k:.6f}")

if elset_cards:
    lines.append("*Element, type=C3D8")
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                e = (i * ny + j) * nz + k + 1
                lines.append(
                    f"{e}, {nid(i,j,k)}, {nid(i+1,j,k)}, {nid(i+1,j+1,k)}, {nid(i,j+1,k)}, "
                    f"{nid(i,j,k+1)}, {nid(i+1,j,k+1)}, {nid(i+1,j+1,k+1)}, {nid(i,j+1,k+1)}")
    lines += ["*Elset, elset=Eall", wrap(range(1, nx * ny * nz + 1))]
    sec_elset = "Eall"
else:
    lines.append("*Element, type=C3D8, elset=Eall")
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                e = (i * ny + j) * nz + k + 1
                lines.append(
                    f"{e}, {nid(i,j,k)}, {nid(i+1,j,k)}, {nid(i+1,j+1,k)}, {nid(i,j+1,k)}, "
                    f"{nid(i,j,k+1)}, {nid(i+1,j,k+1)}, {nid(i+1,j+1,k+1)}, {nid(i,j+1,k+1)}")
    sec_elset = "Eall"

left = [nid(0, j, k) for j in range(ny + 1) for k in range(nz + 1)]
tip = [nid(nx, j, k) for j in range(ny + 1) for k in range(nz + 1)]
if clamp_mode == "partial":
    left = left[:10]
center = nid(nx, ny // 2, nz // 2)
lines += ["*Nset, nset=Left", wrap(left),
          "*Nset, nset=Tip", wrap(tip),
          "*Nset, nset=Center", str(center),
          "*Material, name=Steel", "*Elastic", elastic,
          f"*Solid Section, elset={sec_elset}, material=Steel",
          "*Boundary", "Left, 1, 3, 0.0",
          "*Step", "*Static", "*Cload"]
each = load_total / len(tip)
for n in tip:
    lines.append(f"{n}, 2, {each:.10f}")
lines += ["*Node Print, NSET=Center", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path

nodes = {}
for raw in Path("solution.inp").read_text().splitlines():
    s = raw.strip()
    if not s or s.startswith('*'):
        continue
    p = s.split(',')
    if len(p) == 4:
        try:
            nodes[int(p[0])] = tuple(float(x) for x in p[1:])
        except ValueError:
            pass
center = next(n for n, (x, y, z) in nodes.items()
              if abs(x - 100.0) < 1e-6 and abs(y - 5.0) < 1e-6 and abs(z - 5.0) < 1e-6)

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
            u[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            pass
assert center in u, "parse failed"
Path("summary.txt").write_text(f"{u[center][1]}\n")
PYEOF
"""


def make(nx=40, ny=4, nz=4, order="k", elsets=0, load=-100.0,
         clamp="all", length=100.0, elastic="210000.0, 0.3") -> str:
    return (BASE.replace("__NX__", str(nx))
                .replace("__NY__", str(ny))
                .replace("__NZ__", str(nz))
                .replace("__ORDER__", order)
                .replace("__ELSETS__", str(elsets))
                .replace("__LOAD__", repr(load))
                .replace("__CLAMP__", clamp)
                .replace("__LENGTH__", repr(length))
                .replace("__ELASTIC__", elastic))


GOLD = make()
# Legal alternative: i-fastest node numbering and explicit elset cards.
ALT = make(order="i", elsets=1)
# Legal alternative: node order reversed by using i-fastest numbering with a
# separate element set and the same grid.
ALT2 = make(order="i")

WRONG_LOAD = make(load=-80.0)
PARTIAL_CLAMP = make(clamp="partial")
WRONG_MATERIAL = make(elastic="70000.0, 0.3")
COARSE = make(nx=20, ny=2, nz=2)
WRONG_LENGTH = make(length=90.0)

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = float(Path("/home/user/Desktop/summary.txt").read_text())
Path("/home/user/Desktop/summary.txt").write_text(f"{v * 1.10!r}\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.18377' > summary.txt
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
    "N2 tip load tampered": "tampered_input",
    "N5 fabricated summary (+10%)": "fabricated_field",
    "N6 zero-byte solver output": "skipped_steps",
    "N7 metrics only": "metrics_only",
    "N8 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (i-fastest ids, elset cards)", ALT, ("true",)),
    ("A2 alternative legal (i-fastest ids)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 tip load tampered", WRONG_LOAD, ("false",)),
    ("N3 partial clamp", PARTIAL_CLAMP, ("false",)),
    ("N4 wrong material", WRONG_MATERIAL, ("false",)),
    ("N5 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N6 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N7 metrics only", METRICS_ONLY, ("false",)),
    ("N8 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N9 coarse mesh (20x2x2)", COARSE, ("false",)),
    ("N10 wrong length", WRONG_LENGTH, ("false",)),
]