#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0004 (tapered cantilever).

Quantified-score task (spec/02 L5): the agent chooses the tip width of a
linearly tapered 2D cantilever to remove mass while keeping the tip deflection
under a limit.

Stages:
  stage 1 (feasibility gate)  linear-taper mesh conformance, width bounds, and
                              the tip-deflection limit on the verifier's own
                              re-solve. Any violation -> 0.000000.
  stage 2 (quality score)     normalized mass reduction from the uniform
                              W0=20 mm baseline to the best feasible taper.

L3 rebuilds the plane-stress BVP in dolfinx ON THE SUBMITTED MESH; the
agent's summary is only cross-checked, never trusted.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3", "L5")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))

REQUIRED_ARTIFACTS = ["mesh.msh", "summary.txt", "solve.py"]

# ---- pinned design (task instruction) ----
LENGTH, W0 = 100.0, 20.0
WT_BOUNDS = (4.0, 20.0)
DEFLECTION_LIMIT = 0.58
TOTAL_LOAD = -100.0
E_YOUNG, NU = 210000.0, 0.3
THICKNESS = 1.0

# best feasible taper: pinned from the same image's deflection curve
WT_OPT = 5.57

# mesh / geometry
GEOM_ABS_TOL = 0.5
TAPER_ABS_TOL = 0.05
MIN_ELEMENTS = 3000

# deflection curve, measured on this image (wt -> |tip_uy|)
PINNED_WT = (4.0, 6.0, 8.0, 10.0, 20.0)
PINNED_TIP = (0.69422779, 0.54870340, 0.45892860, 0.39691645, 0.24464901)
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
            or ys.min() < -W0 / 2 - GEOM_ABS_TOL or ys.max() > W0 / 2 + GEOM_ABS_TOL):
        _fail("mesh bounding box does not match the 100 x 20 mm cantilever")
        return None

    edges = _edge_counts(triangles)
    boundary = set()
    for (a, b), count in edges.items():
        if count == 1:
            boundary.add(a)
            boundary.add(b)
    boundary = np.asarray(sorted(boundary), dtype=np.int64)

    tip = boundary[np.abs(xs[boundary] - LENGTH) <= 1e-6]
    if tip.size < 2:
        _fail("no tip edge found")
        return None
    wt = float(ys[tip].max() - ys[tip].min())
    if not (WT_BOUNDS[0] - 1e-6 <= wt <= WT_BOUNDS[1] + 1e-6):
        _fail(f"tip width {wt:.4f} outside {WT_BOUNDS}")
        return None

    w = W0 + (wt - W0) * xs / LENGTH
    if np.any(np.abs(ys) > w / 2 + TAPER_ABS_TOL):
        _fail("mesh nodes lie outside the linear taper")
        return None
    side = (np.abs(xs[boundary]) <= 1e-6) | (np.abs(xs[boundary] - LENGTH) <= 1e-6)
    if np.any(np.abs(np.abs(ys[boundary[~side]]) - w[boundary[~side]] / 2) > TAPER_ABS_TOL):
        _fail("top/bottom boundary is not the prescribed linear taper")
        return None
    left = boundary[np.abs(xs[boundary]) <= 1e-6]
    if left.size >= 2 and abs((ys[left].max() - ys[left].min()) - W0) > GEOM_ABS_TOL:
        _fail("root width must be 20 mm")
        return None
    return wt


# ---------------------------------------------------------------- L3
def resolve(points, triangles, wt: float) -> tuple[float, float] | None:
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
    t = ufl.as_vector((0.0, TOTAL_LOAD / wt))
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
    sigma_xx = Function(V1)
    sigma_xx.interpolate(fem.Expression(sigma(uh)[0, 0], ip))
    sigma_max = float(np.max(np.abs(sigma_xx.x.array)))
    return tip_uy, sigma_max


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
    wt = l2_mesh_conformance(points, triangles)
    if wt is None:
        return 0.0

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        _fail("summary.txt must be two comma-separated numbers: tip_width, tip_uy")
        return 0.0
    wt_s, tip_s = summary
    if not close_enough(wt_s, wt, SUMMARY_REL_TOL):
        _fail("reported tip width does not match the submitted mesh")
        return 0.0

    resolved = resolve(points, triangles, wt)
    if resolved is None:
        _fail("independent re-solve failed")
        return 0.0
    tip, _sigma_max = resolved
    if not close_enough(tip_s, tip, RESOLVE_REL_TOL):
        _fail("tip_uy does not match the independent re-solve of mesh.msh")
        return 0.0

    import numpy as np
    tip_ref = float(np.interp(wt, PINNED_WT, PINNED_TIP))
    if not close_enough(tip, -tip_ref, PINNED_REL_TOL):
        _fail(f"tip deflection {tip:.4f} is outside the pinned curve "
              f"(-{tip_ref:.4f} +/- {PINNED_REL_TOL:.0%})")
        return 0.0

    # ---- stage 1: feasibility gate
    if abs(tip) > DEFLECTION_LIMIT * (1.0 + 1e-9):
        _fail(f"tip deflection {abs(tip):.4f} exceeds the {DEFLECTION_LIMIT} mm limit")
        return 0.0

    # ---- stage 2: normalized mass reduction
    score = (W0 - wt) / (W0 - WT_OPT)
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