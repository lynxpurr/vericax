"""Audit cases for cae--cli--fenics--task-0019 (exact_match, L1-L3; full plate, oblique load).

Each entry is (label, bash script, expectation). The harness runs the first
script as the ground-truth source, so keep GOLD canonical.

The solver template below is the artifact an agent would deliver: it meshes
the full plate with both holes (gmsh OCC, a MathEval size field refined near
both holes), solves the plane-stress problem with dolfinx and writes
summary.txt. Environment overrides let the negative cases produce
deliberately wrong artifacts without duplicating the script.

Hand estimate for the gold (2026-11-28): the x component of the force is
31.2 kN and the net section beside hole A is (120 - 24) x 2 = 192 mm^2, so the
nominal sigma_xx there is about 162 MPa; with a stress concentration of about
2.6 the peak is about 420 MPa. The first version of this template carried the
thickness in the load but not in the stiffness, reported 844 MPa, and passed a
24-case audit, because the gold and the verifier share the template: the audit
proves that the two agree, not that either is right. In the calibration run
every agent solution came out at half that value. The template now carries the
thickness in both forms, and two cases cover the alternative formulations. The mesh must also stay below 80000 triangles (stated in the
instruction; it bounds the verifier's direct solve): N20 exceeds the cap and is
rejected before any solve.
"""

