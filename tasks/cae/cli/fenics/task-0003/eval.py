#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0003 (hole-radius sizing).

Quantified-score task (spec/02 L5): the agent chooses the radius R of a central
circular hole to remove mass while keeping the peak axial stress on the hole
within 400 MPa.

Stages:
  stage 1 (feasibility gate)  mesh conformance (quarter plate, circular hole,
                              bounds, refinement), summary agreement with the
                              mesh geometry, and the 400 MPa stress limit on
                              the verifier's own re-solve. Any violation ->
                              0.000000 (no partial credit).
  stage 2 (quality score)     normalized mass reduction from the R=10 mm
                              baseline to the best feasible design at the
                              stress limit (R ~= 31.56 mm).

L3 rebuilds the plane-stress BVP in dolfinx ON THE SUBMITTED MESH and uses the
verifier's own re-solve for the gate and the score; the agent's summary is only
cross-checked, never trusted.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3", "L5")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))

REQUIRED_ARTIFACTS = ["mesh.msh", "summary.txt", "solve.py"]

# ---- pinned design (task instruction) ----
W, H = 100.0, 100.0
SIGMA_LOAD = 100.0
E_YOUNG, NU = 210000.0, 0.3
THICKNESS = 1.0
R_BOUNDS = (5.0, 35.0)
SIGMA_LIMIT = 400.0
R_BASELINE = 10.0
# largest R whose peak stress stays at the limit (pinned band below)
R_OPT = 31.56

# ---- mesh / geometry tolerances ----
GEOM_ABS_TOL = 0.5
RADIUS_ABS_TOL = 0.05
MIN_ARC_EDGES = 80
MIN_ELEMENTS = 3000

# ---- pinned peak-stress band, measured on this image (MPa) ----
# R -> sigma_xx_max on the hole boundary; linear interpolation between points.
PINNED_R = (10.0, 20.0, 25.0, 30.0, 35.0)
PINNED_SIGMA = (308.464544, 336.024634, 358.331205, 387.841918, 426.789979)
PINNED_REL_TOL = 5.0e-2

# ---- tolerances ----
RESOLVE_REL_TOL = 2.0e-2     # summary vs independent re-solve
SUMMARY_REL_TOL = 1.0e-3     # reported radius vs mesh geometry


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-9) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * abs(target))


# ---------------------------------------------------------------- summary
def parse_summary(summary_path: Path) -> tuple[float, float, float] | None:
    parts = [p.strip() for p in summary_path.read_text(errors="ignore").strip().split(",")]
    if len(parts) != 3:
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


def _arc_nodes(points, triangles) -> set[int]:
    """Boundary nodes that are not on the outer 100 x 100 rectangle."""
    edges = _edge_counts(triangles)
    nodes: set[int] = set()
    for (a, b), count in edges.items():
        if count != 1:
            continue
        mx = 0.5 * (points[a, 0] + points[b, 0])
        my = 0.5 * (points[a, 1] + points[b, 1])
        on_outer = (abs(mx) <= 1e-6 or abs(mx - W) <= 1e-6
                    or abs(my) <= 1e-6 or abs(my - H) <= 1e-6)
        if not on_outer:
            nodes.add(a)
            nodes.add(b)
    return nodes


def l2_mesh_conformance(points, triangles) -> float | None:
    import numpy as np

    if len(triangles) < MIN_ELEMENTS:
        _fail(f"mesh has {len(triangles)} triangles, fewer than {MIN_ELEMENTS}")
        return None
    xs, ys = points[:, 0], points[:, 1]
    if (abs(xs.min()) > GEOM_ABS_TOL or abs(xs.max() - W) > GEOM_ABS_TOL
            or abs(ys.min()) > GEOM_ABS_TOL or abs(ys.max() - H) > GEOM_ABS_TOL):
        _fail("mesh bounding box does not match the 100 x 100 mm quarter plate")
        return None

    arc = np.asarray(sorted(_arc_nodes(points, triangles)), dtype=np.int64)
    if arc.size == 0:
        _fail("no hole-boundary nodes found")
        return None
    radii = np.hypot(xs, ys)
    r = float(radii[arc].max())
    if not (R_BOUNDS[0] - 1e-6 <= r <= R_BOUNDS[1] + 1e-6):
        _fail(f"hole radius R={r:.4f} outside {R_BOUNDS}")
        return None
    if np.any(np.abs(radii[arc] - r) > RADIUS_ABS_TOL):
        _fail("hole-boundary nodes do not lie on one circle")
        return None
    if np.any(radii < r - RADIUS_ABS_TOL):
        _fail("mesh nodes lie inside the circular hole")
        return None

    edges = _edge_counts(triangles)
    arc_set = set(int(i) for i in arc)
    arc_edges = sum(1 for (u, v), count in edges.items()
                    if count == 1 and u in arc_set and v in arc_set)
    if arc_edges < MIN_ARC_EDGES:
        _fail(f"only {arc_edges} boundary edges on the hole arc; need >= {MIN_ARC_EDGES}")
        return None
    return r


