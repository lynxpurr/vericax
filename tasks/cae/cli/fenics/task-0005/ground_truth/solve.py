"""Cantilever with a circular lightening hole (FEniCSx)."""
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

