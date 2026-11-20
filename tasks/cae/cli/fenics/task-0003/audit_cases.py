"""Audit cases for cae--cli--fenics--task-0003 (quantified_score, L1-L5).

The first case is the ground-truth source. Cases assert on the numeric score:
"ge" for accepted designs, "le" for rejected or baseline designs.

Reference design: R=30.5 mm, just below the 400 MPa peak-stress limit. The
score is the normalized mass reduction from the R=10 mm baseline to the best
feasible radius (R ~= 31.56 mm).
"""

SOLVER = r'''"""Circular hole sizing in a quarter plate under uniaxial tension (FEniCSx)."""
import os

import gmsh
import numpy as np

W, H = 100.0, 100.0
R = float(os.environ.get("FENICS_R", "30.5"))
HMAX = float(os.environ.get("FENICS_HMAX", "5.0"))
NEAR = float(os.environ.get("FENICS_NEAR", "0.20"))
SLOPE = float(os.environ.get("FENICS_SLOPE", "0.10"))
STRATEGY = os.environ.get("FENICS_MESH", "dist")

E, NU, SIGMA_LOAD, THICK = 210000.0, 0.3, 100.0, 1.0

# ---------------------------------------------------------------- mesh
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("plate")
occ = gmsh.model.occ
rect = occ.addRectangle(0.0, 0.0, 0.0, W, H)
if R > 0.0:
    disk = occ.addDisk(0.0, 0.0, 0.0, R, R)
    occ.synchronize()
    occ.cut([(2, rect)], [(2, disk)])
occ.synchronize()

gmsh.option.setNumber("Mesh.MeshSizeMax", HMAX)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.05)
field = gmsh.model.mesh.field
if R > 0.0 and STRATEGY == "math":
    fid = field.add("MathEval")
    field.setString(fid, "F", f"{NEAR} + {SLOPE}*(sqrt(x^2+y^2) - {R})")
    field.setAsBackgroundMesh(fid)
elif R > 0.0:
    f_dist = field.add("Distance")
    field.setNumber(f_dist, "Sampling", 200)
    curves = []
    for _dim, ctag in gmsh.model.getEntities(1):
        xmin, ymin, _zmin, xmax, ymax, _zmax = gmsh.model.occ.getBoundingBox(1, ctag)
        if (xmax <= R + 1e-6 and ymax <= R + 1e-6
                and not (xmax <= 1e-9 or ymax <= 1e-9)):
            curves.append(ctag)
    field.setNumbers(f_dist, "CurvesList", curves)
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
Vx, Vy = V.sub(0), V.sub(1)
bcs = [
    dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx),
    dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, bottom), Vy),
]

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
L = ufl.inner(ufl.as_vector((SIGMA_LOAD, 0.0)), v) * THICK * ds(1)

from dolfinx.fem.petsc import LinearProblem  # explicit submodule import

problem = LinearProblem(
    a, L, bcs=bcs, petsc_options_prefix="vcax_gold_",
    petsc_options={"ksp_type": "preonly", "pc_type": "lu"})
uh = problem.solve()

V1 = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
ip = V1.element.interpolation_points
ip = ip() if callable(ip) else ip
sxx = Function(V1)
sxx.interpolate(fem.Expression(sigma(uh)[0, 0], ip))
ux = Function(V1)
ux.interpolate(fem.Expression(uh[0], ip))

xy = V1.tabulate_dof_coordinates()
loaded = xy[:, 0] >= W - 1e-3
ux_peak = float(np.max(ux.x.array[loaded])) if loaded.any() else 0.0
if R > 0.0:
    radii = np.hypot(xy[:, 0], xy[:, 1])
    on_hole = np.abs(radii - R) <= 1e-3
    sigma_peak = float(np.max(sxx.x.array[on_hole])) if on_hole.any() else 0.0
else:
    sigma_peak = 0.0

with open("summary.txt", "w") as fh:
    fh.write(f"{R:.6f}, {sigma_peak:.6f}, {ux_peak:.6f}\n")
print("R =", R, " sigma_xx_max =", sigma_peak, " ux_max =", ux_peak)
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


GOLD = _run(env="FENICS_R=30.5 FENICS_NEAR=0.20 FENICS_HMAX=5.0")
ALT = _run(env="FENICS_R=30.0 FENICS_NEAR=0.22 FENICS_HMAX=5.0")
ALT2 = _run(env="FENICS_R=30.5 FENICS_NEAR=0.20 FENICS_HMAX=5.0 FENICS_MESH=math")
BASELINE = _run(env="FENICS_R=10.0 FENICS_NEAR=0.12 FENICS_HMAX=4.0")
OVER_LIMIT = _run(env="FENICS_R=35.0 FENICS_NEAR=0.22 FENICS_HMAX=6.0")
OUT_OF_BOUNDS = _run(env="FENICS_R=45.0 FENICS_NEAR=0.25 FENICS_HMAX=7.0")
NO_HOLE = _run(env="FENICS_R=0 FENICS_HMAX=4.0")
COARSE = _run(env="FENICS_R=30.5 FENICS_NEAR=0.90 FENICS_HMAX=10.0")

FABRICATE = _run(after=(
    "python3 - <<'PY'\n"
    "line = [float(x) for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(f'{line[0]:.6f}, {line[1] * 0.95:.6f}, "
    "{line[2] * 1.10:.6f}\\n')\n"
    "PY"))
ZERO_MESH = _run(after=": > mesh.msh")
WRONG_R = _run(after=(
    "python3 - <<'PY'\n"
    "v = open('summary.txt').read().strip().split(',')\n"
    "open('summary.txt', 'w').write('20.0, ' + ', '.join(x.strip() for x in v[1:]) + '\\n')\n"
    "PY"))
BAD_SUMMARY = _run(after="printf '30.5, 391.6\\n' > summary.txt")

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '30.5, 391.6, 0.075' > summary.txt
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
    "N3 radius out of bounds": "tampered_input",
    "N6 fabricated summary": "fabricated_field",
    "N7 zero-byte mesh": "skipped_steps",
    "N8 metrics only": "metrics_only",
    "N9 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("ge", 0.92)),
    ("P2 robust (gold re-run)", GOLD, ("ge", 0.92)),
    ("A1 alternative legal (R=30.0)", ALT, ("ge", 0.88)),
    ("A2 alternative legal (math size field)", ALT2, ("ge", 0.92)),
    ("N1 empty delivery", "", ("le", 0.001)),
    ("N2 stress limit exceeded (R=35)", OVER_LIMIT, ("le", 0.001)),
    ("N3 radius out of bounds", OUT_OF_BOUNDS, ("le", 0.001)),
    ("N4 no hole", NO_HOLE, ("le", 0.001)),
    ("N5 baseline copied (R=10)", BASELINE, ("le", 0.001)),
    ("N6 fabricated summary", GOLD + FABRICATE, ("le", 0.001)),
    ("N7 zero-byte mesh", GOLD + ZERO_MESH, ("le", 0.001)),
    ("N8 metrics only", METRICS_ONLY, ("le", 0.001)),
    ("N9 encoded payload", GOLD + ENCODE_SUMMARY, ("le", 0.001)),
    ("N10 wrong radius reported", GOLD + WRONG_R, ("le", 0.001)),
    ("N11 coarse mesh", COARSE, ("le", 0.001)),
    ("N12 malformed summary", GOLD + BAD_SUMMARY, ("le", 0.001)),
]