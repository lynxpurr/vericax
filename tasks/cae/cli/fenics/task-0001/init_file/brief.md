# Plate with a central hole under uniaxial tension (quarter model)

A thin square plate 200 mm x 200 mm with a central circular hole of radius
10 mm is loaded by a uniform uniaxial tension `sigma_xx = 100 MPa` along one
pair of opposite edges.

Model ONE QUARTER of the plate (a 100 mm x 100 mm domain with the hole
quarter at the origin):

- domain: `x in [0, 100]`, `y in [0, 100]`, excluding the quarter disk
  `x^2 + y^2 <= 10^2` around the origin
- symmetry: `ux = 0` on the edge `x = 0`; `uy = 0` on the edge `y = 0`
- the hole boundary (`x^2 + y^2 = 10^2`) and the edge `y = 100` are
  traction-free
- material: `E = 210000 MPa`, `nu = 0.3`, plane stress, thickness 1 mm
- load: uniform traction `t = (100, 0) MPa` on the edge `x = 100`

Deliver in `/home/user/Desktop`:

1. `mesh.msh` — gmsh ASCII mesh (2.2 or 4.1), triangular elements, refined
   around the hole: at least 200 element edges along the hole arc, element
   size near the hole `<= 0.5 mm`, at least 2000 elements.
2. `solve.py` — the script that builds and solves the model (not executed by
   the evaluator).
3. `summary.txt` — one line, two comma-separated numbers:
   - `sigma_xx_max` = maximum `sigma_xx` at the mesh vertices on the hole arc
     (`|sqrt(x^2+y^2) - 10| <= 1e-3`), in MPa, evaluated by projecting the
     stress field to a continuous field before taking the maximum;
   - `ux_max` = maximum `ux` at the mesh vertices on the loaded edge
     (`x >= 100 - 1e-3`), in mm.

Solve with `dolfinx`. The evaluator re-solves the submitted mesh
independently; the reported numbers must come from your own computation.