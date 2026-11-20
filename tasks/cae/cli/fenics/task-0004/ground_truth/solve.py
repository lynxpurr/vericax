"""Linearly tapered cantilever under a tip load (FEniCSx)."""
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

