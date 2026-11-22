#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0005 (cantilever lightening hole).

Quantified-score task (spec/02 L5): the agent chooses the radius of a circular
lightening hole in a 2D cantilever to remove mass while keeping the tip
deflection under a limit.

Stages:
  stage 1 (feasibility gate)  hole/plate mesh conformance, radius bounds, and
                              the tip-deflection limit on the verifier's own
                              re-solve. Any violation -> 0.000000.
  stage 2 (quality score)     normalized mass reduction from the R=2 mm
                              baseline to the best feasible radius.

L3 rebuilds the plane-stress BVP in dolfinx ON THE SUBMITTED MESH; the
agent's summary is only cross-checked, never trusted.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3", "L5")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))

REQUIRED_ARTIFACTS = ["mesh.msh", "summary.txt", "solve.py"]

# ---- pinned design (task instruction) ----
LENGTH, WIDTH = 100.0, 20.0
HOLE_X, HOLE_Y = 40.0, 0.0
R_BOUNDS = (2.0, 8.0)
DEFLECTION_LIMIT = 0.27
TOTAL_LOAD = -100.0
E_YOUNG, NU = 210000.0, 0.3
THICKNESS = 1.0

R_OPT = 6.4

GEOM_ABS_TOL = 0.5
RADIUS_ABS_TOL = 0.05
MIN_ARC_EDGES = 60
MIN_ELEMENTS = 2500

# tip deflection curve, measured on this image (R -> |tip_uy|)
PINNED_R = (2.0, 4.0, 6.0, 8.0)
PINNED_TIP = (0.24500547, 0.24775791, 0.25956861, 0.31209782)
PINNED_REL_TOL = 5.0e-2

RESOLVE_REL_TOL = 2.0e-2
SUMMARY_REL_TOL = 1.0e-3


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-9) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * abs(target))


# ---------------------------------------------------------------- summary
def parse_summary(summary_path: Path) -> tuple[float, float] | None:
    parts = [p.strip() for p in summary_path.read_text(errors="ignore").strip().split(",")]
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
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


def l2_mesh_conformance(points, triangles) -> float | None:
    import numpy as np

    if len(triangles) < MIN_ELEMENTS:
        _fail(f"mesh has {len(triangles)} triangles, fewer than {MIN_ELEMENTS}")
        return None
    xs, ys = points[:, 0], points[:, 1]
    if (abs(xs.min()) > GEOM_ABS_TOL or abs(xs.max() - LENGTH) > GEOM_ABS_TOL
            or abs(ys.min() + WIDTH / 2) > GEOM_ABS_TOL
            or abs(ys.max() - WIDTH / 2) > GEOM_ABS_TOL):
        _fail("mesh bounding box does not match the 100 x 20 mm cantilever")
        return None

    edges = _edge_counts(triangles)
    boundary = set()
    for (a, b), count in edges.items():
        if count == 1:
            boundary.add(a)
            boundary.add(b)
    boundary = np.asarray(sorted(boundary), dtype=np.int64)
    outer = ((np.abs(xs[boundary]) <= 1e-6) | (np.abs(xs[boundary] - LENGTH) <= 1e-6)
             | (np.abs(ys[boundary] + WIDTH / 2) <= 1e-6)
             | (np.abs(ys[boundary] - WIDTH / 2) <= 1e-6))
    hole = boundary[~outer]
    if hole.size == 0:
        _fail("no hole-boundary nodes found")
        return None
    cx = float((xs[hole].min() + xs[hole].max()) / 2.0)
    cy = float((ys[hole].min() + ys[hole].max()) / 2.0)
    r = float((xs[hole].max() - xs[hole].min()) / 2.0)
    if abs(cx - HOLE_X) > GEOM_ABS_TOL or abs(cy - HOLE_Y) > GEOM_ABS_TOL:
        _fail(f"hole center ({cx:.3f}, {cy:.3f}) is not (40, 0)")
        return None
    if not (R_BOUNDS[0] - 1e-6 <= r <= R_BOUNDS[1] + 1e-6):
        _fail(f"hole radius R={r:.4f} outside {R_BOUNDS}")
        return None
    radii = np.hypot(xs - cx, ys - cy)
    if np.any(np.abs(radii[hole] - r) > RADIUS_ABS_TOL):
        _fail("hole-boundary nodes do not lie on one circle")
        return None
    if np.any(radii < r - RADIUS_ABS_TOL):
        _fail("mesh nodes lie inside the circular hole")
        return None

    hole_set = set(int(i) for i in hole)
    arc_edges = sum(1 for (u, v), count in edges.items()
                    if count == 1 and u in hole_set and v in hole_set)
    if arc_edges < MIN_ARC_EDGES:
        _fail(f"only {arc_edges} boundary edges on the hole; need >= {MIN_ARC_EDGES}")
        return None
    return r


