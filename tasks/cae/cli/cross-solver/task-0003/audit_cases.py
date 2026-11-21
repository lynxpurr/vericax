"""Audit cases for cae--cli--cross-solver--task-0003 (software-selection).

Required tool: FEniCS/dolfinx (smooth spatially varying modulus E(x,y); the
deliverables are the FEniCS native pair: gmsh mesh + dolfinx XDMF/HDF5
checkpoint). The verifier re-solves the submitted mesh with the exact field
and the prescribed P1 discretisation and compares the checkpoint field at
every vertex (matched by coordinates) and the summary. CalculiX cannot
express the smooth field, and a foreign .dat native family is rejected.
"""

GOLD = r"""
set -e
cd /home/user/Desktop
python3 - <<'PYEOF'
import gmsh

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("plate")
occ = gmsh.model.occ
rect = occ.addRectangle(0.0, 0.0, 0.0, 100.0, 100.0)
occ.synchronize()
right = []
for dim, tag in gmsh.model.getEntities(1):
    xmin, _ymin, _z, xmax, _ymax, _zmax = gmsh.model.occ.getBoundingBox(dim, tag)
    if abs(xmin - 100.0) < 1e-3 and abs(xmax - 100.0) < 1e-3:
        right.append(tag)
gmsh.model.addPhysicalGroup(1, right, tag=1, name="VCAX_AUDIT_0003")
gmsh.model.addPhysicalGroup(2, [rect], name="plate")
gmsh.option.setNumber("Mesh.MeshSizeMax", 2.0)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.5)
gmsh.option.setNumber("Mesh.Algorithm", 6)
gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.model.mesh.generate(2)
gmsh.write("mesh.msh")
gmsh.finalize()
PYEOF
python3 - <<'PYEOF'
import numpy as np
from mpi4py import MPI
import basix.ufl
import ufl
from dolfinx import fem, io
from dolfinx.io import gmsh as gmshio
from dolfinx.fem import functionspace, dirichletbc, locate_dofs_topological
from dolfinx.mesh import locate_entities_boundary
from dolfinx.fem.petsc import LinearProblem
import meshio

meshdata = gmshio.read_from_msh("mesh.msh", MPI.COMM_WORLD, gdim=2)
mesh, ft = meshdata.mesh, meshdata.facet_tags
V = functionspace(mesh, ("Lagrange", 1, (2,)))
W, H, E0, NU = 100.0, 100.0, 210000.0, 0.3

left = locate_entities_boundary(mesh, 1, lambda x: np.isclose(x[0], 0.0))
Vx, Vy = V.sub(0), V.sub(1)
bc_x = dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx)
bc_y = dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, left), Vy)

# traction on the challenge group: gmsh physical tag of VCAX_AUDIT_0003
mt = ft
ds = ufl.Measure("ds", domain=mesh, subdomain_data=mt)

def eps(w):
    return ufl.sym(ufl.grad(w))

x = ufl.SpatialCoordinate(mesh)
modulus = E0 * (1.0 + 0.5 * ufl.sin(ufl.pi * x[0] / W) * ufl.sin(ufl.pi * x[1] / H))
mu = modulus / (2.0 * (1.0 + NU))
lam = modulus * NU / ((1.0 + NU) * (1.0 - 2.0 * NU))
lam_star = 2.0 * lam * mu / (lam + 2.0 * mu)

def sigma(w):
    return 2.0 * mu * eps(w) + lam_star * ufl.tr(eps(w)) * ufl.Identity(2)

u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)
# gmshio assigns facet tags from the physical groups in file order; the curve
# group of task-0003 is the first (and only) curve group -> tag 1.
a = ufl.inner(sigma(u), eps(v)) * ufl.dx
L = ufl.dot(ufl.as_vector((100.0, 0.0)), v) * ds(1)

problem = LinearProblem(
    a, L, bcs=[bc_x, bc_y],
    petsc_options_prefix="vcax_ss3_gold_",
    petsc_options={"ksp_type": "preonly", "pc_type": "lu"})
uh = problem.solve()

with io.XDMFFile(MPI.COMM_WORLD, "solution.xdmf", "w") as f:
    f.write_mesh(mesh)
    f.write_function(uh, 0.0)

# summary: mean ux over the challenge-group nodes (via meshio field_data)
mx = meshio.read("mesh.msh")
tag = int(mx.field_data["VCAX_AUDIT_0003"][0])
token_nodes = None
for block, tags in zip(mx.cells, mx.cell_data["gmsh:physical"]):
    if block.type == "line":
        sel = np.asarray(block.data, dtype=np.int64)[np.asarray(tags) == tag]
        if len(sel):
            token_nodes = np.unique(sel.ravel())
assert token_nodes is not None
dof_xy = uh.function_space.tabulate_dof_coordinates()[:, :2]
disp = uh.x.array.reshape(-1, 2)
vals = []
for nid in token_nodes:
    key = (round(float(mx.points[int(nid), 0]), 6),
           round(float(mx.points[int(nid), 1]), 6))
    for row in range(dof_xy.shape[0]):
        if (round(float(dof_xy[row, 0]), 6), round(float(dof_xy[row, 1]), 6)) == key:
            vals.append(disp[row, 0])
            break
assert vals, "token nodes not found in the solution"
Path = __import__("pathlib").Path
Path("summary.txt").write_text(f"{float(np.mean(vals))!r}\n")
PYEOF
"""

