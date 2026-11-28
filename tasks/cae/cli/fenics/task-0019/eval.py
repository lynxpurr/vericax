#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0019 (full plate with two holes, oblique edge load).

Observation-reconstruct task. The agent reads an engineering drawing (plate
outline, two through holes on the mid-height line, supports, a total force at
an angle, material in GPa) and a brief, then delivers the mesh, its solve
script and four numbers. This verifier implements

  L1  artifacts present and non-empty
  L2  mesh conformance (full plate, both holes, per-hole arc resolution,
      element count)
  L3  independent re-solve: the plane-stress problem is rebuilt in dolfinx ON
      THE SUBMITTED MESH and solved here, with ux = 0 on the left edge, uy = 0
      on the bottom edge, the total force distributed as a uniform traction
      over the whole right edge, and the plate thickness carried in both the
      stiffness and the load (a mismatch there scales the whole solution).

The comparison is

  A  the agent's summary.txt
  B  the verifier's independent re-solve of the submitted mesh   (tight)
  C  pinned reference values from the same image                 (loose)
followed by a plausibility net on the reported numbers.

Quantity choice: the peak sigma_xx on the arc of the larger hole and the peak
sigma_yy on the arc of the smaller hole (stress-concentration quantities that
bind geometry, load direction and units), and the mean displacements of the
loaded edge (smooth functionals that bind the material, the supports and the
force-to-traction conversion).
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))

REQUIRED_ARTIFACTS = ["mesh.msh", "summary.txt", "solve.py"]

# summary fields, in the order they are written
NAMES = ("sxx_A", "syy_B", "ux_mean", "uy_mean")

# ---- pinned design (drawing.svg) ----
W, H = 240.0, 120.0                   # plate width / height (mm)
THICKNESS = 2.0                       # mm
HOLES = {"A": (70.0, 60.0, 12.0), "B": (170.0, 60.0, 6.0)}   # centre x, y, radius (mm)
FORCE = 36.0e3                        # total force at the middle of the right edge (N)
ANGLE_DEG = 30.0                      # its direction, degrees above the +x axis
E_YOUNG, NU = 210000.0, 0.3           # MPa (210 GPa), Poisson's ratio

# The force is carried by a uniform traction over the right edge (N/mm^2 = MPa):
# F in N, H and t in mm.
TRACTION = FORCE / (H * THICKNESS)
TX = TRACTION * math.cos(math.radians(ANGLE_DEG))
TY = TRACTION * math.sin(math.radians(ANGLE_DEG))

# ---- pinned reference, filled from the same VM image (ground_truth/) ----
# One line per summary field, in summary order: scripts/audit_task.py zips the
# EXPECTED_* lines with the gold summary values.
# Never hand-fill them: the audit bakes them from ground_truth/summary.txt.
EXPECTED_SXX_A = None
EXPECTED_SYY_B = None
EXPECTED_UX_MEAN = None
EXPECTED_UY_MEAN = None

# ---- tolerances ----
RESOLVE_REL_TOL = 2.0e-2    # A vs B: same mesh, evaluation-convention noise
PINNED_REL_TOL = 5.0e-2     # B vs C: mesh/refinement differences
GEOM_ABS_TOL = 0.5          # mesh bounding box tolerance (mm)
HOLE_ABS_TOL = 0.05         # node-vs-arc tolerance (mm)
NODE_TOL = 1e-3            # a node this close to a reference curve (hole arc,
                           # loaded edge) counts as on it (mm)
MIN_ARC_EDGES = 60          # boundary edges needed on EACH hole arc
MIN_ELEMENTS = 4000
MAX_ELEMENTS = 80000     # stated in the instruction; bounds the verifier's direct solve
STRESS_CAP = 10.0 * TRACTION    # plausibility net: 0 < each reported stress < cap (MPa)


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-9) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * abs(target))


# ---------------------------------------------------------------- summary
def parse_summary(summary_path: Path) -> tuple[float, float, float, float] | None:
    parts = [p.strip() for p in summary_path.read_text(errors="ignore").strip().split(",")]
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


