"""Elliptical hole in a quarter plate under two load cases (FEniCSx)."""
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

