# Tapered cantilever mass minimisation (FEniCS)

A 2D plane-stress cantilever 100 mm long is 20 mm wide at the clamped root
(`x = 0`) and linearly tapered to a tip width `wt` at `x = 100`; thickness is
1 mm. A total tip force of -100 N in y is applied as a uniform shear traction
over the tip edge. `wt` is the design variable, `4 <= wt <= 20 mm`.

Deliver in `/home/user/Desktop`:

1. `mesh.msh` — gmsh ASCII mesh (2.2 or 4.1), triangles, nodes on the linear
   boundaries `y = +/- w(x)/2` with `w(x) = 20 + (wt - 20)*x/100`; at least
   3000 triangles, refined enough that the tip deflection is converged.
2. `solve.py` — the script that builds and solves the model (not executed by
   the evaluator).
3. `summary.txt` — one line, two comma-separated numbers: `wt, tip_uy`, where
   `tip_uy` is the average y displacement of the nodes on the tip edge
   (`x >= 100 - 1e-3`), in mm.

Objective: remove mass, i.e. make `wt` as small as possible, subject to
`|tip_uy| <= 0.58 mm`. Material: `E = 210000 MPa`, `nu = 0.3`, plane stress,
thickness 1 mm. The score is the normalized mass reduction from the uniform
`wt=20 mm` baseline to the best feasible taper:
`score = clamp((20 - wt) / (20 - 5.57), 0, 1)`.

Solve with dolfinx. The evaluator re-solves the submitted mesh independently.