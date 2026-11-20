#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0002 (elliptical hole shape).

Quantified-score task (spec/02 L5): the agent chooses the semi-axes of a
central elliptical hole at fixed hole area and minimises the peak axial stress
on the hole boundary.

Stages:
  stage 1 (feasibility gate)  mesh conformance (quarter plate, elliptical hole,
                              fixed area, bounds, refinement) and summary
                              agreement with the mesh geometry. Any violation
                              -> 0.000000 (no partial credit).
  stage 2 (quality score)     normalized reduction of the peak stress from
                              the circular baseline (Kt = 3) toward the best
                              ellipse in the box (Kt = 1.5).

L3 rebuilds the plane-stress BVP in dolfinx ON THE SUBMITTED MESH and uses the
verifier's own re-solve for the score; the agent's summary is only
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
AREA_TARGET = 100.0          # a*b, fixed hole area pi*a*b = pi*10^2
A_BOUNDS = (5.0, 20.0)
B_BOUNDS = (5.0, 20.0)

# ---- mesh / geometry tolerances ----
GEOM_ABS_TOL = 0.5
ELLIPSE_TOL = 2.0e-3
AREA_REL_TOL = 5.0e-3
MIN_ARC_EDGES = 80
MIN_ELEMENTS = 3000

# ---- scoring anchors, measured on this image ----
# circular baseline (a=b=10) from the task-0001 reference solve
SIGMA_CIRCLE = 308.464544
# infinite-plate Inglis optimum for a/b = 4: Kt = 1 + 2b/a = 1.5
SIGMA_OPT = 1.5 * SIGMA_LOAD

# ---- tolerances ----
RESOLVE_REL_TOL = 2.0e-2     # summary vs independent re-solve
SUMMARY_REL_TOL = 1.0e-3     # reported semi-axes vs mesh geometry
INGLIS_REL_TOL = 8.0e-2      # re-solve vs Inglis band (physics net)


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
    """Boundary nodes that are not on the outer 100 x 100 rectangle.

    Works from edge midpoints so the two arc endpoints, which sit on the
    symmetry axes, are still classified as hole boundary.
    """
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


def l2_mesh_conformance(points, triangles) -> tuple[float, float] | None:
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
    a = float(xs[arc].max())
    b = float(ys[arc].max())
    if not (A_BOUNDS[0] - 1e-6 <= a <= A_BOUNDS[1] + 1e-6):
        _fail(f"semi-axis a={a:.4f} outside {A_BOUNDS}")
        return None
    if not (B_BOUNDS[0] - 1e-6 <= b <= B_BOUNDS[1] + 1e-6):
        _fail(f"semi-axis b={b:.4f} outside {B_BOUNDS}")
        return None
    if abs(a * b - AREA_TARGET) > AREA_REL_TOL * AREA_TARGET:
        _fail(f"hole area a*b={a * b:.4f} differs from the fixed area {AREA_TARGET}")
        return None

    q = np.hypot(xs / a, ys / b)
    if np.any(q < 1.0 - ELLIPSE_TOL):
        _fail("mesh nodes lie inside the elliptical hole")
        return None
    if np.any(np.abs(q[arc] - 1.0) > ELLIPSE_TOL):
        _fail("hole-boundary nodes do not lie on the ellipse x^2/a^2 + y^2/b^2 = 1")
        return None

    edges = _edge_counts(triangles)
    arc_set = set(int(i) for i in arc)
    arc_edges = sum(1 for (u, v), count in edges.items()
                    if count == 1 and u in arc_set and v in arc_set)
    if arc_edges < MIN_ARC_EDGES:
        _fail(f"only {arc_edges} boundary edges on the hole arc; need >= {MIN_ARC_EDGES}")
        return None
    return a, b


# ---------------------------------------------------------------- L3
def resolve(points, triangles, a: float, b: float) -> tuple[float, float] | None:
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
    q = np.hypot(xy[:, 0] / a, xy[:, 1] / b)
    on_hole = np.abs(q - 1.0) <= 1e-3
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
    import math

    if not l1_completeness():
        return 0.0
    points, triangles = load_mesh(AGENT_ROOT / "mesh.msh")
    design = l2_mesh_conformance(points, triangles)
    if design is None:
        return 0.0
    a_mesh, b_mesh = design

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        _fail("summary.txt must be four comma-separated numbers: a, b, sigma_xx_max, ux_max")
        return 0.0
    a_s, b_s, sigma_s, ux_s = summary
    if not close_enough(a_s, a_mesh, SUMMARY_REL_TOL):
        _fail("reported semi-axis a does not match the submitted mesh")
        return 0.0
    if not close_enough(b_s, b_mesh, SUMMARY_REL_TOL):
        _fail("reported semi-axis b does not match the submitted mesh")
        return 0.0

    resolved = resolve(points, triangles, a_mesh, b_mesh)
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

    # Physics net: Inglis Kt = 1 + 2b/a for a load along x (peak at (0, b)).
    kt = 1.0 + 2.0 * b_mesh / a_mesh
    sigma_ref = kt * SIGMA_LOAD
    if not close_enough(sigma_b, sigma_ref, INGLIS_REL_TOL):
        _fail(f"peak stress {sigma_b:.2f} MPa is outside the Inglis band "
              f"({sigma_ref:.2f} MPa +/- {INGLIS_REL_TOL:.0%})")
        return 0.0
    if not (0.0 < ux_s < 1.0):
        _fail("ux_max is outside the physically plausible range")
        return 0.0

    score = (SIGMA_CIRCLE - sigma_b) / (SIGMA_CIRCLE - SIGMA_OPT)
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