# ---------------------------------------------------------------- mesh
def load_mesh(mesh_path: Path):
    import meshio
    import numpy as np

    m = meshio.read(mesh_path)
    triangles = None
    for block in m.cells:
        if block.type == "triangle":
            triangles = np.asarray(block.data, dtype=np.int64)
            break
    if triangles is None or len(triangles) == 0:
        raise ValueError("no triangular elements in mesh")
    points = np.asarray(m.points, dtype=float)
    if points.shape[1] == 3:
        # accept a flat extrusion; otherwise reject
        if np.any(np.abs(points[:, 2]) > 1e-9):
            raise ValueError("mesh is not planar (z != 0)")
        points = points[:, :2]
    return points, triangles


def _edge_counts(triangles):
    from collections import Counter
    edges = Counter()
    for a, b, c in triangles:
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))] += 1
    return edges


def _arc_edges(points, triangles, cx: float, cy: float, radius: float):
    """(number of nodes on the arc, number of boundary edges with both ends on it)."""
    import numpy as np

    radii = np.hypot(points[:, 0] - cx, points[:, 1] - cy)
    on_arc = np.abs(radii - radius) <= NODE_TOL
    count = sum(1 for (a, b), n in _edge_counts(triangles).items()
                if n == 1 and on_arc[a] and on_arc[b])
    return int(on_arc.sum()), count


def l2_mesh_conformance(points, triangles) -> bool:
    import numpy as np

    if len(triangles) < MIN_ELEMENTS:
        return _fail(f"mesh has {len(triangles)} triangles, fewer than {MIN_ELEMENTS}")
    if len(triangles) > MAX_ELEMENTS:
        return _fail(f"mesh has {len(triangles)} triangles, more than {MAX_ELEMENTS}")
    xs, ys = points[:, 0], points[:, 1]
    if (abs(xs.min()) > GEOM_ABS_TOL or abs(xs.max() - W) > GEOM_ABS_TOL
            or abs(ys.min()) > GEOM_ABS_TOL or abs(ys.max() - H) > GEOM_ABS_TOL):
        return _fail("mesh bounding box does not match the 240 x 120 mm full plate")
    for name, (cx, cy, radius) in HOLES.items():
        radii = np.hypot(xs - cx, ys - cy)
        if radii.min() < radius - HOLE_ABS_TOL:
            return _fail(f"mesh nodes inside hole {name} "
                         f"(min distance {radii.min():.3f} mm, radius {radius:g} mm)")
        if not np.any(np.abs(radii - radius) <= NODE_TOL):
            return _fail(f"no mesh nodes on the arc of hole {name} "
                         f"(centre {cx:g}, {cy:g}; radius {radius:g} mm)")
        n_nodes, n_edges = _arc_edges(points, triangles, cx, cy, radius)
        if n_edges < MIN_ARC_EDGES:
            return _fail(f"only {n_edges} boundary edges on the arc of hole {name} "
                         f"({n_nodes} nodes); need >= {MIN_ARC_EDGES}")
    return True


