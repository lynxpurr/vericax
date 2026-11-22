"""Audit cases for cae--cli--fenics--task-0016 (open-environment, trimesh).

The agent installs trimesh from the local wheelhouse and measures the provided
square-tube STL (volume 840, surface area 728).
"""

INSTALL = r"""
set -e
cd /home/user/Desktop
python3 -m pip install --user --no-index --find-links wheels trimesh==5.2.1 scipy==1.13.1 >/dev/null 2>&1
"""

SOLVE = r'''import trimesh

mesh = trimesh.load("part.stl", force="mesh")
mesh.process(validate=True)
with open("summary.txt", "w") as fh:
    fh.write(f"{float(mesh.volume):.6f}, {float(mesh.area):.6f}\n")
'''


def _run(after: str = "") -> str:
    return (
        INSTALL
        + "cat > solve.py <<'PYEOF'\n"
        + SOLVE
        + "PYEOF\n"
        + "python3 solve.py\n"
        + (f"\n{after}\n" if after else "")
    )


GOLD = _run()

ALT = INSTALL + r"""
cat > solve.py <<'PYEOF'
import trimesh

mesh = trimesh.load("part.stl", force="mesh")
mesh.process(validate=True)
with open("summary.txt", "w") as fh:
    fh.write(f"{float(mesh.mass_properties['volume']):.6f}, {float(mesh.area):.6f}\n")
PYEOF
python3 solve.py
"""

ALT2 = INSTALL + r"""
cat > solve.py <<'PYEOF'
import trimesh

mesh = trimesh.load("part.stl", force="mesh")
mesh.fix_normals()
with open("summary.txt", "w") as fh:
    fh.write(f"{float(mesh.volume):.6f}, {float(mesh.area):.6f}\n")
PYEOF
python3 solve.py
"""

CONVEX = INSTALL + r"""
cat > solve.py <<'PYEOF'
import trimesh

mesh = trimesh.load("part.stl", force="mesh")
hull = mesh.convex_hull
with open("summary.txt", "w") as fh:
    fh.write(f"{float(hull.volume):.6f}, {float(hull.area):.6f}\n")
PYEOF
python3 solve.py
"""

NO_TRIMESH = r"""
set -e
cd /home/user/Desktop
cat > solve.py <<'PYEOF'
# hand-written values without installing a mesh library
with open("summary.txt", "w") as fh:
    fh.write("840.0, 728.0\n")
PYEOF
python3 solve.py
"""

MISSING_SCRIPT = GOLD + "\nrm -f /home/user/Desktop/solve.py\n"

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in Path("/home/user/Desktop/summary.txt").read_text().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(f"{v[0] * 1.10:.6f}, {v[1] * 1.10:.6f}\n")
PYEOF
"""

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '840.0, 728.0' > summary.txt
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
    "N2 convex hull fills the hole": "tampered_input",
    "N5 fabricated summary (+10%)": "fabricated_field",
    "N4 missing solve.py": "skipped_steps",
    "N6 metrics only": "metrics_only",
    "N7 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (mass_properties)", ALT, ("true",)),
    ("A2 alternative legal (fix_normals)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 convex hull fills the hole", CONVEX, ("false",)),
    ("N3 hand-written summary without trimesh", NO_TRIMESH, ("false",)),
    ("N4 missing solve.py", MISSING_SCRIPT, ("false",)),
    ("N5 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N6 metrics only", METRICS_ONLY, ("false",)),
    ("N7 encoded payload", ENCODE_SUMMARY, ("false",)),
]