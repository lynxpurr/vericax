"""Elliptical hole in a quarter plate under uniaxial tension (FEniCSx)."""
import os

import gmsh
import numpy as np

W, H = 100.0, 100.0
A = float(os.environ.get("FENICS_A", "20"))
B = float(os.environ.get("FENICS_B", "5"))
NEAR = float(os.environ.get("FENICS_NEAR", "0.12"))
HMAX = float(os.environ.get("FENICS_HMAX", "3.0"))
STRATEGY = os.environ.get("FENICS_MESH", "dist")

E, NU, SIGMA_LOAD, THICK = 210000.0, 0.3, 100.0, 1.0

# ---------------------------------------------------------------- mesh
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("plate")
occ = gmsh.model.occ
rect = occ.addRectangle(0.0, 0.0, 0.0, W, H)
if A > 0.0 and B > 0.0:
    hole = occ.addDisk(0.0, 0.0, 0.0, A, B)
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
if A > 0.0 and B > 0.0:
    q = np.hypot(xy[:, 0] / A, xy[:, 1] / B)
    on_hole = np.abs(q - 1.0) <= 1e-3
    sigma_peak = float(np.max(sxx.x.array[on_hole])) if on_hole.any() else 0.0
else:
    sigma_peak = 0.0

with open("summary.txt", "w") as fh:
    fh.write(f"{A:.6f}, {B:.6f}, {sigma_peak:.6f}, {ux_peak:.6f}\n")
print("a =", A, " b =", B, " sigma_xx_max =", sigma_peak, " ux_max =", ux_peak)

