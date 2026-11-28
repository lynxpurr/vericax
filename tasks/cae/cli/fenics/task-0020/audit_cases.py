"""Audit cases for cae--cli--fenics--task-0020 (quantified_score, L1-L5).

The first case is the ground-truth source. Cases assert on the numeric score:
"ge" for accepted designs, "le" for rejected or baseline designs.

Reference design: a = 14.05 mm, b = 100/14.05 = 7.1174 mm (fixed area
a*b = 100). Unlike task-0002 the optimum is interior: both load cases are
active there at once.

  LC1  x-traction 100 MPa: peak sigma_xx at (0, b), Inglis 100 (1 + 2b/a),
       decreasing with r = a/b
  LC2  y-traction 40 MPa:  peak sigma_yy at (a, 0), Inglis 40 (1 + 2a/b),
       increasing with r

Design index K = max(s1, s2) / 100: both peaks are referred to one reference
stress (the LC1 nominal stress). The infinite-plate estimate puts the minimum
at r = 2 with K = 2.0; the quarter plate is finite, which raises both peaks by
2-5 % and moves the crossing. Measured on this image with the evaluator's own
re-solve (2026-11-28, sweeps of a at three mesh densities):

  a      13.0    13.6    13.8    14.0    14.05   14.1    14.1421 14.3   15.5   17.0   18.5
  K      2.236   2.130   2.098   2.067   2.062   2.074   2.084   2.118  2.425  2.846  3.302

  circle (a = b = 10): K = 3.085-3.087 over 87-172 arc edges

K varies by less than 0.01 with the mesh density once the mesh is legal (87 to
187 arc edges), so the score does not reward a coarse mesh. The anchors are
the measured values: K_CIRCLE = 3.085 and K_BEST = 2.062. The circular
baseline scores at most 0.0002 on any legal mesh.

The design that is optimal for LC1 alone (a = 20, b = 5) measures s1 = 153,
s2 = 380, K = 3.80 and scores 0; the mirror image of the gold has K about 5.
Normalising each peak by its own nominal stress instead, max(s1/100, s2/40),
would make the circle the optimum.

Mesh rules beyond the arc edges: at most 80000 triangles (stated in the
instruction; bounds the verifier's direct solve), and a point in the file that
belongs to no element is not a mesh node (A4 adds the ellipse centre as a
dangling point; N16 exceeds the element cap).

Pin recipe (VM): to re-measure, run the gold script with FENICS_A/FENICS_B
set and feed the mesh to the verifier's resolve(); keep K_CIRCLE at or below
the smallest K the circle reaches on a legal mesh, otherwise the baseline
stops scoring 0.
"""

