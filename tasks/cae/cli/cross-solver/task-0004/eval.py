#!/usr/bin/env python3
"""VeriCAx verifier - cross-solver task-0004 (software-selection, L6).

Required tool: FEniCS/dolfinx 0.10 (steady advection-diffusion with a smooth
spatially varying diffusivity and a convective term; CalculiX's equation set
has neither advection nor smooth coefficient fields, and its native result
family is .dat/.frd). The submitted native pair is mesh.msh + a dolfinx
XDMF/HDF5 checkpoint of the concentration field.

L6 enforcement:
  L1  completeness (mesh.msh, checkpoint xdmf+h5, summary)
  L2  mesh conformance + the challenge physical group `VCAX_AUDIT_0003`
  L3  independent re-solve on the submitted mesh with the exact E(x,y) field
      and the prescribed P1 discretisation
  L6  the SUBMITTED checkpoint field must equal the verifier's fresh field at
      every mesh vertex (matched by coordinates); a fabricated field, a
      foreign (CalculiX .dat) native result or a mesh without the challenge
      group is rejected.

spec/02 section 6 boundary: this proves artifact-tool equivalence, not that
the agent executed the tool.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IMPLEMENTS = ("L1", "L2", "L3", "L6")

AGENT_ROOT = Path(os.environ.get("VERICAX_AGENT_ROOT", "/home/user/Desktop"))

REQUIRED_ARTIFACTS = ["mesh.msh", "solution.xdmf", "solution.h5", "summary.txt"]
TOKEN = "VCAX_AUDIT_0004"

W, H = 100.0, 100.0
MIN_ELEMENTS = 2500
KAPPA0 = 10.0
BVELOCITY = (1.0, 0.0)
U_IN, U_OUT = 1.0, 0.0

FIELD_REL_TOL = 1.0e-4
RESOLVE_REL_TOL = 1.0e-4
PINNED_REL_TOL = 5.0e-2   # legal alternatives vary the mesh; the pin still catches image drift
KEY_DECIMALS = 6

EXPECTED_MEAN_U = None   # pinned from the same VM image (ground_truth/)


def _fail(reason: str) -> bool:
    print(f"debug: {reason}", file=sys.stderr)
    return False


def close_enough(actual: float, target: float, rel_tol: float, abs_tol: float = 1e-9) -> bool:
    return abs(actual - target) <= max(abs_tol, rel_tol * max(abs(actual), abs(target)))


# ---------------------------------------------------------------- mesh loading
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
    if points.shape[1] == 3 and np.any(np.abs(points[:, 2]) > 1e-9):
        raise ValueError("mesh is not planar (z != 0)")
    points = points[:, :2]

    # the challenge group names the loaded edge: map its physical tag to the
    # line-cell block and collect the group's point indices
    token_nodes = None
    tag_info = (m.field_data or {}).get(TOKEN)
    if tag_info is not None:
        tag = int(tag_info[0])
        line_cells = None
        for block in m.cells:
            if block.type == "line":
                line_cells = np.asarray(block.data, dtype=np.int64)
                break
        if line_cells is not None:
            for block, tags in zip(m.cells, m.cell_data["gmsh:physical"]):
                if block.type == "line":
                    sel = line_cells[np.asarray(tags) == tag]
                    if len(sel):
                        token_nodes = np.unique(sel.ravel())
                    break
    return points, triangles, token_nodes


# ---------------------------------------------------------------- checkpoint
def read_checkpoint(xdmf_path: Path) -> tuple[dict | None, str | None]:
    """Read the dolfinx XDMF/HDF5 checkpoint with an independent parser
    (h5py + XML; dolfinx 0.10 cannot read functions back from XDMF).

    Returns (field_by_coord, error). field_by_coord maps a rounded (x, y)
    coordinate key to the (ux, uy) nodal values.
    """
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(xdmf_path)
    except Exception as exc:  # noqa: BLE001
        return None, f"unreadable XDMF: {exc}"
    root = tree.getroot()

    def hdf_ref(node):
        item = node.find(".//DataItem[@Format='HDF']")
        if item is None or not (item.text or "").strip():
            return None
        return item.text.strip()

    def read_ds(ref: str):
        import h5py
        fname, key = ref.split(":", 1)
        h5 = xdmf_path.parent / fname.strip()
        if not h5.is_file():
            return None
        with h5py.File(h5, "r") as fh:
            return fh[key][:]

    geometry = topology = values = None
    for grid in root.iter("Grid"):
        geo = grid.find("Geometry")
        topo = grid.find("Topology")
        if geo is not None and topo is not None and geometry is None:
            ref = hdf_ref(geo)
            topo_ref = hdf_ref(topo)
            if ref and topo_ref:
                geometry = read_ds(ref)
                topology = read_ds(topo_ref)
        for attr in grid.findall("Attribute"):
            center = (attr.get("Center") or "").lower()
            if center == "node" and values is None:
                ref = hdf_ref(attr)
                if ref:
                    values = read_ds(ref)
    if geometry is None or values is None or topology is None:
        return None, "checkpoint lacks mesh geometry/topology or a nodal field"

    field: dict = {}
    for row in range(geometry.shape[0]):
        key = (round(float(geometry[row, 0]), KEY_DECIMALS),
               round(float(geometry[row, 1]), KEY_DECIMALS))
        field[key] = float(values[row][0])
    return field, None


# ---------------------------------------------------------------- L1
def l1_completeness() -> bool:
    for rel in REQUIRED_ARTIFACTS:
        p = AGENT_ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            return _fail(f"missing or empty artifact: {rel}")
    return True


# ---------------------------------------------------------------- L2
def l2_mesh_conformance(points, triangles, token_nodes) -> bool:
    import numpy as np

    if len(triangles) < MIN_ELEMENTS:
        return _fail(f"mesh has {len(triangles)} triangles, fewer than {MIN_ELEMENTS}")
    xs, ys = points[:, 0], points[:, 1]
    if (abs(xs.min()) > 1e-9 or abs(xs.max() - W) > 1e-6
            or abs(ys.min()) > 1e-9 or abs(ys.max() - H) > 1e-6):
        return _fail("mesh bounding box does not match the 100 x 100 mm domain")
    if token_nodes is None or len(token_nodes) < 2:
        return _fail(f"mesh lacks a non-trivial {TOKEN} physical curve")
    on_edge = np.isclose(points[token_nodes, 0], W, atol=1e-6)
    if not on_edge.all():
        return _fail(f"{TOKEN} must lie on the outflow edge x = {W}")
    if len(set(points[token_nodes, 1].round(6))) < 10:
        return _fail(f"{TOKEN} does not span the outflow edge")
    return True


# ---------------------------------------------------------------- L3/L6 re-solve
def resolve(points, triangles, token_nodes) -> tuple[float | None, dict | None]:
    """Re-solve the prescribed P1 advection-diffusion BVP with the exact
    kappa(x,y) and the convective term."""
    import numpy as np
    from mpi4py import MPI
    import basix.ufl
    import ufl
    from dolfinx import fem
    from dolfinx.fem import functionspace, dirichletbc, locate_dofs_topological
    from dolfinx.fem.petsc import LinearProblem
    from dolfinx.mesh import create_mesh, locate_entities_boundary, meshtags

    coords = np.ascontiguousarray(points, dtype=float)
    cells = triangles.astype(np.int64)
    coord_el = basix.ufl.element("Lagrange", "triangle", 1, shape=(2,))
    domain = create_mesh(MPI.COMM_WORLD, cells, coord_el, coords)
    V = functionspace(domain, ("Lagrange", 1))

    inflow = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], 0.0))
    outflow = locate_entities_boundary(domain, 1, lambda x: np.isclose(x[0], W))
    bc_in = dirichletbc(np.float64(U_IN), locate_dofs_topological(V, 1, inflow), V)
    bc_out = dirichletbc(np.float64(U_OUT), locate_dofs_topological(V, 1, outflow), V)

    # token-bound outflow facets: both endpoints carry a challenge-group
    # coordinate key on x = W (create_mesh may reindex the geometry, so the
    # binding is coordinate-based)
    token_keys = set()
    for n in token_nodes:
        token_keys.add((round(float(points[int(n), 0]), KEY_DECIMALS),
                        round(float(points[int(n), 1]), KEY_DECIMALS)))
    domain.topology.create_connectivity(1, 0)
    conn10 = domain.topology.connectivity(1, 0)
    im = domain.topology.index_map(1)
    chosen = []
    for f in range(im.size_local + im.num_ghosts):
        vs = conn10.links(f)
        vkeys = {(round(float(domain.geometry.x[vv][0]), KEY_DECIMALS),
                  round(float(domain.geometry.x[vv][1]), KEY_DECIMALS)) for vv in vs}
        if len(vkeys) == 2 and vkeys <= token_keys:
            chosen.append(f)
    if not chosen:
        return None, None
    mt = meshtags(domain, 1, np.asarray(chosen, dtype=np.int32),
                  np.full(len(chosen), 1, dtype=np.int32))

    u = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)
    x = ufl.SpatialCoordinate(domain)
    kappa = KAPPA0 * (1.0 + 0.3 * ufl.sin(ufl.pi * x[0] / W) * ufl.sin(ufl.pi * x[1] / H))
    bvel = ufl.as_vector(BVELOCITY)
    a = kappa * ufl.dot(ufl.grad(u), ufl.grad(v)) * ufl.dx + ufl.dot(bvel, ufl.grad(u)) * v * ufl.dx
    L = fem.Constant(domain, 0.0) * v * ufl.dx

    problem = LinearProblem(
        a, L, bcs=[bc_in, bc_out],
        petsc_options_prefix="vcax_ss4_eval_",
        petsc_options={"ksp_type": "preonly", "pc_type": "lu"})
    uh = problem.solve()

    field: dict = {}
    disp = uh.x.array
    dof_xy = uh.function_space.tabulate_dof_coordinates()[:, :2]
    for row in range(dof_xy.shape[0]):
        key = (round(float(dof_xy[row, 0]), KEY_DECIMALS),
               round(float(dof_xy[row, 1]), KEY_DECIMALS))
        field[key] = float(disp[row])

    # summary: mean concentration over all mesh vertices
    if not field:
        return None, None
    return float(np.mean([v for v in field.values()])), field


# ---------------------------------------------------------------- verdict
def evaluate() -> bool:
    if not l1_completeness():
        return False

    try:
        points, triangles, token_nodes = load_mesh(AGENT_ROOT / "mesh.msh")
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        return _fail(f"mesh.msh unreadable: {exc}")
    if not l2_mesh_conformance(points, triangles, token_nodes):
        return False

    submitted, err = read_checkpoint(AGENT_ROOT / "solution.xdmf")
    if submitted is None:
        return _fail(f"checkpoint unreadable: {err}")

    fresh_ux, fresh_field = resolve(points, triangles, token_nodes)
    if fresh_field is None or fresh_ux is None:
        return _fail("independent re-solve failed")

    # L6.2: the submitted checkpoint must cover the same vertices as the mesh
    mesh_keys = {(round(float(x), KEY_DECIMALS), round(float(y), KEY_DECIMALS))
                 for x, y in points}
    if set(submitted) != mesh_keys:
        return _fail("checkpoint vertices do not match the submitted mesh "
                     f"({len(submitted)} vs {len(mesh_keys)})")

    for key, fresh in fresh_field.items():
        sub = submitted.get(key)
        if sub is None:
            return _fail(f"checkpoint missing vertex {key}")
        if not close_enough(sub, fresh, FIELD_REL_TOL):
            return _fail(f"checkpoint field differs at {key}")

    summary = [p.strip() for p in (AGENT_ROOT / "summary.txt").read_text(
        errors="ignore").strip().split(",")]
    if len(summary) != 1:
        return _fail("summary.txt must be one number: the mean concentration over all vertices")
    try:
        summary_s = float(summary[0])
    except ValueError:
        return _fail("summary.txt value is not a number")
    if not close_enough(summary_s, fresh_ux, RESOLVE_REL_TOL):
        return _fail("summary does not match the independent re-solve")
    if EXPECTED_MEAN_U is not None and not close_enough(
            fresh_ux, EXPECTED_MEAN_U, PINNED_REL_TOL):
        return _fail("re-solve deviates from pinned reference (mean u)")
    return True


def main() -> int:
    try:
        ok = evaluate()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - never crash open
        print(f"debug: evaluator exception: {exc}", file=sys.stderr)
        ok = False
    print("True" if ok else "False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