SOLVER = r'''"""Full plate with two holes under an oblique load on its right edge (FEniCSx)."""
import math
import os

import gmsh
import numpy as np

W, H, THICK = 240.0, 120.0, 2.0
FORCE = float(os.environ.get("FENICS_FORCE", "36.0"))     # kN, total, mid-height of the right edge
ANGLE = float(os.environ.get("FENICS_ANGLE", "30.0"))     # deg above the +x axis
RAW_TRACTION = os.environ.get("FENICS_RAW_TRACTION", "0") == "1"
E_GPA, NU = float(os.environ.get("FENICS_E_GPA", "210.0")), 0.3
E_UNIT = os.environ.get("FENICS_E_UNIT", "gpa")           # the drawing gives GPa
HMAX = float(os.environ.get("FENICS_HMAX", "3.5"))
NEAR = float(os.environ.get("FENICS_NEAR", "0.5"))
GROW = float(os.environ.get("FENICS_GROW", "12.0"))
MESH_STRATEGY = os.environ.get("FENICS_MESH", "eval")
HALF_MODEL = os.environ.get("FENICS_HALF", "0") == "1"
SKIP_HOLE = os.environ.get("FENICS_SKIP_HOLE", "")
SWAP_HOLES = os.environ.get("FENICS_SWAP_HOLES", "0") == "1"
RA = float(os.environ.get("FENICS_RA", "12.0"))
RB = float(os.environ.get("FENICS_RB", "6.0"))
# where the thickness is carried: in both forms (canonical), in neither
# (unit-thickness form, equivalent), or in the load only (a factor-of-2 error)
FORM = os.environ.get("FENICS_FORM", "both")

E = E_GPA * (1000.0 if E_UNIT == "gpa" else 1.0)          # MPa
# total force -> uniform traction over the right edge (N/mm^2 = MPa)
TRACTION = FORCE if RAW_TRACTION else FORCE * 1000.0 / (H * THICK)

HOLES = {"A": (70.0, 60.0, RA), "B": (170.0, 60.0, RB)}   # centre x, centre y, radius
if SWAP_HOLES:
    HOLES = {"A": (170.0, 60.0, RA), "B": (70.0, 60.0, RB)}
Y0 = H / 2 if HALF_MODEL else 0.0                         # a false-symmetry half model
cut = [hole for name, hole in HOLES.items() if name != SKIP_HOLE]

# ---------------------------------------------------------------- mesh
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("plate")
occ = gmsh.model.occ
rect = occ.addRectangle(0.0, Y0, 0.0, W, H - Y0)
disks = [occ.addDisk(cx, cy, 0.0, r, r) for cx, cy, r in cut]
occ.synchronize()
if disks:
    occ.cut([(2, rect)], [(2, disk) for disk in disks])
occ.synchronize()
gmsh.option.setNumber("Mesh.MeshSizeMax", HMAX)
gmsh.option.setNumber("Mesh.MeshSizeMin", 0.1)
field = gmsh.model.mesh.field


def _hole_curves():
    curves = []
    for _dim, tag in gmsh.model.getEntities(1):
        xmin, ymin, _zmin, xmax, ymax, _zmax = gmsh.model.occ.getBoundingBox(1, tag)
        # hole curves are at most 24 x 24 mm; the outer edges are >= 60 mm long
        if (xmax - xmin) ** 2 + (ymax - ymin) ** 2 < 45.0 ** 2:
            curves.append(tag)
    return curves


def _ramp(cx, cy, r):
    """0 on the hole arc, -> 1 away from it on either side (linear over about GROW).

    The unsigned distance keeps the field positive everywhere, so it stays sane
    where a hole is not cut (the negative cases)."""
    d = f"(sqrt((x-{cx})*(x-{cx})+(y-{cy})*(y-{cy}))-{r})"
    return f"sqrt({d}*{d})/sqrt({d}*{d}+{GROW * GROW})"


if MESH_STRATEGY == "dist":
    # Different meshing strategy: distance-to-holes + threshold field.
    f_dist = field.add("Distance")
    field.setNumbers(f_dist, "CurvesList", _hole_curves())
    f_thr = field.add("Threshold")
    field.setNumber(f_thr, "InField", f_dist)
    field.setNumber(f_thr, "SizeMin", NEAR)
    field.setNumber(f_thr, "SizeMax", HMAX)
    field.setNumber(f_thr, "DistMin", 0.0)
    field.setNumber(f_thr, "DistMax", GROW)
    field.setAsBackgroundMesh(f_thr)
else:
    fid = field.add("MathEval")
    field.setString(fid, "F", f"{NEAR}+({HMAX}-{NEAR})"
                    f"*{_ramp(*HOLES['A'])}*{_ramp(*HOLES['B'])}")
    field.setAsBackgroundMesh(fid)
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
bottom = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[1], Y0))
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
lam_star = 2.0 * lam * mu / (lam + 2.0 * mu)  # plane stress


def eps(w):
    return ufl.sym(ufl.grad(w))


def sigma(w):
    return 2.0 * mu * eps(w) + lam_star * ufl.tr(eps(w)) * ufl.Identity(2)


u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)
# The thickness belongs to both forms, or to neither.
T_STIFF = THICK if FORM != "none" else 1.0
T_LOAD = THICK if FORM != "none" else 1.0
if FORM == "load_only":
    T_STIFF = 1.0
a = ufl.inner(sigma(u), eps(v)) * T_STIFF * ufl.dx
traction = ufl.as_vector((TRACTION * math.cos(math.radians(ANGLE)),
                          TRACTION * math.sin(math.radians(ANGLE))))
L = ufl.inner(traction, v) * T_LOAD * ds(1)

from dolfinx.fem.petsc import LinearProblem  # explicit submodule import

problem = LinearProblem(
    a, L, bcs=bcs, petsc_options_prefix="vcax_gold_",
    petsc_options={"ksp_type": "preonly", "pc_type": "lu"})
uh = problem.solve()

V1 = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
ip = V1.element.interpolation_points
ip = ip() if callable(ip) else ip
if os.environ.get("FENICS_STRESS", "interp") == "project":
    # Legal reading of "projected onto the P1 space": a least-squares (L2)
    # projection, which averages the element-wise discontinuous P2 stress. The
    # P2 stress is linear per element, so a DG1 copy of it is exact.
    Vdg = functionspace(domain, basix.ufl.element("DG", "triangle", 1))
    ip_dg = Vdg.element.interpolation_points
    ip_dg = ip_dg() if callable(ip_dg) else ip_dg
    t1, v1 = ufl.TrialFunction(V1), ufl.TestFunction(V1)
    mass = ufl.inner(t1, v1) * ufl.dx

    def l2_project(component):
        sdg = Function(Vdg)
        sdg.interpolate(fem.Expression(component, ip_dg))
        return LinearProblem(
            mass, ufl.inner(sdg, v1) * ufl.dx, petsc_options_prefix="vcax_proj_",
            petsc_options={"ksp_type": "preonly", "pc_type": "lu"}).solve()

    sxx = l2_project(sigma(uh)[0, 0])
    syy = l2_project(sigma(uh)[1, 1])
else:
    sxx = Function(V1)
    sxx.interpolate(fem.Expression(sigma(uh)[0, 0], ip))
    syy = Function(V1)
    syy.interpolate(fem.Expression(sigma(uh)[1, 1], ip))
ux = Function(V1)
ux.interpolate(fem.Expression(uh[0], ip))
uy = Function(V1)
uy.interpolate(fem.Expression(uh[1], ip))

xy = V1.tabulate_dof_coordinates()
(ax, ay, ra), (bx, by, rb) = HOLES["A"], HOLES["B"]
arc_a = np.abs(np.hypot(xy[:, 0] - ax, xy[:, 1] - ay) - ra) <= 1e-3
arc_b = np.abs(np.hypot(xy[:, 0] - bx, xy[:, 1] - by) - rb) <= 1e-3
loaded = xy[:, 0] >= W - 1e-3
sxx_a = float(np.max(sxx.x.array[arc_a])) if arc_a.any() else 0.0
syy_b = float(np.max(syy.x.array[arc_b])) if arc_b.any() else 0.0
ux_mean = float(np.mean(ux.x.array[loaded])) if loaded.any() else 0.0
uy_mean = float(np.mean(uy.x.array[loaded])) if loaded.any() else 0.0

with open("summary.txt", "w") as fh:
    fh.write(f"{sxx_a:.6f}, {syy_b:.6f}, {ux_mean:.6f}, {uy_mean:.6f}\n")
print("sxx_A =", sxx_a, " syy_B =", syy_b,
      " ux_mean =", ux_mean, " uy_mean =", uy_mean)
'''


