# Hole-radius sizing under uniaxial tension (quarter model)

A thin square plate 200 mm x 200 mm with a central circular hole of radius `R`
is loaded by a uniform uniaxial tension `sigma_xx = 100 MPa` along one pair of
opposite edges.

Model ONE QUARTER of the plate (a 100 mm x 100 mm domain with the hole quarter
at the origin):

- domain: `x in [0, 100]`, `y in [0, 100]`, excluding the quarter disk
  `x^2 + y^2 <= R^2` around the origin
- design variable: the hole radius `R`, with `5 <= R <= 35 mm`
- symmetry: `ux = 0` on the edge `x = 0`; `uy = 0` on the edge `y = 0`
- the hole boundary and the edge `y = 100` are traction-free
- material: `E = 210000 MPa`, `nu = 0.3`, plane stress, thickness 1 mm
- load: uniform traction `t = (100, 0) MPa` on the edge `x = 100`

Deliver in `/home/user/Desktop`:

1. `mesh.msh` — gmsh ASCII mesh (2.2 or 4.1), triangular elements, refined
   around the hole: at least 80 element edges along the hole arc, at least
   3000 triangles, and no nodes inside the hole.
2. `solve.py` — the script that builds and solves the model (not executed by
   the evaluator).
3. `summary.txt` — one line, three comma-separated numbers:
   `R, sigma_xx_max, ux_max` where
   - `R` is the meshed hole radius, in mm;
   - `sigma_xx_max` is the maximum `sigma_xx` at the mesh vertices on the hole
     boundary (`|sqrt(x^2+y^2) - R| <= 1e-3`), in MPa, evaluated by projecting
     the stress field to a continuous field before taking the maximum;
   - `ux_max` is the maximum `ux` at the mesh vertices on the loaded edge
     (`x >= 100 - 1e-3`), in mm.

Objective: remove mass, i.e. make `R` as large as possible, subject to a
peak-stress limit of 400 MPa on the hole boundary. The score is the
normalized mass reduction from the `R=10 mm` baseline toward the best feasible
design at the limit (`R ~= 31.56 mm`):
`score = clamp((R^2 - 100) / (31.56^2 - 100), 0, 1)`.

Solve with dolfinx. The evaluator re-solves the submitted mesh independently;
the reported numbers must come from your own computation on that mesh.