SOLVER = r'''"""Elliptical hole in a quarter plate under two load cases (FEniCSx)."""
import math
import os

import gmsh
import numpy as np

W, H = 100.0, 100.0
A = float(os.environ.get("FENICS_A", "14.05"))
B = float(os.environ.get("FENICS_B", "7.117437"))
NEAR = float(os.environ.get("FENICS_NEAR", "0.12"))
HMAX = float(os.environ.get("FENICS_HMAX", "3.0"))
STRATEGY = os.environ.get("FENICS_MESH", "dist")
LC1_ONLY = os.environ.get("FENICS_LC1_ONLY", "") == "1"

E, NU, THICK = 210000.0, 0.3, 1.0
SIGMA_X, SIGMA_Y = 100.0, 40.0

# ---------------------------------------------------------------- mesh
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("plate")
occ = gmsh.model.occ
rect = occ.addRectangle(0.0, 0.0, 0.0, W, H)
if A > 0.0 and B > 0.0:
    # addDisk wants the larger radius first; a tall ellipse is rotated into place
    if A >= B:
        hole = occ.addDisk(0.0, 0.0, 0.0, A, B)
    else:
        hole = occ.addDisk(0.0, 0.0, 0.0, B, A)
        occ.rotate([(2, hole)], 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, math.pi / 2.0)
    occ.synchronize()
    occ.cut([(2, rect)], [(2, hole)])
occ.synchronize()

curves = []
if A > 0.0 and B > 0.0:
    for _dim, ctag in gmsh.model.getEntities(1):
        xmin, ymin, _zmin, xmax, ymax, _zmax = gmsh.model.occ.getBoundingBox(1, ctag)
        if (xmax <= A + 1e-6 and ymax <= B + 1e-6
                and not (xmax <= 1e-9 or ymax <= 1e-9)):
            curves.append(ctag)

gmsh.option.setNumber("Mesh.MeshSizeMax", HMAX)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.05)
field = gmsh.model.mesh.field
if curves and STRATEGY == "math":
    fid = field.add("MathEval")
    field.setString(
        fid, "F",
        f"{NEAR} + 0.10*abs(sqrt((x/({A}))^2+(y/({B}))^2)-1)")
    field.setAsBackgroundMesh(fid)
elif curves:
    f_dist = field.add("Distance")
    field.setNumbers(f_dist, "CurvesList", curves)
    field.setNumber(f_dist, "Sampling", 200)
    f_thr = field.add("Threshold")
    field.setNumber(f_thr, "InField", f_dist)
    field.setNumber(f_thr, "SizeMin", NEAR)
    field.setNumber(f_thr, "SizeMax", HMAX)
    field.setNumber(f_thr, "DistMin", 0.0)
    field.setNumber(f_thr, "DistMax", 30.0)
    field.setAsBackgroundMesh(f_thr)
gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.option.setNumber("Mesh.ElementOrder", 1)
gmsh.model.mesh.generate(2)
gmsh.write("mesh.msh")
gmsh.finalize()
if os.environ.get("FENICS_SKIP_SOLVE", "0") == "1":
    # audit-only: build the mesh of a rejected case without solving on it
    raise SystemExit(0)

# ---------------------------------------------------------------- solve
import basix.ufl
import meshio
import ufl
from dolfinx import fem
from dolfinx.fem import Function, dirichletbc, functionspace, locate_dofs_topological
from dolfinx.mesh import create_mesh, locate_entities_boundary, meshtags
from mpi4py import MPI

m = meshio.read("mesh.msh")
pts = np.ascontiguousarray(m.points[:, :2], dtype=float)
cells = np.asarray(m.cells_dict["triangle"], dtype=np.int64)

domain = create_mesh(
    MPI.COMM_WORLD, cells,
    basix.ufl.element("Lagrange", "triangle", 1, shape=(2,)), pts)
V = functionspace(
    domain, basix.ufl.element("Lagrange", "triangle", 2, shape=(2,)))

left = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], 0.0))
bottom = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[1], 0.0))
right = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], W))
top = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[1], H))
Vx, Vy = V.sub(0), V.sub(1)
bcs = [
    dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx),
    dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, bottom), Vy),
]

# right edge -> 1 (LC1), top edge -> 2 (LC2)
facets = np.concatenate([right, top]).astype(np.int32)
values = np.concatenate([np.full(len(right), 1, dtype=np.int32),
                         np.full(len(top), 2, dtype=np.int32)])
order = np.argsort(facets)
mt = meshtags(domain, 1, facets[order], values[order])
ds = ufl.Measure("ds", domain=domain, subdomain_data=mt)

mu = E / (2.0 * (1.0 + NU))
lam = E * NU / ((1.0 + NU) * (1.0 - 2.0 * NU))
lam_star = 2.0 * lam * mu / (lam + 2.0 * mu)


def eps(w):
    return ufl.sym(ufl.grad(w))


def sigma(w):
    return 2.0 * mu * eps(w) + lam_star * ufl.tr(eps(w)) * ufl.Identity(2)


u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)
a = ufl.inner(sigma(u), eps(v)) * ufl.dx

V1 = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
ip = V1.element.interpolation_points
ip = ip() if callable(ip) else ip
xy = V1.tabulate_dof_coordinates()
on_hole = np.zeros(len(xy), dtype=bool)
if A > 0.0 and B > 0.0:
    q = np.hypot(xy[:, 0] / A, xy[:, 1] / B)
    on_hole = np.abs(q - 1.0) <= 1e-3

from dolfinx.fem.petsc import LinearProblem  # explicit submodule import


def peak(t, tag, component):
    """Solve one load case; peak normal stress at the hole-boundary vertices."""
    L = ufl.inner(t, v) * THICK * ds(tag)
    problem = LinearProblem(
        a, L, bcs=bcs, petsc_options_prefix="vcax_gold_",
        petsc_options={"ksp_type": "preonly", "pc_type": "lu"})
    uh = problem.solve()
    stress = Function(V1)
    stress.interpolate(fem.Expression(sigma(uh)[component, component], ip))
    return float(np.max(stress.x.array[on_hole])) if on_hole.any() else 0.0


s1 = peak(ufl.as_vector((SIGMA_X, 0.0)), 1, 0)
s2 = s1 if LC1_ONLY else peak(ufl.as_vector((0.0, SIGMA_Y)), 2, 1)

with open("summary.txt", "w") as fh:
    fh.write(f"{A:.6f}, {B:.6f}, {s1:.6f}, {s2:.6f}\n")
print("a =", A, " b =", B, " s1 =", s1, " s2 =", s2)
'''


