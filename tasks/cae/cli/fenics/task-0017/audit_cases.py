"""Audit cases for cae--cli--fenics--task-0017 (exact_match, L1-L4).

The first case is the ground-truth source. Cases assert on the verifier's
boolean verdict.

Reference model: one mesh of a quarter plate with a 20 mm hole; steady heat
conduction, then plane-stress thermo-elasticity in three load cases (thermal
only, traction only, both). The environment knobs exist for the negatives:
each one breaks the model in a specific way while leaving the delivery format
intact.
"""

SOLVER = r'''"""Two-stage thermo-elastic analysis of a quarter plate with a hole (FEniCSx)."""
import os

import gmsh
import numpy as np

W, H = 100.0, 100.0
R = float(os.environ.get("FENICS_R", "20.0"))
HMAX = float(os.environ.get("FENICS_HMAX", "5.0"))
NEAR = float(os.environ.get("FENICS_NEAR", "0.20"))
STRATEGY = os.environ.get("FENICS_MESH", "dist")
SKIP_THERMAL = os.environ.get("FENICS_SKIP_THERMAL", "") == "1"
BETA_MODE = os.environ.get("FENICS_BETA", "plane_stress")
SCALE = float(os.environ.get("FENICS_SCALE", "1.0"))
TRACTION = float(os.environ.get("FENICS_TRACTION", "100.0"))
ALPHA_SIGN = float(os.environ.get("FENICS_ALPHA_SIGN", "1.0"))
SUPERPOSE = os.environ.get("FENICS_SUPERPOSE", "") == "1"
SUMMARY = os.environ.get("FENICS_SUMMARY", "summary.txt")

K_COND, F0 = 45.0, 4.0
E, NU, ALPHA, THICK = 210000.0, 0.3, 1.2e-5, 1.0

# ---------------------------------------------------------------- mesh
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("plate")
occ = gmsh.model.occ
rect = occ.addRectangle(0.0, 0.0, 0.0, W, H)
disk = occ.addDisk(0.0, 0.0, 0.0, R, R)
occ.synchronize()
occ.cut([(2, rect)], [(2, disk)])
occ.synchronize()

gmsh.option.setNumber("Mesh.MeshSizeMax", HMAX)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.05)
field = gmsh.model.mesh.field
if STRATEGY == "math":
    fid = field.add("MathEval")
    field.setString(fid, "F", f"{NEAR} + 0.10*(sqrt(x^2+y^2) - {R})")
    field.setAsBackgroundMesh(fid)
else:
    f_dist = field.add("Distance")
    field.setNumber(f_dist, "Sampling", 200)
    curves = []
    for _dim, ctag in gmsh.model.getEntities(1):
        xmin, ymin, _zmin, xmax, ymax, _zmax = gmsh.model.occ.getBoundingBox(1, ctag)
        if (xmax <= R + 1e-3 and ymax <= R + 1e-3
                and not (xmax <= 1e-3 or ymax <= 1e-3)):
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
if os.environ.get("FENICS_SKIP_SOLVE", "0") == "1":
    # audit-only: build the mesh of a rejected case without solving on it
    raise SystemExit(0)

# ---------------------------------------------------------------- stage 1
import basix.ufl
import meshio
import ufl
from dolfinx import fem
from dolfinx.fem import dirichletbc, functionspace, locate_dofs_topological
from dolfinx.fem.petsc import LinearProblem
from dolfinx.mesh import create_mesh, locate_entities_boundary, meshtags
from mpi4py import MPI

LU = {"ksp_type": "preonly", "pc_type": "lu"}
m = meshio.read("mesh.msh")
pts = np.ascontiguousarray(m.points[:, :2], dtype=float)
cells = np.asarray(m.cells_dict["triangle"], dtype=np.int64)
domain = create_mesh(
    MPI.COMM_WORLD, cells,
    basix.ufl.element("Lagrange", "triangle", 1, shape=(2,)), pts)

Q = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
cold = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], W))
bc_t = dirichletbc(np.float64(0.0), locate_dofs_topological(Q, 1, cold), Q)
x = ufl.SpatialCoordinate(domain)
source = fem.Constant(domain, SCALE * F0) * ufl.cos(ufl.pi * x[0] / (2.0 * W))
T, q = ufl.TrialFunction(Q), ufl.TestFunction(Q)
temperature = LinearProblem(
    K_COND * ufl.dot(ufl.grad(T), ufl.grad(q)) * ufl.dx, source * q * ufl.dx,
    bcs=[bc_t], petsc_options_prefix="vcax_gold_t_", petsc_options=LU).solve()
if SKIP_THERMAL:
    temperature.x.array[:] = 0.0
t_max = float(np.max(temperature.x.array))

# ---------------------------------------------------------------- stage 2
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
if BETA_MODE == "plane_strain":
    beta = E * ALPHA * ALPHA_SIGN / ((1.0 + NU) * (1.0 - 2.0 * NU))
else:
    beta = E * ALPHA * ALPHA_SIGN / (1.0 - NU)


def eps(w):
    return ufl.sym(ufl.grad(w))


def sigma(w):
    return 2.0 * mu * eps(w) + lam_star * ufl.tr(eps(w)) * ufl.Identity(2)


u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)
a = ufl.inner(sigma(u), eps(v)) * ufl.dx


def ux_mean(thermal, traction):
    """Mean ux along the loaded edge: a linear functional, so the cases add up."""
    L = fem.Constant(domain, 0.0) * v[0] * ufl.dx
    if thermal:
        L = L + beta * temperature * ufl.tr(eps(v)) * ufl.dx
    if traction:
        L = L + ufl.inner(ufl.as_vector((TRACTION, 0.0)), v) * THICK * ds(1)
    uh = LinearProblem(a, L, bcs=bcs, petsc_options_prefix="vcax_gold_u_",
                       petsc_options=LU).solve()
    return float(fem.assemble_scalar(fem.form(uh[0] * ds(1))) / W)


ux_th = ux_mean(True, False)
ux_m = ux_mean(False, True)
ux_both = ux_th + ux_m if SUPERPOSE else ux_mean(True, True)

with open(SUMMARY, "w") as fh:
    fh.write(f"{t_max:.6f}, {ux_th:.6f}, {ux_m:.6f}, {ux_both:.6f}\n")
print("T_max =", t_max, " ux_th =", ux_th, " ux_m =", ux_m, " ux_both =", ux_both)
'''


