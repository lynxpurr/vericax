"""Audit cases for cae--cli--calculix--task-0009 (exact_match, L4 chain).

Two decks solve the same 3D cantilever on a coarse (20x2x2) and a fine
(40x4x4) C3D8 mesh. The verifier checks both decks, re-runs both, and requires
the fine result to be closer to beam theory while the two stay in one band.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

L, W, H = 100.0, 10.0, 10.0
LOAD = -100.0


def wrap(ids, per=16):
    ids = list(ids)
    return "\n".join(", ".join(str(v) for v in ids[i:i + per])
                     for i in range(0, len(ids), per))


def build(nx, ny, nz, order, elsets, tag):
    dx, dy, dz = L / nx, W / ny, H / nz

    def nid(i, j, k):
        if order == "i":
            return (j * (nz + 1) + k) * (nx + 1) + i + 1
        return (i * (ny + 1) + j) * (nz + 1) + k + 1

    lines = ["*Heading", f"VeriCAX task-0009 {tag}", "*Node"]
    for i in range(nx + 1):
        for j in range(ny + 1):
            for k in range(nz + 1):
                lines.append(f"{nid(i,j,k)}, {dx*i:.6f}, {dy*j:.6f}, {dz*k:.6f}")
    if elsets:
        lines.append("*Element, type=C3D8")
    else:
        lines.append("*Element, type=C3D8, elset=Eall")
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                e = (i * ny + j) * nz + k + 1
                lines.append(
                    f"{e}, {nid(i,j,k)}, {nid(i+1,j,k)}, {nid(i+1,j+1,k)}, {nid(i,j+1,k)}, "
                    f"{nid(i,j,k+1)}, {nid(i+1,j,k+1)}, {nid(i+1,j+1,k+1)}, {nid(i,j+1,k+1)}")
    if elsets:
        lines += ["*Elset, elset=Eall", wrap(range(1, nx * ny * nz + 1))]
    left = [nid(0, j, k) for j in range(ny + 1) for k in range(nz + 1)]
    tip = [nid(nx, j, k) for j in range(ny + 1) for k in range(nz + 1)]
    center = nid(nx, ny // 2, nz // 2)
    lines += ["*Nset, nset=Left", wrap(left),
              "*Nset, nset=Tip", wrap(tip),
              "*Nset, nset=Center", str(center),
              "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
              "*Solid Section, elset=Eall, material=Steel",
              "*Boundary", "Left, 1, 3, 0.0",
              "*Step", "*Static", "*Cload"]
    each = LOAD / len(tip)
    for n in tip:
        lines.append(f"{n}, 2, {each:.10f}")
    lines += ["*Node Print, NSET=Center", "U", "*End Step", ""]
    Path(f"{tag}.inp").write_text("\n".join(lines))


build(20, 2, 2, "k", 0, "coarse")
build(40, 4, 4, "k", 0, "fine")
PYEOF
/usr/bin/ccx coarse > /tmp/ccx-coarse.log 2>&1 || { tail -25 /tmp/ccx-coarse.log; exit 1; }
/usr/bin/ccx fine > /tmp/ccx-fine.log 2>&1 || { tail -25 /tmp/ccx-fine.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path


def center_uy(tag):
    nodes = {}
    for raw in Path(f"{tag}.inp").read_text().splitlines():
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
    dat = Path(f"{tag}.dat").read_text(errors="ignore")
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
    assert center in u, f"{tag} parse failed"
    return u[center][1]


Path("summary.txt").write_text(f"{center_uy('coarse')!r}, {center_uy('fine')!r}\n")
PYEOF
"""

# Legal alternative: i-fastest node numbering and explicit elset cards in both decks.
ALT = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
from pathlib import Path

L, W, H = 100.0, 10.0, 10.0
LOAD = -100.0


def wrap(ids, per=16):
    ids = list(ids)
    return "\n".join(", ".join(str(v) for v in ids[i:i + per])
                     for i in range(0, len(ids), per))