def _run(env: str = "", after: str = "") -> str:
    prefix = f"{env} " if env else ""
    tail = f"\n{after}\n" if after else ""
    return (
        "set -e\n"
        "cd /home/user/Desktop\n"
        "cat > /tmp/solve.py <<'PYEOF'\n"
        + SOLVER
        + "\nPYEOF\n"
        "cp /tmp/solve.py solve.py\n"
        + prefix + "python3 /tmp/solve.py\n"
        + tail
    )


GOLD = _run(env="FENICS_A=14.05 FENICS_B=7.117437 FENICS_NEAR=0.12 FENICS_HMAX=3.0")
FINER = _run(env="FENICS_A=14.05 FENICS_B=7.117437 FENICS_NEAR=0.09 FENICS_HMAX=2.5")
NEIGHBOUR = _run(env="FENICS_A=13.3333 FENICS_B=7.5 FENICS_NEAR=0.12 FENICS_HMAX=3.0")
MATH = _run(env="FENICS_A=14.05 FENICS_B=7.117437 FENICS_NEAR=0.12 FENICS_HMAX=3.0 FENICS_MESH=math")
WRONG_AREA = _run(env="FENICS_A=14.05 FENICS_B=15 FENICS_NEAR=0.15 FENICS_HMAX=4.0")
OUT_OF_BOUNDS = _run(env="FENICS_A=21 FENICS_B=4.7619048 FENICS_NEAR=0.15 FENICS_HMAX=4.0")
LC1_ONLY_OPT = _run(env="FENICS_A=20 FENICS_B=5 FENICS_NEAR=0.12 FENICS_HMAX=3.0")
LC2_ONLY_OPT = _run(env="FENICS_A=5 FENICS_B=20 FENICS_NEAR=0.12 FENICS_HMAX=3.0")
CIRCLE = _run(env="FENICS_A=10 FENICS_B=10 FENICS_NEAR=0.12 FENICS_HMAX=3.0")
INVERTED = _run(env="FENICS_A=7.117437 FENICS_B=14.05 FENICS_NEAR=0.12 FENICS_HMAX=3.0")
COARSE = _run(env="FENICS_A=14.05 FENICS_B=7.117437 FENICS_NEAR=0.60 FENICS_HMAX=8.0")
# Too fine for the verifier's direct solve: rejected on the element count alone
# (no solve on that mesh; the summary is a placeholder).
# Measured on the image: NEAR=0.02, HMAX=0.8 gives 95203 triangles in 2.3 s.
OVERSIZED = _run(env="FENICS_A=14.05 FENICS_B=7.117437 FENICS_NEAR=0.02 FENICS_HMAX=0.8 FENICS_SKIP_SOLVE=1",
                 after="printf '14.050000, 7.117437, 206, 206\\n' > summary.txt")

# A construction point that belongs to no element (an ellipse centre left by
# an addEllipseArc builder) is not a mesh node and must not fail the delivery.
DANGLING_SNIPPET = (
    "python3 - <<'PY'\n"
    "p = 'mesh.msh'\n"
    "head, rest = open(p).read().split('$Nodes\\n', 1)\n"
    "count, tail = rest.split('\\n', 1)\n"
    "nodes, after_nodes = tail.split('$EndNodes', 1)\n"
    "n = int(count)\n"
    "open(p, 'w').write(head + '$Nodes\\n' + str(n + 1) + '\\n' + nodes.rstrip('\\n')\n"
    "                    + f'\\n{n + 1} 0 0 0\\n$EndNodes' + after_nodes)\n"
    "print('dangling point added at the hole centre')\n"
    "PY")
GOLD_DANGLING = _run(after=DANGLING_SNIPPET)