# ---------------------------------------------------------------- L3
def resolve(points, triangles, r_hole: float) -> tuple[float, float] | None:
    import numpy as np
    from mpi4py import MPI
    import basix.ufl
    import ufl
    from dolfinx import fem
    from dolfinx.mesh import create_mesh, locate_entities_boundary, meshtags
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
    right = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], LENGTH))
    Vx, Vy = V.sub(0), V.sub(1)
    bcs = [dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx),
           dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, left), Vy)]
    mt = meshtags(domain, 1, right, np.full(len(right), 1, dtype=np.int32))
    ds = ufl.Measure("ds", domain=domain, subdomain_data=mt)

    mu = E_YOUNG / (2.0 * (1.0 + NU))
    lam = E_YOUNG * NU / ((1.0 + NU) * (1.0 - 2.0 * NU))
    lam_star = 2.0 * lam * mu / (lam + 2.0 * mu)

    def eps(w):
        return ufl.sym(ufl.grad(w))

    def sigma(w):
        return 2.0 * mu * eps(w) + lam_star * ufl.tr(eps(w)) * ufl.Identity(2)

    u = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)
    a = ufl.inner(sigma(u), eps(v)) * ufl.dx
    t = ufl.as_vector((0.0, TOTAL_LOAD / WIDTH))
    load = ufl.inner(t, v) * THICKNESS * ds(1)
    from dolfinx.fem.petsc import LinearProblem
    problem = LinearProblem(a, load, bcs=bcs, petsc_options_prefix="vcax_eval_",
                            petsc_options={"ksp_type": "preonly", "pc_type": "lu"})
    uh = problem.solve()
    V1 = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
    ip = _ipoints(V1)
    uy = Function(V1)
    uy.interpolate(fem.Expression(uh[1], ip))
    xy = V1.tabulate_dof_coordinates()
    tip_nodes = xy[:, 0] >= LENGTH - 1e-3
    if not tip_nodes.any():
        return None
    tip_uy = float(np.mean(uy.x.array[tip_nodes]))
    return tip_uy, r_hole


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
    r = l2_mesh_conformance(points, triangles)
    if r is None:
        return 0.0

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        _fail("summary.txt must be two comma-separated numbers: R, tip_uy")
        return 0.0
    r_s, tip_s = summary
    if not close_enough(r_s, r, SUMMARY_REL_TOL):
        _fail("reported hole radius does not match the submitted mesh")
        return 0.0

    resolved = resolve(points, triangles, r)
    if resolved is None:
        _fail("independent re-solve failed")
        return 0.0
    tip, _ = resolved
    if not close_enough(tip_s, tip, RESOLVE_REL_TOL):
        _fail("tip_uy does not match the independent re-solve of mesh.msh")
        return 0.0

    import numpy as np
    tip_ref = float(np.interp(r, PINNED_R, PINNED_TIP))
    if not close_enough(tip, -tip_ref, PINNED_REL_TOL):
        _fail(f"tip deflection {tip:.4f} is outside the pinned curve "
              f"(-{tip_ref:.4f} +/- {PINNED_REL_TOL:.0%})")
        return 0.0

    if abs(tip) > DEFLECTION_LIMIT * (1.0 + 1e-9):
        _fail(f"tip deflection {abs(tip):.4f} exceeds the {DEFLECTION_LIMIT} mm limit")
        return 0.0

    score = (r**2 - R_BOUNDS[0] ** 2) / (R_OPT**2 - R_BOUNDS[0] ** 2)
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