ALT = GOLD.replace("Mesh.MeshSizeMax\", 2.0", "Mesh.MeshSizeMax\", 1.5")
ALT = ALT.replace("(buckling)", "(modal)")  # no-op safety
ALT = ALT.replace("VeriCAX", "VeriCAX-alt")

A2 = GOLD.replace("Mesh.MeshSizeMax\", 2.0", "Mesh.MeshSizeMax\", 1.8")
A2 = A2.replace("Mesh.Algorithm\", 6", "Mesh.Algorithm\", 5")

WRONG_GROUP = GOLD.replace('"VCAX_AUDIT_0003"', '"VCAX_OLD_0003"')
COARSE = GOLD.replace("Mesh.MeshSizeMax\", 2.0", "Mesh.MeshSizeMax\", 6.0")
SHIFTED = GOLD.replace("occ.addRectangle(0.0, 0.0, 0.0, 100.0, 100.0)",
                       "occ.addRectangle(5.0, 5.0, 0.0, 100.0, 100.0)")

FABRICATE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = float(Path("/home/user/Desktop/summary.txt").read_text())
Path("/home/user/Desktop/summary.txt").write_text(f"{v * 1.10!r}\n")
PYEOF
"""

FABRICATE_FIELD = GOLD + r"""
python3 - <<'PYEOF'
import h5py

with h5py.File("/home/user/Desktop/solution.h5", "r+") as fh:
    def walk(group):
        for k in group:
            obj = group[k]
            if isinstance(obj, h5py.Dataset):
                if obj.dtype.kind == "f" and obj.name.startswith("/Function/"):
                    obj[...] = obj[...] * 1.02
            else:
                walk(obj)
    walk(fh)
PYEOF
"""

WRONG_TOKEN = GOLD.replace('"VCAX_AUDIT_0003"', '"VCAX_OLD_0003"')

FOREIGN_RESULT = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
# a CalculiX-shaped .dat instead of the FEniCS checkpoint family
for name in ("solution.xdmf", "solution.h5"):
    p = Path("/home/user/Desktop") / name
    p.unlink(missing_ok=True)
Path("/home/user/Desktop/solution.dat").write_text(
    "                        S T E P       1\n\n"
    " displacements (vx,vy,vz) for set VCAX_AUDIT_0003\n\n"
    "         1  0.000000E+00  0.000000E+00  0.000000E+00\n")
Path("/home/user/Desktop/summary.txt").write_text("-0.1\n")
PYEOF
"""

ZERO_XDMF = GOLD + "\n: > /home/user/Desktop/solution.xdmf\n: > /home/user/Desktop/solution.h5\n"

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf 'placeholder\n' > mesh.msh
printf 'placeholder\n' > solution.xdmf
printf 'placeholder\n' > solution.h5
printf '%s\n' '0.05' > summary.txt
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
    "N2 token group missing": "tampered_input",
    "N7 fabricated checkpoint field": "fabricated_field",
    "N8 zero-byte checkpoint": "skipped_steps",
    "N9 metrics only": "metrics_only",
    "N10 encoded summary": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal mesh (finer)", ALT, ("true",)),
    ("A2 alternative legal mesh (alg 5)", A2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 token group missing", WRONG_GROUP, ("false",)),
    ("N3 coarse mesh (6 mm)", COARSE, ("false",)),
    ("N4 fabricated summary (+10%)", FABRICATE_SUMMARY, ("false",)),
    ("N5 wrong token / replayed mesh", WRONG_TOKEN, ("false",)),
    ("N6 foreign native result", FOREIGN_RESULT, ("false",)),
    ("N7 fabricated checkpoint field", FABRICATE_FIELD, ("false",)),
    ("N8 zero-byte checkpoint", ZERO_XDMF, ("false",)),
    ("N9 metrics only", METRICS_ONLY, ("false",)),
    ("N10 encoded summary", ENCODE_SUMMARY, ("false",)),
    ("N11 shifted plate", SHIFTED, ("false",)),
]
