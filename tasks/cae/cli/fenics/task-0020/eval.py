#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0020 (elliptical hole, two load cases).

Quantified-score task (spec/02 L5): the agent chooses the semi-axes of a
central elliptical hole at fixed hole area and minimises the worst-case stress
index over TWO independent load cases:
  LC1  uniform traction (100, 0) MPa on the edge x = 100
  LC2  uniform traction (0, 40) MPa on the edge y = 100
The index is K = max(s1, s2) / 100: the larger of the two peak stresses, s1
being the peak sigma_xx on the hole boundary under LC1 and s2 the peak
sigma_yy under LC2, referred to one common reference stress.

Stages:
  stage 1 (feasibility gate)  mesh conformance (quarter plate, elliptical hole,
                              fixed area, bounds, refinement), summary
                              agreement with the mesh geometry, with the
                              independent re-solve and with the Inglis physics
                              of each load case. Any violation -> 0.000000
                              (no partial credit).
  stage 2 (quality score)     normalized reduction of K from the circular
                              baseline (K_CIRCLE) toward the best ellipse in
                              the design box (K_BEST).

L3 rebuilds the plane-stress BVP in dolfinx ON THE SUBMITTED MESH, solves the
two load cases with one bilinear form and two linear forms, and uses the
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
SIGMA_LOAD_X = 100.0          # LC1: traction on the edge x = 100
SIGMA_LOAD_Y = 40.0           # LC2: traction on the edge y = 100
E_YOUNG, NU = 210000.0, 0.3
THICKNESS = 1.0
AREA_TARGET = 100.0          # a*b, fixed hole area pi*a*b = pi*10^2
A_BOUNDS = (5.0, 20.0)
B_BOUNDS = (5.0, 20.0)

# Design index K = max(s1, s2) / K_REF: both peaks are referred to ONE
# reference stress (the LC1 nominal stress). Referring each peak to its own
# nominal stress instead, max(s1 / 100, s2 / 40), makes the circle the optimum
# (max(1 + 2/r, 1 + 2r) >= 3 for every r) and every design would score 0.
K_REF = SIGMA_LOAD_X

# ---- mesh / geometry tolerances ----
GEOM_ABS_TOL = 0.5
ELLIPSE_TOL = 2.0e-3
AREA_REL_TOL = 5.0e-3
MIN_ARC_EDGES = 80
MIN_ELEMENTS = 3000
MAX_ELEMENTS = 80000     # stated in the instruction; bounds the verifier's direct solve

# ---- scoring anchors, measured on this image with the re-solve below ----
# circular baseline (a=b=10): K is 3.085-3.087 over 87-172 arc edges, so any
# legal circular mesh scores at most 0.0002
K_CIRCLE = 3.085
# best ellipse in the design box (a=14.05, b=7.1174): the infinite-plate
# estimate is a/b=2 with K=2.0; the finite quarter plate raises both peaks by
# 2-5 % and moves the crossing. K varies by less than 0.01 with the mesh
# density once the mesh is legal.
K_BEST = 2.062