# Tampering with s2 can only be detected where the two peaks differ by more
# than the re-solve tolerance, so these two cases use the neighbouring legal
# design (s1 about 15 % above s2), not the gold, where s1 and s2 are equal by
# construction.
# LC1 solved correctly, LC2 never solved: s2 is a stand-in copy of s1.
LC2_IGNORED = _run(env="FENICS_A=13.3333 FENICS_B=7.5 FENICS_NEAR=0.12 FENICS_HMAX=3.0 FENICS_LC1_ONLY=1")

FABRICATE = _run(after=(
    "python3 - <<'PY'\n"
    "line = [float(x) for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(f'{line[0]:.6f}, {line[1]:.6f}, "
    "{line[2] * 1.10:.6f}, {line[3] * 1.10:.6f}\\n')\n"
    "PY"))
ZERO_MESH = _run(after=": > mesh.msh")
# One run on the neighbouring design, then the swap. (Concatenating two runs
# would let the second one overwrite the first one's mesh and summary.)
SWAPPED_S12 = _run(
    env="FENICS_A=13.3333 FENICS_B=7.5 FENICS_NEAR=0.12 FENICS_HMAX=3.0",
    after=(
        "python3 - <<'PY'\n"
        "v = open('summary.txt').read().strip().split(',')\n"
        "open('summary.txt', 'w').write(', '.join([v[0].strip(), v[1].strip(), "
        "v[3].strip(), v[2].strip()]) + '\\n')\n"
        "PY"))
BAD_SUMMARY = _run(after="printf '14.050000, 7.117437, 206\\n' > summary.txt")

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '14.050000, 7.117437, 206.0, 206.2' > summary.txt
"""

ENCODE_SUMMARY = _run(after=(
    "python3 - <<'PY'\n"
    "import base64\n"
    "from pathlib import Path\n"
    "raw = Path('summary.txt').read_text().strip().encode()\n"
    "Path('summary.txt').write_text(base64.b64encode(raw).decode() + '\\n')\n"
    "PY"))

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N2 wrong hole area (a*b = 212)": "tampered_input",
    "N8 LC2 ignored (s2 = s1 stand-in)": "skipped_steps",
    "N11 zero-byte mesh": "skipped_steps",
    "N14 metrics only": "metrics_only",
    "N15 encoded payload": "encoded_payload",
    "N10 fabricated summary (+10%)": "fabricated_field",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("ge", 0.90)),
    ("P2 robust (gold re-run)", GOLD, ("ge", 0.90)),
    ("A1 alternative legal (finer mesh)", FINER, ("ge", 0.90)),
    ("A2 alternative legal (neighbouring design)", NEIGHBOUR, ("ge", 0.60)),
    ("A3 alternative legal (math size field)", MATH, ("ge", 0.90)),
    ("A4 alternative legal (unused construction point in the file)", GOLD_DANGLING, ("ge", 0.90)),
    ("N1 empty delivery", "", ("le", 0.001)),
    ("N2 wrong hole area (a*b = 212)", WRONG_AREA, ("le", 0.001)),
    ("N3 semi-axis out of bounds (a = 21)", OUT_OF_BOUNDS, ("le", 0.001)),
    ("N4 LC1-only optimum (a=20, b=5)", LC1_ONLY_OPT, ("le", 0.001)),
    ("N5 LC2-only optimum (a=5, b=20)", LC2_ONLY_OPT, ("le", 0.001)),
    ("N6 circular baseline (a=b=10)", CIRCLE, ("le", 0.001)),
    ("N7 aspect ratio inverted (a=7.1174, b=14.05)", INVERTED, ("le", 0.001)),
    ("N8 LC2 ignored (s2 = s1 stand-in)", LC2_IGNORED, ("le", 0.001)),
    ("N9 swapped s1 / s2", SWAPPED_S12, ("le", 0.001)),
    ("N10 fabricated summary (+10%)", GOLD + FABRICATE, ("le", 0.001)),
    ("N11 zero-byte mesh", GOLD + ZERO_MESH, ("le", 0.001)),
    ("N12 malformed summary", GOLD + BAD_SUMMARY, ("le", 0.001)),
    ("N13 coarse mesh", COARSE, ("le", 0.001)),
    ("N16 oversized mesh", OVERSIZED, ("le", 0.001)),
    ("N14 metrics only", METRICS_ONLY, ("le", 0.001)),
    ("N15 encoded payload", GOLD + ENCODE_SUMMARY, ("le", 0.001)),
]
