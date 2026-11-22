"""Audit cases for cae--cli--fenics--task-0015 (open-environment, pygmsh).

The agent installs pygmsh from the local wheelhouse, meshes the quarter plate
with a central hole, and solves it with dolfinx. The verifier checks the mesh,
re-solves it, and requires solve.py to use pygmsh.
"""

INSTALL = r"""
set -e
cd /home/user/Desktop
python3 -m pip install --user --no-index --find-links wheels pygmsh==7.1.17 >/dev/null 2>&1
"""

SOLVE = r'''"""Quarter plate with a central hole, meshed with pygmsh and solved with dolfinx."""
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
'''


def _run(env: str = "", after: str = "") -> str:
    prefix = f"{env} " if env else ""
    tail = f"\n{after}\n" if after else ""
    return (
        INSTALL
        + "cat > solve.py <<'PYEOF'\n"
        + SOLVE
        + "\nPYEOF\n"
        + prefix + "python3 solve.py\n"
        + tail
    )


GOLD = _run()
ALT = _run(env="FENICS_NEAR=0.15 FENICS_FAR=2.5")
ALT2 = _run(env="FENICS_NEAR=0.12 FENICS_FAR=4.0")
WRONG_RADIUS = _run(env="FENICS_R=8")
WRONG_LOAD = _run(env="FENICS_SIGMA=80")
COARSE = _run(env="FENICS_NEAR=1.0 FENICS_FAR=10.0")
NO_PYGMSH = r"""
set -e
cd /home/user/Desktop
cat > solve.py <<'PYEOF'
# A hand-written summary without pygmsh.
with open("summary.txt", "w") as fh:
    fh.write("308.46, 0.05008\n")
PYEOF
python3 solve.py
"""
FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = [float(x) for x in Path("/home/user/Desktop/summary.txt").read_text().split(",")]
Path("/home/user/Desktop/summary.txt").write_text(f"{v[0] * 1.10:.6f}, {v[1] * 1.10:.6f}\n")
PYEOF
"""
ZERO_MESH = GOLD + "\n: > /home/user/Desktop/mesh.msh\n"
METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '308.46, 0.05008' > summary.txt
"""
ENCODE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
import base64
from pathlib import Path
raw = Path("/home/user/Desktop/summary.txt").read_text().strip().encode()
Path("/home/user/Desktop/summary.txt").write_text(base64.b64encode(raw).decode() + "\n")
PYEOF
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N2 wrong hole radius": "tampered_input",
    "N6 fabricated summary (+10%)": "fabricated_field",
    "N7 zero-byte mesh": "skipped_steps",
    "N8 metrics only": "metrics_only",
    "N9 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (finer mesh)", ALT, ("true",)),
    ("A2 alternative legal (finer hole mesh)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 wrong hole radius", WRONG_RADIUS, ("false",)),
    ("N3 wrong load", WRONG_LOAD, ("false",)),
    ("N4 no pygmsh", NO_PYGMSH, ("false",)),
    ("N5 coarse mesh", COARSE, ("false",)),
    ("N6 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N7 zero-byte mesh", ZERO_MESH, ("false",)),
    ("N8 metrics only", METRICS_ONLY, ("false",)),
    ("N9 encoded payload", ENCODE_SUMMARY, ("false",)),
]