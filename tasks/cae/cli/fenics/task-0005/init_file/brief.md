# Cantilever lightening-hole sizing (FEniCS)

A 2D plane-stress cantilever 100 mm long and 20 mm wide (thickness 1 mm) has a
circular lightening hole of radius `R` centred at `(40, 0)`. A total tip force
of -100 N in y is applied as a uniform shear traction over the tip edge. `R` is
the design variable, `2 <= R <= 8 mm`.

Deliver in `/home/user/Desktop`:

1. `mesh.msh` — gmsh ASCII mesh (2.2 or 4.1) with triangular elements, at least
   2500 triangles, at least 60 element edges around the hole, and no nodes
   inside the hole.
2. `solve.py` — the script that builds and solves the model (not executed by
   the evaluator).
3. `summary.txt` — one line, two comma-separated numbers: `R, tip_uy`, where
   `tip_uy` is the average y displacement of the nodes on the tip edge
   (`x >= 100 - 1e-3`), in mm.

Objective: remove mass, i.e. make `R` as large as possible, subject to
`|tip_uy| <= 0.27 mm`. Material: `E = 210000 MPa`, `nu = 0.3`, plane stress,
thickness 1 mm. The score is the normalized mass reduction from the `R=2 mm`
baseline to the best feasible design:
`score = clamp((R^2 - 4) / (6.4^2 - 4), 0, 1)`.

Solve with dolfinx. The evaluator re-solves the submitted mesh independently.