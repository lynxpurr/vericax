"""Quarter plate with a central hole, meshed with pygmsh and solved with dolfinx."""
import math
import os

import gmsh
import meshio
import numpy as np
import pygmsh

W = H = 100.0
R = float(os.environ.get("FENICS_R", "10"))
NEAR = float(os.environ.get("FENICS_NEAR", "0.18"))
FAR = float(os.environ.get("FENICS_FAR", "3.0"))
SIGMA = float(os.environ.get("FENICS_SIGMA", "100"))
E, NU, THICK = 210000.0, 0.3, 1.0

with pygmsh.occ.Geometry() as geom:
    rect = geom.add_rectangle([0.0, 0.0, 0.0], W, H)
    if R > 0.0:
        disk = geom.add_disk([0.0, 0.0, 0.0], R)
        geom.boolean_difference([rect], [disk])
    def size_callback(dim, tag, x, y, z, lc):
        return NEAR + (FAR - NEAR) * max(0.0, math.hypot(x, y) - R) / 90.0
    geom.set_mesh_size_callback(size_callback)
    mesh = geom.generate_mesh(dim=2)
mesh.write("mesh.msh", file_format="gmsh22")

# ---------------------------------------------------------------- solve
import basix.ufl
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
bottom = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[1], 0.0))
right = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], W))
Vx, Vy = V.sub(0), V.sub(1)
bcs = [dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx),
       dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, bottom), Vy)]
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
L = ufl.inner(ufl.as_vector((SIGMA, 0.0)), v) * THICK * ds(1)
from dolfinx.fem.petsc import LinearProblem
problem = LinearProblem(a, L, bcs=bcs, petsc_options_prefix="vcax_gold_",
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
on_hole = np.abs(radii - R) <= 1e-3
loaded = xy[:, 0] >= W - 1e-3
sigma_peak = float(np.max(sxx.x.array[on_hole])) if on_hole.any() else 0.0
ux_peak = float(np.max(ux.x.array[loaded])) if loaded.any() else 0.0
with open("summary.txt", "w") as fh:
    fh.write(f"{sigma_peak:.6f}, {ux_peak:.6f}\n")

