"""Two-stage thermo-elastic analysis of a quarter plate with a hole (FEniCSx)."""
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

