"""Audit cases for cae--cli--fenics--task-0004 (quantified_score, L1-L5).

The first case is the ground-truth source. Cases assert on the numeric score:
"ge" for accepted designs, "le" for rejected or baseline designs.

Reference design: linearly tapered cantilever, tip width 6 mm, root 20 mm.
The tip deflection is 0.5487 mm, under the 0.58 mm limit; the score is
(20-6)/(20-5.57) = 0.970.
"""

SOLVER = r'''"""Linearly tapered cantilever under a tip load (FEniCSx)."""
import os

import gmsh
import numpy as np

L, W0, THICK = 100.0, 20.0, 1.0
WT = float(os.environ.get("FENICS_WT", "6.0"))
HMAX = float(os.environ.get("FENICS_HMAX", "0.9"))
STRATEGY = os.environ.get("FENICS_MESH", "math")
E, NU, F = 210000.0, 0.3, 100.0

# ---------------------------------------------------------------- mesh
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("taper")
occ = gmsh.model.occ
pts = [occ.addPoint(0.0, -W0 / 2, 0.0), occ.addPoint(L, -WT / 2, 0.0),
       occ.addPoint(L, WT / 2, 0.0), occ.addPoint(0.0, W0 / 2, 0.0)]
lines = [occ.addLine(pts[i], pts[(i + 1) % 4]) for i in range(4)]
loop = occ.addCurveLoop(lines)
occ.addPlaneSurface([loop])
occ.synchronize()

gmsh.option.setNumber("Mesh.MeshSizeMax", HMAX)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.2)
if STRATEGY == "math":
    fid = gmsh.model.mesh.field.add("MathEval")
    gmsh.model.mesh.field.setString(fid, "F", f"0.5 + {HMAX}*x/{L}")
    gmsh.model.mesh.field.setAsBackgroundMesh(fid)
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
load = ufl.inner(ufl.as_vector((0.0, -F / WT)), v) * THICK * ds(1)
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
    fh.write(f"{WT:.6f}, {tip_uy:.8f}\n")
print("tip_width =", WT, " tip_uy =", tip_uy)
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


GOLD = _run(env="FENICS_WT=6.0 FENICS_HMAX=0.9")
ALT = _run(env="FENICS_WT=8.0 FENICS_HMAX=0.9")
ALT2 = _run(env="FENICS_WT=6.0 FENICS_HMAX=0.7 FENICS_MESH=uniform")
BASELINE = _run(env="FENICS_WT=20.0 FENICS_HMAX=1.0 FENICS_MESH=uniform")
OVER_LIMIT = _run(env="FENICS_WT=4.0 FENICS_HMAX=0.9")
OUT_OF_BOUNDS = _run(env="FENICS_WT=3.0 FENICS_HMAX=0.9")
COARSE = _run(env="FENICS_WT=6.0 FENICS_HMAX=2.5 FENICS_MESH=uniform")

FABRICATE = _run(after=(
    "python3 - <<'PY'\n"
    "v = [float(x) for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(f'{v[0]:.6f}, {v[1] * 1.10:.8f}\\n')\n"
    "PY"))
ZERO_MESH = _run(after=": > mesh.msh")
WRONG_WT = _run(after=(
    "python3 - <<'PY'\n"
    "v = open('summary.txt').read().strip().split(',')\n"
    "open('summary.txt', 'w').write('8.0, ' + v[1].strip() + '\\n')\n"
    "PY"))
BAD_SUMMARY = _run(after="printf '6.0\\n' > summary.txt")

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '6.0, -0.5487' > summary.txt
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
    "N2 tip width out of bounds": "tampered_input",
    "N5 fabricated summary (+10%)": "fabricated_field",
    "N6 zero-byte mesh": "skipped_steps",
    "N7 metrics only": "metrics_only",
    "N8 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("ge", 0.95)),
    ("P2 robust (gold re-run)", GOLD, ("ge", 0.95)),
    ("A1 alternative legal (wt=8)", ALT, ("ge", 0.80)),
    ("A2 alternative legal (uniform mesh)", ALT2, ("ge", 0.95)),
    ("N1 empty delivery", "", ("le", 0.001)),
    ("N2 tip width out of bounds", OUT_OF_BOUNDS, ("le", 0.001)),
    ("N3 deflection limit exceeded (wt=4)", OVER_LIMIT, ("le", 0.001)),
    ("N4 baseline copied (wt=20)", BASELINE, ("le", 0.001)),
    ("N5 fabricated summary (+10%)", GOLD + FABRICATE, ("le", 0.001)),
    ("N6 zero-byte mesh", GOLD + ZERO_MESH, ("le", 0.001)),
    ("N7 metrics only", METRICS_ONLY, ("le", 0.001)),
    ("N8 encoded payload", GOLD + ENCODE_SUMMARY, ("le", 0.001)),
    ("N9 wrong tip width reported", GOLD + WRONG_WT, ("le", 0.001)),
    ("N10 coarse mesh", COARSE, ("le", 0.001)),
    ("N11 malformed summary", GOLD + BAD_SUMMARY, ("le", 0.001)),
]