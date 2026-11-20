"""Audit cases for cae--cli--calculix--task-0010 (beam vs solid).

The first case is the ground-truth source. The same cantilever is delivered as
a B31 beam and a C3D8 solid; the verifier requires both to agree.
"""

BASE = r"""
set -e
cd /home/user/Desktop
export ORDER=__ORDER__
export SOLID_ELSETS=__SOLID_ELSETS__
export BEAM_REVERSE=__BEAM_REVERSE__
python3 - <<'PYEOF'
import os
from pathlib import Path

order = os.environ["ORDER"]
solid_elsets = os.environ["SOLID_ELSETS"] == "1"
beam_reverse = os.environ["BEAM_REVERSE"] == "1"

# ---------------- beam deck
n = 10
beam = ["*Heading", "VeriCAX task-0010 beam model", "*Node"]
ids = range(n + 1, 0, -1) if beam_reverse else range(1, n + 2)
for i in ids:
    beam.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
beam.append("*Element, type=B31, elset=AllElems")
for e in range(1, n + 1):
    beam.append(f"{e}, {e}, {e + 1}")
beam += ["*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
         "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
         "*Beam Section, elset=AllElems, material=Steel, section=RECT", "10.0, 10.0",
         "*Boundary", "1, 1, 6, 0.0",
         "*Step", "*Static", "*Cload", "11, 2, -100.0",
         "*Node Print, NSET=All_Nodes", "U", "*End Step", ""]
Path("beam.inp").write_text("\n".join(beam))

# ---------------- solid deck
nx, ny, nz = 40, 4, 4
L, W, H = 100.0, 10.0, 10.0
dx, dy, dz = L / nx, W / ny, H / nz


def nid(i, j, k):
    if order == "i":
        return (j * (nz + 1) + k) * (nx + 1) + i + 1
    return (i * (ny + 1) + j) * (nz + 1) + k + 1


def wrap(ids, per=16):
    ids = list(ids)
    return "\n".join(", ".join(str(v) for v in ids[i:i + per])
                     for i in range(0, len(ids), per))


solid = ["*Heading", "VeriCAX task-0010 solid model", "*Node"]
for i in range(nx + 1):
    for j in range(ny + 1):
        for k in range(nz + 1):
            solid.append(f"{nid(i,j,k)}, {dx*i:.6f}, {dy*j:.6f}, {dz*k:.6f}")
if solid_elsets:
    solid.append("*Element, type=C3D8")
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                e = (i * ny + j) * nz + k + 1
                solid.append(
                    f"{e}, {nid(i,j,k)}, {nid(i+1,j,k)}, {nid(i+1,j+1,k)}, {nid(i,j+1,k)}, "
                    f"{nid(i,j,k+1)}, {nid(i+1,j,k+1)}, {nid(i+1,j+1,k+1)}, {nid(i,j+1,k+1)}")
    solid += ["*Elset, elset=Eall", wrap(range(1, nx * ny * nz + 1))]
else:
    solid.append("*Element, type=C3D8, elset=Eall")
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                e = (i * ny + j) * nz + k + 1
                solid.append(
                    f"{e}, {nid(i,j,k)}, {nid(i+1,j,k)}, {nid(i+1,j+1,k)}, {nid(i,j+1,k)}, "
                    f"{nid(i,j,k+1)}, {nid(i+1,j,k+1)}, {nid(i+1,j+1,k+1)}, {nid(i,j+1,k+1)}")
left = [nid(0, j, k) for j in range(ny + 1) for k in range(nz + 1)]
tip = [nid(nx, j, k) for j in range(ny + 1) for k in range(nz + 1)]
center = nid(nx, ny // 2, nz // 2)
solid += ["*Nset, nset=Left", wrap(left), "*Nset, nset=Tip", wrap(tip),
          "*Nset, nset=Center", str(center),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Solid Section, elset=Eall, material=Steel",
          "*Boundary", "Left, 1, 3, 0.0",
          "*Step", "*Static", "*Cload"]
each = -100.0 / len(tip)
for node in tip:
    solid.append(f"{node}, 2, {each:.10f}")
solid += ["*Node Print, NSET=Center", "U", "*End Step", ""]
Path("solid.inp").write_text("\n".join(solid))
PYEOF
/usr/bin/ccx beam > /tmp/ccx-beam.log 2>&1 || { tail -20 /tmp/ccx-beam.log; exit 1; }
/usr/bin/ccx solid > /tmp/ccx-solid.log 2>&1 || { tail -20 /tmp/ccx-solid.log; exit 1; }
python3 - <<'PYEOF'
import os, re
from pathlib import Path


def field(dat, node):
    u, head = {}, None
    for raw in Path(dat).read_text(errors="ignore").splitlines():
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
    return u[node]


uy_beam = field("beam.dat", 11)[1]
nodes = {}
for raw in Path("solid.inp").read_text().splitlines():
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
uy_solid = field("solid.dat", center)[1]
Path("summary.txt").write_text(f"{uy_beam!r}, {uy_solid!r}\n")
PYEOF
"""


def make(order="k", solid_elsets=0, beam_reverse=0) -> str:
    return (BASE.replace("__ORDER__", order)
                .replace("__SOLID_ELSETS__", str(solid_elsets))
                .replace("__BEAM_REVERSE__", str(beam_reverse)))


GOLD = make()
ALT = make(order="i", solid_elsets=1, beam_reverse=1)
ALT2 = make(solid_elsets=1)
WRONG_SOLID_LOAD = GOLD + r"""
sed -i 's/-4.0000000000/-3.2000000000/g' /home/user/Desktop/solid.inp
"""
WRONG_BEAM_SECTION = GOLD + r"""
sed -i 's/10.0, 10.0/12.0, 10.0/' /home/user/Desktop/beam.inp
"""
WRONG_BEAM_LOAD = GOLD + r"""
sed -i 's/11, 2, -100.0/11, 2, -80.0/' /home/user/Desktop/beam.inp
"""
MISSING_SOLID = GOLD + r"""
rm -f /home/user/Desktop/solid.inp
"""

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in Path("/home/user/Desktop/summary.txt").read_text().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(f"{v[0] * 1.10!r}, {v[1] * 1.10!r}\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solid.dat\n"

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.191155, -0.18377' > summary.txt
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
    "N2 solid load tampered": "tampered_input",
    "N7 fabricated summary (+10%)": "fabricated_field",
    "N8 zero-byte solid output": "skipped_steps",
    "N9 metrics only": "metrics_only",
    "N10 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (solid i-fastest, beam reversed)", ALT, ("true",)),
    ("A2 alternative legal (solid elset cards)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 solid load tampered", WRONG_SOLID_LOAD, ("false",)),
    ("N3 beam section tampered", WRONG_BEAM_SECTION, ("false",)),
    ("N4 beam load tampered", WRONG_BEAM_LOAD, ("false",)),
    ("N5 missing solid deck", MISSING_SOLID, ("false",)),
    ("N6 beam/solid inconsistency", WRONG_SOLID_LOAD, ("false",)),
    ("N7 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N8 zero-byte solid output", ZERO_DAT, ("false",)),
    ("N9 metrics only", METRICS_ONLY, ("false",)),
    ("N10 encoded payload", ENCODE_SUMMARY, ("false",)),
]