def _run(env: str = "", after: str = "") -> str:
    prefix = f"{env} " if env else ""
    tail = f"\n{after}\n" if after else ""
    return (
        "set -e\n"
        "cd /home/user/Desktop\n"
        "cat > /tmp/solve.py <<'PYEOF'\n"
        + SOLVER
        + "\nPYEOF\n"
        "cp /tmp/solve.py solve.py\n"
        + prefix + "python3 /tmp/solve.py\n"
        + tail
    )


# Mesh size knobs, measured on the image (2026-11-28). N14 has 3696 triangles
# (floor 4000); N15 has 38 boundary edges on the arc of hole B (floor 60); N16
# has 54 on hole A. A1-A3 and A4 pass every floor. The L2-projected stress (A4)
# differs from the vertex-interpolated one by 0.2 % (sxx_A) and 1.2 % (syy_B),
# inside the re-solve tolerance of 2 %.
GOLD = _run()
FINER = _run(env="FENICS_HMAX=2.5 FENICS_NEAR=0.35")
DIST_FIELD = _run(env="FENICS_MESH=dist")
COARSER = _run(env="FENICS_HMAX=4.5 FENICS_NEAR=0.55 FENICS_GROW=10")
L2_PROJECT = _run(env="FENICS_STRESS=project")
UNIT_THICKNESS = _run(env="FENICS_FORM=none")
LOAD_ONLY_THICKNESS = _run(env="FENICS_FORM=load_only")
# Too fine for the verifier's direct solve: rejected on the element count alone.
# No solve on that mesh; the summary is a placeholder, so the count is the only
# thing the verifier can object to.
OVERSIZED = _run(env="FENICS_HMAX=1.5 FENICS_NEAR=0.10 FENICS_SKIP_SOLVE=1",
                 after="printf '1, 2, 3, 4\\n' > summary.txt")

