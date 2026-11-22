"""Audit cases for cae--cli--fenics--task-0005 (quantified_score, L1-L5).

The first case is the ground-truth source. Cases assert on the numeric score:
"ge" for accepted designs, "le" for rejected or baseline designs.

Reference design: circular lightening hole R=6 mm at (40, 0) in a
100 x 20 mm cantilever. The tip deflection is 0.2596 mm, under the 0.27 mm
limit; the score is (36-4)/(6.4^2-4) = 0.866.
"""

SOLVER = r'''"""Cantilever with a circular lightening hole (FEniCSx)."""
import os

import gmsh
import numpy as np

L, W, THICK = 100.0, 20.0, 1.0
R = float(os.environ.get("FENICS_R", "6.0"))
HMAX = float(os.environ.get("FENICS_HMAX", "1.8"))
NEAR = float(os.environ.get("FENICS_NEAR", "0.35"))
STRATEGY = os.environ.get("FENICS_MESH", "dist")
E, NU, F = 210000.0, 0.3, 100.0

# ---------------------------------------------------------------- mesh
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("cantilever")
occ = gmsh.model.occ
rect = occ.addRectangle(0.0, -W / 2, 0.0, L, W)
if R > 0.0:
    disk = occ.addDisk(40.0, 0.0, 0.0, R, R)
    occ.synchronize()
    occ.cut([(2, rect)], [(2, disk)])
occ.synchronize()

gmsh.option.setNumber("Mesh.MeshSizeMax", HMAX)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.15)
field = gmsh.model.mesh.field
if R > 0.0 and STRATEGY == "math":
    fid = field.add("MathEval")
    field.setString(fid, "F", f"{NEAR} + 0.10*(sqrt((x-40)^2+y^2) - {R})")
    field.setAsBackgroundMesh(fid)
elif R > 0.0:
    curves = []
    for _dim, ctag in gmsh.model.getEntities(1):
        xmin, ymin, _zmin, xmax, ymax, _zmax = gmsh.model.occ.getBoundingBox(1, ctag)
        if (xmin >= 40 - R - 1e-6 and xmax <= 40 + R + 1e-6
                and ymin >= -R - 1e-6 and ymax <= R + 1e-6):
            curves.append(ctag)
    f_dist = field.add("Distance")
    field.setNumbers(f_dist, "CurvesList", curves)
    field.setNumber(f_dist, "Sampling", 200)
    f_thr = field.add("Threshold")
    field.setNumber(f_thr, "InField", f_dist)
    field.setNumber(f_thr, "SizeMin", NEAR)
    field.setNumber(f_thr, "SizeMax", HMAX)
    field.setNumber(f_thr, "DistMin", 0.0)
    field.setNumber(f_thr, "DistMax", 15.0)
    field.setAsBackgroundMesh(f_thr)
gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.model.mesh.generate(2)
gmsh.write("mesh.msh")
gmsh.finalize()

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
domain = create_mesh(MPI.COMM_WORLD, cells,
                     basix.ufl.element("Lagrange", "triangle", 1, shape=(2,)), pts)
V = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 2, shape=(2,)))
left = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], 0.0))
right = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], L))
Vx, Vy = V.sub(0), V.sub(1)
bcs = [dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx),
       dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, left), Vy)]
mt = meshtags(domain, 1, right, np.full(len(right), 1, dtype=np.int32))
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
load = ufl.inner(ufl.as_vector((0.0, -F / W)), v) * THICK * ds(1)
from dolfinx.fem.petsc import LinearProblem
problem = LinearProblem(a, load, bcs=bcs, petsc_options_prefix="vcax_gold_",
                        petsc_options={"ksp_type": "preonly", "pc_type": "lu"})
uh = problem.solve()
V1 = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
ip = V1.element.interpolation_points
ip = ip() if callable(ip) else ip
uy = Function(V1)
uy.interpolate(fem.Expression(uh[1], ip))
xy = V1.tabulate_dof_coordinates()
tip = xy[:, 0] >= L - 1e-3
tip_uy = float(np.mean(uy.x.array[tip]))
with open("summary.txt", "w") as fh:
    fh.write(f"{R:.6f}, {tip_uy:.8f}\n")
print("R =", R, " tip_uy =", tip_uy)
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


GOLD = _run(env="FENICS_R=6.0 FENICS_NEAR=0.35 FENICS_HMAX=1.8")
ALT = _run(env="FENICS_R=4.0 FENICS_NEAR=0.35 FENICS_HMAX=1.8")
ALT2 = _run(env="FENICS_R=6.0 FENICS_NEAR=0.30 FENICS_HMAX=1.6 FENICS_MESH=math")
OVER_LIMIT = _run(env="FENICS_R=8.0 FENICS_NEAR=0.35 FENICS_HMAX=1.8")
OUT_OF_BOUNDS = _run(env="FENICS_R=9.0 FENICS_NEAR=0.40 FENICS_HMAX=2.0")
NO_HOLE = _run(env="FENICS_R=0 FENICS_HMAX=1.8")
COARSE = _run(env="FENICS_R=6.0 FENICS_NEAR=1.20 FENICS_HMAX=4.0")

FABRICATE = _run(after=(
    "python3 - <<'PY'\n"
    "v = [float(x) for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(f'{v[0]:.6f}, {v[1] * 1.10:.8f}\\n')\n"
    "PY"))
ZERO_MESH = _run(after=": > mesh.msh")
WRONG_R = _run(after=(
    "python3 - <<'PY'\n"
    "v = open('summary.txt').read().strip().split(',')\n"
    "open('summary.txt', 'w').write('4.0, ' + v[1].strip() + '\\n')\n"
    "PY"))
BAD_SUMMARY = _run(after="printf '6.0\\n' > summary.txt")

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '6.0, -0.2596' > summary.txt
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
    "N2 radius out of bounds": "tampered_input",
    "N5 fabricated summary (+10%)": "fabricated_field",
    "N6 zero-byte mesh": "skipped_steps",
    "N7 metrics only": "metrics_only",
    "N8 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("ge", 0.84)),
    ("P2 robust (gold re-run)", GOLD, ("ge", 0.84)),
    ("A1 alternative legal (R=4)", ALT, ("ge", 0.30)),
    ("A2 alternative legal (math size field)", ALT2, ("ge", 0.84)),
    ("N1 empty delivery", "", ("le", 0.001)),
    ("N2 radius out of bounds", OUT_OF_BOUNDS, ("le", 0.001)),
    ("N3 deflection limit exceeded (R=8)", OVER_LIMIT, ("le", 0.001)),
    ("N4 no hole", NO_HOLE, ("le", 0.001)),
    ("N5 fabricated summary (+10%)", GOLD + FABRICATE, ("le", 0.001)),
    ("N6 zero-byte mesh", GOLD + ZERO_MESH, ("le", 0.001)),
    ("N7 metrics only", METRICS_ONLY, ("le", 0.001)),
    ("N8 encoded payload", GOLD + ENCODE_SUMMARY, ("le", 0.001)),
    ("N9 wrong radius reported", GOLD + WRONG_R, ("le", 0.001)),
    ("N10 coarse mesh", COARSE, ("le", 0.001)),
    ("N11 malformed summary", GOLD + BAD_SUMMARY, ("le", 0.001)),
]