# ---- tolerances ----
RESOLVE_REL_TOL = 2.0e-2     # summary vs independent re-solve
SUMMARY_REL_TOL = 1.0e-3     # reported semi-axes vs mesh geometry
INGLIS_REL_TOL = 8.0e-2      # re-solve vs Inglis band, per load case (physics net)


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
    # The mesh nodes are the points its elements use. A geometry builder may
    # leave construction points in the file (an ellipse centre, for example);
    # they belong to no element, change no result, and are not part of the mesh.
    used, inverse = np.unique(triangles, return_inverse=True)
    return points[used], inverse.reshape(triangles.shape)


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
    if len(triangles) > MAX_ELEMENTS:
        _fail(f"mesh has {len(triangles)} triangles, more than {MAX_ELEMENTS}")
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
    """Re-solve both plane-stress load cases on the submitted mesh with dolfinx."""
    import numpy as np
    from mpi4py import MPI
    import basix.ufl
    import ufl
    from dolfinx import fem
    from dolfinx.mesh import (create_mesh, locate_entities_boundary,
                              meshtags)
    from dolfinx.fem import functionspace, Function, dirichletbc
    from dolfinx.fem import locate_dofs_topological
    from dolfinx.fem.petsc import LinearProblem  # explicit submodule import

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
    top = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[1], H))
    Vx, Vy = V.sub(0), V.sub(1)
    bcs = [dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx),
           dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, bottom), Vy)]

    # right edge -> tag 1 (LC1), top edge -> tag 2 (LC2); the two sets are disjoint
    facets = np.concatenate([right, top]).astype(np.int32)
    tags = np.concatenate([np.full(len(right), 1, dtype=np.int32),
                           np.full(len(top), 2, dtype=np.int32)])
    order = np.argsort(facets)
    mt = meshtags(domain, 1, facets[order], tags[order])
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
    # one bilinear form, one linear form per load case, the same Dirichlet
    # conditions both times
    L_lc1 = ufl.inner(ufl.as_vector((SIGMA_LOAD_X, 0.0)), v) * THICKNESS * ds(1)
    L_lc2 = ufl.inner(ufl.as_vector((0.0, SIGMA_LOAD_Y)), v) * THICKNESS * ds(2)

    V1 = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
    ip = _ipoints(V1)
    xy = V1.tabulate_dof_coordinates()
    q = np.hypot(xy[:, 0] / a, xy[:, 1] / b)
    on_hole = np.abs(q - 1.0) <= 1e-3
    if not on_hole.any():
        return None

    peaks = []
    for load, component in ((L_lc1, 0), (L_lc2, 1)):
        problem = LinearProblem(aa, load, bcs=bcs,
                                petsc_options_prefix="vcax_eval20_",
                                petsc_options={"ksp_type": "preonly",
                                               "pc_type": "lu"})
        uh = problem.solve()
        stress = Function(V1)
        stress.interpolate(fem.Expression(sigma(uh)[component, component], ip))
        peaks.append(float(np.max(stress.x.array[on_hole])))
    return peaks[0], peaks[1]


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
    design = l2_mesh_conformance(points, triangles)
    if design is None:
        return 0.0
    a_mesh, b_mesh = design

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        _fail("summary.txt must be four comma-separated numbers: a, b, s1, s2")
        return 0.0
    a_s, b_s, s1_s, s2_s = summary
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
    s1_b, s2_b = resolved

    # A vs B: reported numbers must match the physics of the submitted mesh.
    if not close_enough(s1_s, s1_b, RESOLVE_REL_TOL):
        _fail("s1 does not match the independent re-solve of mesh.msh under LC1")
        return 0.0
    if not close_enough(s2_s, s2_b, RESOLVE_REL_TOL):
        _fail("s2 does not match the independent re-solve of mesh.msh under LC2")
        return 0.0

    # ---- stage 1: physics net (Inglis, infinite plate), one band per load
    # case. a is the semi-axis along x, b the one along y.
    # LC1 (x-traction): peak sigma_xx at (0, b) = SIGMA_LOAD_X (1 + 2b/a).
    # LC2 (y-traction): peak sigma_yy at (a, 0) = SIGMA_LOAD_Y (1 + 2a/b).
    # With r = a/b and both peaks divided by K_REF = 100:
    #   K1(r) = 1 + 2/r decreases with r, K2(r) = 0.4 (1 + 2r) increases.
    # K = max(K1, K2) is minimal where they cross, near r = 2 (measured:
    # a = 14.05, K = 2.062). The optimum is interior: the best design for LC1
    # alone (r = 4) measures K = 3.80; at r = 0.25, K1 is about 9.
    for name, measured, inglis in (
            ("s1", s1_b, SIGMA_LOAD_X * (1.0 + 2.0 * b_mesh / a_mesh)),
            ("s2", s2_b, SIGMA_LOAD_Y * (1.0 + 2.0 * a_mesh / b_mesh))):
        if not close_enough(measured, inglis, INGLIS_REL_TOL):
            _fail(f"{name} = {measured:.2f} MPa is outside the Inglis band "
                  f"({inglis:.2f} MPa +/- {INGLIS_REL_TOL:.0%})")
            return 0.0

    # ---- stage 2: quality score from the verifier's own re-solve
    k_worst = max(s1_b, s2_b) / K_REF
    score = (K_CIRCLE - k_worst) / (K_CIRCLE - K_BEST)
    return max(0.0, min(1.0, score))


def main() -> int:
    try:
        score = evaluate()
    except (Exception, SystemExit) as exc:  # verifier must never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        score = 0.0
    print(f"{max(0.0, min(1.0, float(score))):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