# ---------------------------------------------------------------- L3
def resolve(points, triangles, r_hole: float) -> tuple[float, float] | None:
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
    aa = ufl.inner(sigma(u), eps(v)) * ufl.dx
    t = ufl.as_vector((SIGMA_LOAD, 0.0))
    L = ufl.inner(t, v) * THICKNESS * ds(1)

    from dolfinx.fem.petsc import LinearProblem  # explicit submodule import
    problem = LinearProblem(aa, L, bcs=[bc_x, bc_y],
                            petsc_options_prefix="vcax_eval_",
                            petsc_options={"ksp_type": "preonly",
                                           "pc_type": "lu"})
    uh = problem.solve()

    V1 = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
    ip = _ipoints(V1)
    sxx = Function(V1)
    sxx.interpolate(fem.Expression(sigma(uh)[0, 0], ip))
    ux = Function(V1)
    ux.interpolate(fem.Expression(uh[0], ip))

    xy = V1.tabulate_dof_coordinates()
    radii = np.hypot(xy[:, 0], xy[:, 1])
    on_hole = np.abs(radii - r_hole) <= 1e-3
    loaded = xy[:, 0] >= W - 1e-3
    if not on_hole.any() or not loaded.any():
        return None
    sigma_peak = float(np.max(sxx.x.array[on_hole]))
    ux_peak = float(np.max(ux.x.array[loaded]))
    return sigma_peak, ux_peak


# ---------------------------------------------------------------- L1
def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


# ---------------------------------------------------------------- verdict
def evaluate() -> float:
    if not l1_completeness():
        return 0.0
    points, triangles = load_mesh(AGENT_ROOT / "mesh.msh")
    r_mesh = l2_mesh_conformance(points, triangles)
    if r_mesh is None:
        return 0.0

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        _fail("summary.txt must be three comma-separated numbers: R, sigma_xx_max, ux_max")
        return 0.0
    r_s, sigma_s, ux_s = summary
    if not close_enough(r_s, r_mesh, SUMMARY_REL_TOL):
        _fail("reported hole radius does not match the submitted mesh")
        return 0.0

    resolved = resolve(points, triangles, r_mesh)
    if resolved is None:
        _fail("independent re-solve failed to evaluate the required quantities")
        return 0.0
    sigma_b, ux_b = resolved

    # A vs B: reported numbers must match the physics of the submitted mesh.
    if not close_enough(sigma_s, sigma_b, RESOLVE_REL_TOL):
        _fail("sigma_xx_max does not match the independent re-solve of mesh.msh")
        return 0.0
    if not close_enough(ux_s, ux_b, RESOLVE_REL_TOL):
        _fail("ux_max does not match the independent re-solve of mesh.msh")
        return 0.0

    # Physics net: how the peak stress grows with the hole radius on this image.
    import numpy as np
    sigma_ref = float(np.interp(r_mesh, PINNED_R, PINNED_SIGMA))
    if not close_enough(sigma_b, sigma_ref, PINNED_REL_TOL):
        _fail(f"peak stress {sigma_b:.2f} MPa is outside the pinned band "
              f"({sigma_ref:.2f} MPa +/- {PINNED_REL_TOL:.0%})")
        return 0.0
    if not (0.0 < ux_s < 1.0):
        _fail("ux_max is outside the physically plausible range")
        return 0.0

    # ---- stage 1: feasibility gate (no partial credit)
    if sigma_b > SIGMA_LIMIT * (1.0 + 1e-9):
        _fail(f"peak stress {sigma_b:.2f} MPa exceeds the {SIGMA_LIMIT} MPa limit")
        return 0.0

    # ---- stage 2: quality score (normalized mass reduction)
    score = (r_mesh**2 - R_BASELINE**2) / (R_OPT**2 - R_BASELINE**2)
    return max(0.0, min(1.0, score))


def main() -> int:
    try:
        score = evaluate()
    except Exception as exc:  # noqa: BLE001 - verifier must never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        score = 0.0
    print(f"{max(0.0, min(1.0, float(score))):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())