# ---------------------------------------------------------------- L3
def resolve(points, triangles) -> tuple[float, float, float, float] | None:
    """Re-solve the plane-stress BVP on the submitted mesh with dolfinx."""
    import numpy as np
    from mpi4py import MPI
    import basix.ufl
    import ufl
    from dolfinx import fem
    from dolfinx.mesh import (create_mesh, locate_entities_boundary,
                              meshtags)
    from dolfinx.fem import functionspace, Function, dirichletbc
    from dolfinx.fem import locate_dofs_topological

    def _ipoints(V):
        ip = V.element.interpolation_points
        return ip() if callable(ip) else ip

    # 2D geometry: gradient/sym stay 2x2 and the plane-stress form is valid
    coords = np.ascontiguousarray(points, dtype=float)
    cells = triangles.astype(np.int64)

    coord_el = basix.ufl.element("Lagrange", "triangle", 1, shape=(2,))
    domain = create_mesh(MPI.COMM_WORLD, cells, coord_el, coords)
    V = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 2, shape=(2,)))

    left = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], 0.0))
    bottom = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[1], 0.0))
    right = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], W))
    Vx, Vy = V.sub(0), V.sub(1)
    bc_x = dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx)
    bc_y = dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, bottom), Vy)

    mt = meshtags(domain, 1, right, np.full(len(right), 1, dtype=np.int32))
    ds = ufl.Measure("ds", domain=domain, subdomain_data=mt)

    mu = E_YOUNG / (2.0 * (1.0 + NU))
    lam = E_YOUNG * NU / ((1.0 + NU) * (1.0 - 2.0 * NU))
    lam_star = 2.0 * lam * mu / (lam + 2.0 * mu)  # plane stress

    def eps(w):
        return ufl.sym(ufl.grad(w))

    def sigma(w):
        return 2.0 * mu * eps(w) + lam_star * ufl.tr(eps(w)) * ufl.Identity(2)

    u = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)
    # The thickness belongs to both forms (or to neither): the traction is
    # already F / (H t), so the load is t * traction per unit length of edge.
    a = ufl.inner(sigma(u), eps(v)) * THICKNESS * ufl.dx
    t = ufl.as_vector((TX, TY))
    L = ufl.inner(t, v) * THICKNESS * ds(1)

    from dolfinx.fem.petsc import LinearProblem  # explicit submodule import
    problem = LinearProblem(a, L, bcs=[bc_x, bc_y],
                            petsc_options_prefix="vcax_eval_",
                            petsc_options={"ksp_type": "preonly",
                                           "pc_type": "lu"})
    uh = problem.solve()

    V1 = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
    ip = _ipoints(V1)

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
    arc_a = np.abs(np.hypot(xy[:, 0] - ax, xy[:, 1] - ay) - ra) <= NODE_TOL
    arc_b = np.abs(np.hypot(xy[:, 0] - bx, xy[:, 1] - by) - rb) <= NODE_TOL
    loaded = xy[:, 0] >= W - NODE_TOL
    if not arc_a.any() or not arc_b.any() or not loaded.any():
        return None
    sxx_a = float(np.max(sxx.x.array[arc_a]))
    syy_b = float(np.max(syy.x.array[arc_b]))
    ux_mean = float(np.mean(ux.x.array[loaded]))
    uy_mean = float(np.mean(uy.x.array[loaded]))
    return sxx_a, syy_b, ux_mean, uy_mean


# ---------------------------------------------------------------- L1
def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False

    points, triangles = load_mesh(AGENT_ROOT / "mesh.msh")
    if not l2_mesh_conformance(points, triangles):
        return False

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        return _fail("summary.txt must be four comma-separated numbers: "
                     "sxx_A, syy_B, ux_mean, uy_mean")
    reported = dict(zip(NAMES, summary))

    resolved = resolve(points, triangles)
    if resolved is None:
        return _fail("independent re-solve failed to evaluate the required quantities")
    solved = dict(zip(NAMES, resolved))

    # A vs B: reported numbers must match the physics of the submitted mesh.
    for name in NAMES:
        if not close_enough(reported[name], solved[name], RESOLVE_REL_TOL):
            return _fail(f"{name} does not match the independent re-solve of mesh.msh")

    # B vs C: the model must be the pinned one (guards against L2 blind spots).
    pinned = dict(zip(NAMES, (EXPECTED_SXX_A, EXPECTED_SYY_B,
                              EXPECTED_UX_MEAN, EXPECTED_UY_MEAN)))
    for name in NAMES:
        if pinned[name] is not None and not close_enough(solved[name], pinned[name],
                                                         PINNED_REL_TOL):
            return _fail(f"re-solve deviates from pinned reference ({name})")

    # Plausibility net: the force pulls the loaded edge up and to the right, and
    # both reported stress components are tensile peaks far below 10 x traction.
    if not (0.0 < reported["ux_mean"] and 0.0 < reported["uy_mean"]):
        return _fail("loaded-edge mean displacements are not both positive")
    for name in ("sxx_A", "syy_B"):
        if not (0.0 < reported[name] < STRESS_CAP):
            return _fail(f"{name} is outside the plausible range "
                         f"(0, {STRESS_CAP:g} MPa)")
    return True


def main() -> int:
    try:
        ok = evaluate()
    except (Exception, SystemExit) as exc:  # verifier must never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        ok = False
    print("True" if ok else "False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
