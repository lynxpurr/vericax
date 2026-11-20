# Elliptical hole shape design under uniaxial tension (quarter model)

A thin square plate 200 mm x 200 mm with a central elliptical hole is loaded
by a uniform uniaxial tension `sigma_xx = 100 MPa` along one pair of opposite
edges.

Model ONE QUARTER of the plate (a 100 mm x 100 mm domain with the quarter hole
at the origin):

- domain: `x in [0, 100]`, `y in [0, 100]`, excluding the quarter ellipse
  `x^2/a^2 + y^2/b^2 <= 1` around the origin
- design variables: the hole semi-axes `a` and `b`, with the hole area fixed:
  `a*b = 100 mm^2`, `5 <= a <= 20`, `5 <= b <= 20`
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
3. `summary.txt` — one line, four comma-separated numbers:
   `a, b, sigma_xx_max, ux_max` where
   - `a`, `b` are the semi-axes of the meshed hole, in mm;
   - `sigma_xx_max` is the maximum `sigma_xx` at the mesh vertices on the hole
     boundary (`|sqrt((x/a)^2+(y/b)^2) - 1| <= 1e-3`), in MPa, evaluated by
     projecting the stress field to a continuous field before taking the
     maximum;
   - `ux_max` is the maximum `ux` at the mesh vertices on the loaded edge
     (`x >= 100 - 1e-3`), in mm.

Objective: minimise `sigma_xx_max` at the fixed hole area. The score is the
normalized reduction of the peak stress from the circular baseline
(`a=b=10`, about 308.5 MPa) toward the best ellipse in the box (`a/b=4`,
about 150 MPa).

Solve with dolfinx. The evaluator re-solves the submitted mesh independently;
the reported numbers must come from your own computation on that mesh.