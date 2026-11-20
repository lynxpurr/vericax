# Plate with a central hole — engineering report

`drawing.svg` gives the geometry and the applied traction. Read it, then build
the quarter model and solve it.

- quarter model: `x in [0, 100]`, `y in [0, 100]`, excluding the quarter hole
  at the origin
- symmetry: `ux = 0` on `x = 0`; `uy = 0` on `y = 0`
- the hole boundary and the edge `y = 100` are traction-free
- the edge `x = 100` carries the uniform traction shown in the drawing
- material: `E = 210000 MPa`, `nu = 0.3`, plane stress, thickness 1 mm

Deliver in `/home/user/Desktop`:

1. `mesh.msh` — gmsh ASCII mesh (2.2 or 4.1), triangular elements, refined
   around the hole: at least 80 element edges along the hole arc, at least
   3000 elements, no nodes inside the hole.
2. `solve.py` — the script that builds and solves the model (not executed by
   the evaluator).
3. `summary.txt` — one line, two comma-separated numbers: `sigma_xx_max, ux_max`
   - `sigma_xx_max`: maximum `sigma_xx` at mesh vertices on the hole arc
     (`|sqrt(x^2+y^2) - R| <= 1e-3`), in MPa, using a continuous (P1)
     projection of the stress field;
   - `ux_max`: maximum `ux` at mesh vertices on the loaded edge
     (`x >= 100 - 1e-3`), in mm.

Solve with dolfinx. The evaluator re-solves the submitted mesh independently;
the reported numbers must come from your own run.