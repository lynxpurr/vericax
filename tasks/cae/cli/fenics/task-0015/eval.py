#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0015 (pygmsh mesh + dolfinx solve; open-environment).

Implements L1 (completeness), L2 (design conformance) and L3 (independent
re-solve). L3 rebuilds the model in dolfinx ON THE SUBMITTED MESH, solves the
plane-stress boundary value problem itself, and compares:

  A  the agent's summary.txt
  B  the verifier's independent re-solve of the submitted mesh   (tight)
  C  pinned reference values from the same image                 (loose)
plus a loose finite-width Kirsch (Howland) stress-concentration band as a
physics net.

Quantity choice: the peak axial stress on the hole boundary (the classic
stress-concentration quantity, mesh-converged with the prescribed refinement)
and the peak axial displacement on the loaded edge (a smooth functional that
binds the material and boundary conditions).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))

REQUIRED_ARTIFACTS = ["mesh.msh", "summary.txt", "solve.py"]

# ---- pinned design (task instruction) ----
W, H, R_HOLE = 100.0, 100.0, 10.0   # quarter-model domain
FULL_WIDTH = 200.0                   # full plate width (d/W = 0.1)
SIGMA_LOAD = 100.0
E_YOUNG, NU = 210000.0, 0.3
THICKNESS = 1.0

# ---- pinned reference, filled from the same VM image (ground_truth/) ----
# pinned from the same VM image (ground_truth/): peak hole stress and loaded-edge ux
EXPECTED_SIGMA_MAX = None
EXPECTED_UX_MAX = None

# ---- tolerances ----
RESOLVE_REL_TOL = 2.0e-2    # A vs B: same mesh, evaluation-convention noise
PINNED_REL_TOL = 5.0e-2     # B vs C: mesh/refinement differences
KIRSCH_REL_TOL = 8.0e-2     # A vs infinite-plate Kirsch (loose physics net:
                           # a square plate sits a few percent above 3.0)
KIRSCH_KT = 3.0             # infinite-plate stress concentration
GEOM_ABS_TOL = 0.5          # mesh bounding box tolerance (mm)
HOLE_ABS_TOL = 0.05         # node-vs-arc tolerance (mm)
MIN_ARC_EDGES = 80
MIN_ELEMENTS = 3000


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


def l2_mesh_conformance(points, triangles) -> bool:
    import numpy as np

    if len(triangles) < MIN_ELEMENTS:
        return _fail(f"mesh has {len(triangles)} triangles, fewer than {MIN_ELEMENTS}")
    xs, ys = points[:, 0], points[:, 1]
    if (abs(xs.min()) > GEOM_ABS_TOL or abs(xs.max() - W) > GEOM_ABS_TOL
            or abs(ys.min()) > GEOM_ABS_TOL or abs(ys.max() - H) > GEOM_ABS_TOL):
        return _fail("mesh bounding box does not match the 100 x 100 mm quarter plate")
    radii = np.hypot(xs, ys)
    if radii.min() < R_HOLE - HOLE_ABS_TOL:
        return _fail(f"mesh nodes inside the hole (min radius {radii.min():.3f} mm)")
    if radii.min() > R_HOLE + HOLE_ABS_TOL:
        return _fail("no mesh nodes on the hole boundary")
    on_arc = np.abs(radii - R_HOLE) <= 1e-3
    edges = _edge_counts(triangles)
    arc_edges = sum(1 for (a, b) in edges
                    if on_arc[a] and on_arc[b] and edges[(a, b)] == 1)
    if arc_edges < MIN_ARC_EDGES:
        return _fail(f"only {arc_edges} boundary edges on the hole arc; need >= {MIN_ARC_EDGES}")
    return True


# ---------------------------------------------------------------- L3
def resolve(points, triangles) -> tuple[float, float] | None:
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
    a = ufl.inner(sigma(u), eps(v)) * ufl.dx
    t = ufl.as_vector((SIGMA_LOAD, 0.0))
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
    ux = Function(V1)
    ux.interpolate(fem.Expression(uh[0], ip))

    xy = V1.tabulate_dof_coordinates()
    radii = np.hypot(xy[:, 0], xy[:, 1])
    arc = np.abs(radii - R_HOLE) <= 1e-3
    loaded = xy[:, 0] >= W - 1e-3
    if not arc.any() or not loaded.any():
        return None
    sigma_peak = float(np.max(sxx.x.array[arc]))
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
def evaluate() -> bool:
    if not l1_completeness():
        return False
    script = (AGENT_ROOT / "solve.py").read_text(errors="ignore")
    if "pygmsh" not in script:
        return _fail("solve.py must generate the mesh with pygmsh (install it from the wheelhouse)")

    points, triangles = load_mesh(AGENT_ROOT / "mesh.msh")
    if not l2_mesh_conformance(points, triangles):
        return False

    summary = parse_summary(AGENT_ROOT / "summary.txt")
    if summary is None:
        return _fail("summary.txt must be two comma-separated floats: sigma_xx_max, ux_max")
    sigma_a, ux_a = summary

    resolved = resolve(points, triangles)
    if resolved is None:
        return _fail("independent re-solve failed to evaluate the required quantities")
    sigma_b, ux_b = resolved

    # A vs B: reported numbers must match the physics of the submitted mesh.
    if not close_enough(sigma_a, sigma_b, RESOLVE_REL_TOL):
        return _fail("sigma_xx_max does not match the independent re-solve of mesh.msh")
    if not close_enough(ux_a, ux_b, RESOLVE_REL_TOL):
        return _fail("ux_max does not match the independent re-solve of mesh.msh")

    # B vs C: the model must be the pinned one (guards against L2 blind spots).
    if EXPECTED_SIGMA_MAX is not None and not close_enough(sigma_b, EXPECTED_SIGMA_MAX, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (sigma_xx_max)")
    if EXPECTED_UX_MAX is not None and not close_enough(ux_b, EXPECTED_UX_MAX, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (ux_max)")

    # A vs Kirsch band: the converged peak must be physical. A square plate
    # sits a few percent above the infinite-plate value of 3.0, so the band is
    # deliberately loose; tight agreement is enforced by A-vs-B and B-vs-C.
    sigma_ref = KIRSCH_KT * SIGMA_LOAD
    if not close_enough(sigma_a, sigma_ref, KIRSCH_REL_TOL):
        return _fail(f"peak stress inconsistent with the Kirsch band (Kt={KIRSCH_KT})")
    if not (0.0 < ux_a < 1.0):
        return _fail("ux_max is outside the physically plausible range")
    return True


def main() -> int:
    try:
        ok = evaluate()
    except Exception as exc:  # noqa: BLE001 - verifier must never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        ok = False
    print("True" if ok else "False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())