def _run(env: str = "", after: str = "") -> str:
    prefix = f"{env} " if env else ""
    tail = f"\n{after}\n" if after else ""
    return (
        "set -e\n"
        "cd /home/user/Desktop\n"
        "rm -f mesh.msh solve.py summary.txt\n"
        "cat > /tmp/solve.py <<'PYEOF'\n"
        + SOLVER
        + "\nPYEOF\n"
        "cp /tmp/solve.py solve.py\n"
        + prefix + "python3 /tmp/solve.py\n"
        + tail
    )


GOLD = _run("FENICS_HMAX=5.0 FENICS_NEAR=0.20")
FINER = _run("FENICS_HMAX=4.0 FENICS_NEAR=0.15")
MATH_FIELD = _run("FENICS_HMAX=5.0 FENICS_NEAR=0.20 FENICS_MESH=math")
SUPERPOSED = _run("FENICS_HMAX=5.0 FENICS_NEAR=0.20 FENICS_SUPERPOSE=1")

SKIP_THERMAL = _run("FENICS_HMAX=5.0 FENICS_NEAR=0.20 FENICS_SKIP_THERMAL=1")
PLANE_STRAIN_BETA = _run("FENICS_HMAX=5.0 FENICS_NEAR=0.20 FENICS_BETA=plane_strain")
OTHER_SOURCE = _run("FENICS_HMAX=5.0 FENICS_NEAR=0.20 FENICS_SCALE=1.2")
WRONG_RADIUS = _run("FENICS_R=25.0 FENICS_HMAX=5.0 FENICS_NEAR=0.20")
COARSE = _run("FENICS_HMAX=10.0 FENICS_NEAR=0.90")
# Too fine for the verifier's direct solve: rejected on the element count alone
# (no solve on that mesh; the summary is a placeholder).
OVERSIZED = _run("FENICS_HMAX=1.5 FENICS_NEAR=0.05 FENICS_SKIP_SOLVE=1",
                after="printf '1, 2, 3, 4\\n' > summary.txt")
THERMAL_CONTRACTION = _run("FENICS_HMAX=5.0 FENICS_NEAR=0.20 FENICS_ALPHA_SIGN=-1")

# Each stage within the 1 % re-solve tolerance, but no longer one linear
# model: ux_both is not ux_th + ux_m. Only the cross-stage check rejects it.
INCONSISTENT = _run(after=(
    "python3 - <<'PY'\n"
    "a, b, c, d = (float(x) for x in open('summary.txt').read().split(','))\n"
    "open('summary.txt', 'w').write(f'{a:.6f}, {b * 1.005:.6f}, {c * 1.005:.6f}, {d:.6f}\\n')\n"
    "PY"))

FABRICATE = _run(after=(
    "python3 - <<'PY'\n"
    "a, b, c, d = (float(x) for x in open('summary.txt').read().split(','))\n"
    "open('summary.txt', 'w').write(f'{a:.6f}, {b:.6f}, {c:.6f}, {d * 1.10:.6f}\\n')\n"
    "PY"))
SWAP = _run(after=(
    "python3 - <<'PY'\n"
    "a, b, c, d = (float(x) for x in open('summary.txt').read().split(','))\n"
    "open('summary.txt', 'w').write(f'{a:.6f}, {c:.6f}, {b:.6f}, {d:.6f}\\n')\n"
    "PY"))
ZERO_MESH = _run(after=": > mesh.msh")
BAD_SUMMARY = _run(after="printf '200.0, 0.3\\n' > summary.txt")

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '200.000000, 0.300000, 0.060000, 0.360000' > summary.txt
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
    "N5 wrong hole radius (R=25)": "tampered_input",
    "N10 fabricated summary (+10%)": "fabricated_field",
    "N11 zero-byte mesh": "skipped_steps",
    "N13 metrics only": "metrics_only",
    "N14 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (finer mesh)", FINER, ("true",)),
    ("A2 alternative legal (math size field)", MATH_FIELD, ("true",)),
    ("A3 alternative legal (both by superposition)", SUPERPOSED, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 thermal stage skipped", SKIP_THERMAL, ("false",)),
    ("N3 plane-strain coupling constant", PLANE_STRAIN_BETA, ("false",)),
    ("N4 other heat source", OTHER_SOURCE, ("false",)),
    ("N5 wrong hole radius (R=25)", WRONG_RADIUS, ("false",)),
    ("N6 coarse mesh", COARSE, ("false",)),
    ("N15 oversized mesh (more than 80000 triangles)", OVERSIZED, ("false",)),
    ("N7 stages do not add up (+0.5%)", INCONSISTENT, ("false",)),
    ("N8 swapped ux_th / ux_m", SWAP, ("false",)),
    ("N9 thermal contraction", THERMAL_CONTRACTION, ("false",)),
    ("N10 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N11 zero-byte mesh", ZERO_MESH, ("false",)),
    ("N12 malformed summary", BAD_SUMMARY, ("false",)),
    ("N13 metrics only", METRICS_ONLY, ("false",)),
    ("N14 encoded payload", ENCODE_SUMMARY, ("false",)),
]
