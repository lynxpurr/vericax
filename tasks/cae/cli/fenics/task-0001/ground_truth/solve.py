"""Quarter plate with a central hole under uniaxial tension (FEniCSx)."""
import os

import gmsh
import numpy as np

W, H = 100.0, 100.0
R = float(os.environ.get("FENICS_R", "10"))
HMAX = float(os.environ.get("FENICS_HMAX", "4.0"))
NEAR = float(os.environ.get("FENICS_NEAR", "0.18"))
SLOPE = float(os.environ.get("FENICS_SLOPE", "0.10"))
CLAMP_LOADED = os.environ.get("FENICS_CLAMP", "0") == "1"

E, NU, SIGMA_LOAD, THICK = 210000.0, 0.3, 100.0, 1.0

# ---------------------------------------------------------------- mesh
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("plate")
occ = gmsh.model.occ
rect = occ.addRectangle(0.0, 0.0, 0.0, W, H)
if R > 0:
    disk = occ.addDisk(0.0, 0.0, 0.0, R, R)
    occ.synchronize()
    occ.cut([(2, rect)], [(2, disk)])
occ.synchronize()
gmsh.option.setNumber("Mesh.MeshSizeMax", HMAX)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.1)
fid = gmsh.model.mesh.field.add("MathEval")
gmsh.model.mesh.field.setString(
    fid, "F", f"{NEAR} + {SLOPE}*(sqrt(x^2+y^2) - {R})")
gmsh.model.mesh.field.setAsBackgroundMesh(fid)
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
if CLAMP_LOADED:
    bcs.append(dirichletbc(np.float64(0.0),
                           locate_dofs_topological(Vx, 1, right), Vx))

mt = meshtags(domain, 1, right, np.full(len(right), 1, dtype=np.int32))
ds = ufl.Measure("ds", domain=domain, subdomain_data=mt)

mu = E / (2.0 * (1.0 + NU))
lam = E * NU / ((1.0 + NU) * (1.0 - 2.0 * NU))
lam_star = 2.0 * lam * mu / (lam + 2.0 * mu)  # plane stress


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
radii = np.hypot(xy[:, 0], xy[:, 1])
arc = np.abs(radii - R) <= 1e-3
loaded = xy[:, 0] >= W - 1e-3
sigma_peak = float(np.max(sxx.x.array[arc])) if arc.any() else 0.0
ux_peak = float(np.max(ux.x.array[loaded])) if loaded.any() else 0.0

with open("summary.txt", "w") as fh:
    fh.write(f"{sigma_peak:.6f}, {ux_peak:.6f}\n")
print("sigma_xx_max =", sigma_peak, " ux_max =", ux_peak)