def build(nx, ny, nz, tag):
    dx, dy, dz = L / nx, W / ny, H / nz

    def nid(i, j, k):
        return (j * (nz + 1) + k) * (nx + 1) + i + 1

    lines = ["*Heading", f"alternative {tag}", "*Node"]
    for i in range(nx + 1):
        for j in range(ny + 1):
            for k in range(nz + 1):
                lines.append(f"{nid(i,j,k)}, {dx*i:.6f}, {dy*j:.6f}, {dz*k:.6f}")
    lines.append("*Element, type=C3D8")
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                e = (i * ny + j) * nz + k + 1
                lines.append(
                    f"{e}, {nid(i,j,k)}, {nid(i+1,j,k)}, {nid(i+1,j+1,k)}, {nid(i,j+1,k)}, "
                    f"{nid(i,j,k+1)}, {nid(i+1,j,k+1)}, {nid(i+1,j+1,k+1)}, {nid(i,j+1,k+1)}")
    lines += ["*Elset, elset=AllElems", wrap(range(1, nx * ny * nz + 1))]
    left = [nid(0, j, k) for j in range(ny + 1) for k in range(nz + 1)]
    tip = [nid(nx, j, k) for j in range(ny + 1) for k in range(nz + 1)]
    center = nid(nx, ny // 2, nz // 2)
    lines += ["*Nset, nset=Clamped", wrap(left),
              "*Nset, nset=Loaded", wrap(tip),
              "*Nset, nset=Mid", str(center),
              "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
              "*Solid Section, elset=AllElems, material=Steel",
              "*Boundary", "Clamped, 1, 3, 0.0",
              "*Step", "*Static", "*Cload"]
    each = LOAD / len(tip)
    for n in tip:
        lines.append(f"{n}, 2, {each:.10f}")
    lines += ["*Node Print, NSET=Mid", "U", "*End Step", ""]
    Path(f"{tag}.inp").write_text("\n".join(lines))


build(20, 2, 2, "coarse")
build(40, 4, 4, "fine")
PYEOF
/usr/bin/ccx coarse > /tmp/ccx-c1.log 2>&1 || { tail -25 /tmp/ccx-c1.log; exit 1; }
/usr/bin/ccx fine > /tmp/ccx-f1.log 2>&1 || { tail -25 /tmp/ccx-f1.log; exit 1; }
python3 - <<'PYEOF'
import re
from pathlib import Path


def center_uy(tag):
    nodes = {}
    for raw in Path(f"{tag}.inp").read_text().splitlines():
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
    dat = Path(f"{tag}.dat").read_text(errors="ignore")
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
    assert center in u
    return u[center][1]


Path("summary.txt").write_text(f"{center_uy('coarse')!r}, {center_uy('fine')!r}\n")
PYEOF
"""

ALT2 = ALT.replace("return (j * (nz + 1) + k) * (nx + 1) + i + 1",
                   "return (i * (ny + 1) + j) * (nz + 1) + k + 1")

SWAP = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = open("/home/user/Desktop/summary.txt").read().strip().split(",")
Path("/home/user/Desktop/summary.txt").write_text(", ".join([v[1].strip(), v[0].strip()]) + "\n")
PYEOF
"""

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in open("/home/user/Desktop/summary.txt").read().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(", ".join(repr(x * 1.10) for x in v) + "\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/fine.dat\n"

MISSING_FINE = GOLD + "\nrm -f /home/user/Desktop/fine.inp\n"

WRONG_FINE_LOAD = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
p = Path("/home/user/Desktop/fine.inp")
text = p.read_text()
p.write_text(text.replace("-4.0000000000", "-3.2000000000"))
PYEOF
"""

COARSE_AS_FINE = GOLD + r"""
cp /home/user/Desktop/coarse.inp /home/user/Desktop/fine.inp
cp /home/user/Desktop/coarse.dat /home/user/Desktop/fine.dat
"""

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.166801, -0.183770' > summary.txt
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
    "N2 fine load tampered": "tampered_input",
    "N6 fabricated summary (+10%)": "fabricated_field",
    "N7 zero-byte fine output": "skipped_steps",
    "N8 metrics only": "metrics_only",
    "N9 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (i-fastest ids)", ALT, ("true",)),
    ("A2 alternative legal (k-fastest ids, elset cards)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 fine load tampered", WRONG_FINE_LOAD, ("false",)),
    ("N3 swapped summary", SWAP, ("false",)),
    ("N4 coarse mesh used for fine", COARSE_AS_FINE, ("false",)),
    ("N5 missing fine deck", MISSING_FINE, ("false",)),
    ("N6 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N7 zero-byte fine output", ZERO_DAT, ("false",)),
    ("N8 metrics only", METRICS_ONLY, ("false",)),
    ("N9 encoded payload", ENCODE_SUMMARY, ("false",)),
]