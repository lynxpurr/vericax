#!/usr/bin/env python3
"""VeriCAx verifier - cae--cli--fenics--task-0017 (thermo-elastic two-stage analysis).

Exact-match task (spec/02 L1-L4). Two stages run on ONE mesh: a steady heat
conduction problem gives a temperature field, and three plane-stress
thermo-elastic load cases use it (thermal only, traction only, both).

L1  artifacts present and non-empty
L2  mesh conformance (quarter plate, R = 20 mm hole, resolution) and a
    four-number summary
L3  independent re-solve of both stages ON THE SUBMITTED MESH; every reported
    number must agree with it
L4  cross-stage consistency: the three cases must obey linear superposition,
    ux_both = ux_th + ux_m

The agent's summary is cross-checked, never trusted; solve.py is not executed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3", "L4")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))

REQUIRED_ARTIFACTS = ["mesh.msh", "summary.txt", "solve.py"]

# ---- problem (task instruction) ----
W = H = 100.0
R_HOLE = 20.0
K_COND, F0 = 45.0, 4.0
E_YOUNG, NU, ALPHA = 210000.0, 0.3, 1.2e-5
THICKNESS = 1.0
SIGMA_LOAD = 100.0

# ---- mesh / geometry tolerances ----
GEOM_ABS_TOL = 0.5
RADIUS_ABS_TOL = 0.05
MIN_ARC_EDGES = 80
MIN_ELEMENTS = 3000
MAX_ELEMENTS = 80000     # stated in the instruction; bounds the verifier's direct solve

# ---- tolerances ----
T_RESOLVE_REL_TOL = 5.0e-3     # T_max vs the independent re-solve
UX_RESOLVE_REL_TOL = 1.0e-2    # each displacement vs the independent re-solve
SUPERPOSITION_REL_TOL = 1.0e-3 # ux_both vs ux_th + ux_m
PINNED_REL_TOL = 5.0e-2        # re-solved displacements vs the reference solution
PINNED_T_REL_TOL = 3.0e-2      # re-solved T_max vs the reference solution

# ---- reference solution on this image (baked from ground_truth/summary.txt) ----
EXPECTED_TMAX = None
EXPECTED_UX_TH = None
EXPECTED_UX_M = None
EXPECTED_UX_BOTH = None


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


def l2_mesh_conformance(points, triangles) -> bool:
    import numpy as np

    if len(triangles) < MIN_ELEMENTS:
        return _fail(f"mesh has {len(triangles)} triangles, fewer than {MIN_ELEMENTS}")
    if len(triangles) > MAX_ELEMENTS:
        return _fail(f"mesh has {len(triangles)} triangles, more than {MAX_ELEMENTS}")
    xs, ys = points[:, 0], points[:, 1]
    if (abs(xs.min()) > GEOM_ABS_TOL or abs(xs.max() - W) > GEOM_ABS_TOL
            or abs(ys.min()) > GEOM_ABS_TOL or abs(ys.max() - H) > GEOM_ABS_TOL):
        return _fail("mesh bounding box does not match the 100 x 100 mm quarter plate")

    arc = np.asarray(sorted(_arc_nodes(points, triangles)), dtype=np.int64)
    if arc.size == 0:
        return _fail("no hole-boundary nodes found")
    radii = np.hypot(xs, ys)
    if np.any(np.abs(radii[arc] - R_HOLE) > RADIUS_ABS_TOL):
        r = float(radii[arc].max())
        return _fail(f"hole-boundary nodes do not lie on the R={R_HOLE} mm circle "
                     f"(largest radius found: {r:.4f} mm)")
    if np.any(radii < R_HOLE - RADIUS_ABS_TOL):
        return _fail("mesh nodes lie inside the circular hole")

    edges = _edge_counts(triangles)
    arc_set = set(int(i) for i in arc)
    arc_edges = sum(1 for (u, v), count in edges.items()
                    if count == 1 and u in arc_set and v in arc_set)
    if arc_edges < MIN_ARC_EDGES:
        return _fail(f"only {arc_edges} boundary edges on the hole arc; "
                     f"need >= {MIN_ARC_EDGES}")
    return True


def build_domain(points, triangles):
    import numpy as np
    from mpi4py import MPI
    import basix.ufl
    from dolfinx.mesh import create_mesh

    coords = np.ascontiguousarray(points, dtype=float)
    coord_el = basix.ufl.element("Lagrange", "triangle", 1, shape=(2,))
    return create_mesh(MPI.COMM_WORLD, triangles.astype(np.int64), coord_el, coords)


# ---------------------------------------------------------------- L3
def _lu_options(prefix: str) -> dict:
    return {"petsc_options_prefix": prefix,
            "petsc_options": {"ksp_type": "preonly", "pc_type": "lu"}}


def solve_thermal(domain):
    """Stage 1 on the given mesh: (temperature P1 function, T_max at vertices)."""
    import numpy as np
    import basix.ufl
    import ufl
    from dolfinx import fem
    from dolfinx.mesh import locate_entities_boundary
    from dolfinx.fem import dirichletbc, functionspace, locate_dofs_topological
    from dolfinx.fem.petsc import LinearProblem

    Q = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 1))
    cold = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], W))
    bc = dirichletbc(np.float64(0.0), locate_dofs_topological(Q, 1, cold), Q)

    x = ufl.SpatialCoordinate(domain)
    source = fem.Constant(domain, F0) * ufl.cos(ufl.pi * x[0] / (2.0 * W))
    T, q = ufl.TrialFunction(Q), ufl.TestFunction(Q)
    a = K_COND * ufl.dot(ufl.grad(T), ufl.grad(q)) * ufl.dx
    L = source * q * ufl.dx
    temperature = LinearProblem(a, L, bcs=[bc], **_lu_options("vcax_eval_t_")).solve()
    return temperature, float(np.max(temperature.x.array))


def solve_elasticity(domain, temperature=None, traction: bool = False) -> float | None:
    """Stage 2 on the given mesh; returns the mean ux along the loaded edge x = 100.

    The mean is a linear functional of the displacement, so the three load
    cases add up exactly; a maximum over the edge would not (the maxima of the
    thermal and the traction case sit at different points).
    """
    import numpy as np
    import basix.ufl
    import ufl
    from dolfinx import fem
    from dolfinx.mesh import locate_entities_boundary, meshtags
    from dolfinx.fem import dirichletbc, functionspace, locate_dofs_topological
    from dolfinx.fem.petsc import LinearProblem

    V = functionspace(domain, basix.ufl.element("Lagrange", "triangle", 2, shape=(2,)))
    left = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], 0.0))
    bottom = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[1], 0.0))
    Vx, Vy = V.sub(0), V.sub(1)
    bcs = [dirichletbc(np.float64(0.0), locate_dofs_topological(Vx, 1, left), Vx),
           dirichletbc(np.float64(0.0), locate_dofs_topological(Vy, 1, bottom), Vy)]

    mu = E_YOUNG / (2.0 * (1.0 + NU))
    lam = E_YOUNG * NU / ((1.0 + NU) * (1.0 - 2.0 * NU))
    lam_star = 2.0 * lam * mu / (lam + 2.0 * mu)  # plane stress

    def eps(w):
        return ufl.sym(ufl.grad(w))

    def sigma(w):
        return 2.0 * mu * eps(w) + lam_star * ufl.tr(eps(w)) * ufl.Identity(2)

    right = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], W))
    if len(right) == 0:
        return None
    mt = meshtags(domain, 1, right, np.full(len(right), 1, dtype=np.int32))
    ds = ufl.Measure("ds", domain=domain, subdomain_data=mt)

    u = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)
    a = ufl.inner(sigma(u), eps(v)) * ufl.dx
    L = fem.Constant(domain, 0.0) * v[0] * ufl.dx
    if temperature is not None:
        beta = E_YOUNG * ALPHA / (1.0 - NU)
        L = L + beta * temperature * ufl.tr(eps(v)) * ufl.dx
    if traction:
        L = L + ufl.inner(ufl.as_vector((SIGMA_LOAD, 0.0)), v) * THICKNESS * ds(1)
    uh = LinearProblem(a, L, bcs=bcs, **_lu_options("vcax_eval_u_")).solve()
    return float(fem.assemble_scalar(fem.form(uh[0] * ds(1))) / W)


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
                     "T_max, ux_th, ux_m, ux_both")
    t_rep, th_rep, m_rep, both_rep = summary

    domain = build_domain(points, triangles)
    temperature, t_ref = solve_thermal(domain)
    th_ref = solve_elasticity(domain, temperature=temperature)
    m_ref = solve_elasticity(domain, traction=True)
    both_ref = solve_elasticity(domain, temperature=temperature, traction=True)
    if th_ref is None or m_ref is None or both_ref is None:
        return _fail("independent re-solve failed: the mesh has no edge at x = 100")

    # ---- L3: every reported number against the independent re-solve
    if not close_enough(t_rep, t_ref, T_RESOLVE_REL_TOL):
        return _fail(f"T_max {t_rep:.6g} does not match the independent re-solve "
                     f"({t_ref:.6g})")
    for name, reported, reference in (("ux_th", th_rep, th_ref), ("ux_m", m_rep, m_ref),
                                      ("ux_both", both_rep, both_ref)):
        if not close_enough(reported, reference, UX_RESOLVE_REL_TOL):
            return _fail(f"{name} {reported:.6g} does not match the independent re-solve "
                         f"({reference:.6g})")

    # ---- L4: the three cases must be one consistent linear model
    if not close_enough(both_rep, th_rep + m_rep, SUPERPOSITION_REL_TOL):
        return _fail(f"ux_both {both_rep:.6g} is not ux_th + ux_m "
                     f"({th_rep:.6g} + {m_rep:.6g})")

    # ---- physics net: the re-solve must land on the reference solution of this
    # image, so another source, coupling constant or load is rejected even when
    # the agent solved that other problem correctly.
    if EXPECTED_TMAX is not None and not close_enough(t_ref, EXPECTED_TMAX, PINNED_T_REL_TOL):
        return _fail(f"re-solved T_max {t_ref:.4f} is outside the reference band "
                     f"({EXPECTED_TMAX:.4f} +/- {PINNED_T_REL_TOL:.0%})")
    for name, reference, pinned in (("ux_th", th_ref, EXPECTED_UX_TH),
                                    ("ux_m", m_ref, EXPECTED_UX_M),
                                    ("ux_both", both_ref, EXPECTED_UX_BOTH)):
        if pinned is not None and not close_enough(reference, pinned, PINNED_REL_TOL):
            return _fail(f"re-solved {name} {reference:.6f} is outside the reference band "
                         f"({pinned:.6f} +/- {PINNED_REL_TOL:.0%})")
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