WRONG_ANGLE = _run(env="FENICS_ANGLE=60")
RAW_TRACTION = _run(env="FENICS_RAW_TRACTION=1")
E_MPA = _run(env="FENICS_E_UNIT=mpa")
NO_HOLE_B = _run(env="FENICS_SKIP_HOLE=B")
HALF = _run(env="FENICS_HALF=1")
WRONG_DIAMETER = _run(env="FENICS_RB=8.0")
SWAPPED_HOLES = _run(env="FENICS_SWAP_HOLES=1")
COARSE = _run(env="FENICS_HMAX=10.0 FENICS_NEAR=1.0")
COARSE_ARC_B = _run(env="FENICS_HMAX=2.5 FENICS_NEAR=1.0")
COARSE_ARC_A = _run(env="FENICS_HMAX=2.5 FENICS_NEAR=1.4")

SWAP = _run(after=(
    "python3 - <<'PY'\n"
    "line = [x.strip() for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(', '.join((line[1], line[0], line[2], line[3])) + '\\n')\n"
    "PY"))
SWAP_U = _run(after=(
    "python3 - <<'PY'\n"
    "line = [x.strip() for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(', '.join((line[0], line[1], line[3], line[2])) + '\\n')\n"
    "PY"))
FABRICATE = _run(after=(
    "python3 - <<'PY'\n"
    "line = [float(x) for x in open('summary.txt').read().split(',')]\n"
    "open('summary.txt', 'w').write(', '.join(f'{x * 1.10:.6f}' for x in line) + '\\n')\n"
    "PY"))
ZERO_MESH = _run(after=": > mesh.msh")
BAD_SUMMARY = _run(after="printf '1, 2, 3\\n' > summary.txt")

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '400.0, 100.0, 0.150, 0.050' > summary.txt
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
    "N7 wrong hole B diameter": "tampered_input",
    "N11 fabricated summary (+10%)": "fabricated_field",
    "N12 zero-byte mesh": "skipped_steps",
    "N17 metrics only": "metrics_only",
    "N18 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (finer mesh)", FINER, ("true",)),
    ("A2 alternative legal (distance-field mesh)", DIST_FIELD, ("true",)),
    ("A3 alternative legal (coarser size field)", COARSER, ("true",)),
    ("A4 alternative legal (L2-projected stress)", L2_PROJECT, ("true",)),
    ("A5 alternative legal (unit-thickness weak form)", UNIT_THICKNESS, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 wrong load angle (60 deg)", WRONG_ANGLE, ("false",)),
    ("N3 force used as traction (no kN conversion)", RAW_TRACTION, ("false",)),
    ("N4 modulus read as MPa", E_MPA, ("false",)),
    ("N5 hole B missing", NO_HOLE_B, ("false",)),
    ("N6 half model (wrong bounding box)", HALF, ("false",)),
    ("N7 wrong hole B diameter", WRONG_DIAMETER, ("false",)),
    ("N8 hole centres swapped", SWAPPED_HOLES, ("false",)),
    ("N9 swapped stress fields", SWAP, ("false",)),
    ("N10 swapped displacement fields", SWAP_U, ("false",)),
    ("N11 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N12 zero-byte mesh", ZERO_MESH, ("false",)),
    ("N13 malformed summary (three numbers)", BAD_SUMMARY, ("false",)),
    ("N14 coarse mesh (too few triangles)", COARSE, ("false",)),
    ("N15 too few edges on hole B arc", COARSE_ARC_B, ("false",)),
    ("N16 too few edges on hole A arc", COARSE_ARC_A, ("false",)),
    ("N17 metrics only", METRICS_ONLY, ("false",)),
    ("N18 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N19 thickness on the load only", LOAD_ONLY_THICKNESS, ("false",)),
    ("N20 oversized mesh (more than 80000 triangles)", OVERSIZED, ("false",)),
]
