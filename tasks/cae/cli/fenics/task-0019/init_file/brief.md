# Plate with two holes under an oblique edge load — engineering report

`drawing.svg` holds the complete problem definition: plate outline, the holes,
supports, load and material. **All problem data are in `drawing.svg` and are
not repeated in this report.** Read the drawing, then build the model and
solve it.

## Model

- Full plate as drawn, plane stress, thickness as given in the drawing. Model
  the whole plate with both holes: the plate is not symmetric under this load
  (the force is oblique and the two holes differ), so no symmetry reduction
  applies.
- Coordinates as drawn: origin at the lower-left corner of the plate, `x`
  along the bottom edge, `y` along the left edge.
- Supports (roller supports, hatched in the drawing): `ux = 0` on the left
  edge `x = 0` with the tangential direction free; `uy = 0` on the bottom edge
  `y = 0` with the tangential direction free. The top edge and both hole
  boundaries are traction-free.
- Load: the total force `F` shown at the middle of the right edge, acting at
  the angle shown above the `+x` direction, is applied as a **uniform traction
  over the whole right edge**. With `H` the plate height and `t` the
  thickness, the traction magnitude is `F / (H t)` with `F` in N and `H`, `t`
  in mm (so N/mm² = MPa), split into `x` and `y` components by the angle.
- Consistent units: mm, N, MPa. The drawing gives `E` in GPa and `F` in kN.
- Discretisation the evaluator uses on the submitted mesh: continuous
  piecewise-quadratic (P2) vector Lagrange elements for the displacement.

## Deliver in `/home/user/Desktop`

1. `mesh.msh` — gmsh ASCII mesh (2.2 or 4.1) of the full plate with both
   holes, planar (all nodes at `z = 0`), triangular elements, refined at the
   holes: at least 60 element edges along EACH hole arc and between 4000 and
   80000 elements in total; no nodes inside either hole.
2. `solve.py` — the script that builds and solves the model (not executed by
   the evaluator).
3. `summary.txt` — exactly one line, four comma-separated numbers:
   `sxx_A, syy_B, ux_mean, uy_mean`
   - `sxx_A`: maximum `sigma_xx` at the mesh vertices on the arc of hole A
     (the larger hole), in MPa;
   - `syy_B`: maximum `sigma_yy` at the mesh vertices on the arc of hole B
     (the smaller hole), in MPa;
   - `ux_mean`, `uy_mean`: arithmetic mean of `ux` and of `uy` over the
     vertices on the loaded edge (`x >= W - 1e-3`, with `W` the plate width),
     in mm.

   Conventions behind these numbers: an arc vertex is a mesh vertex whose
   distance to the hole centre differs from the hole radius by at most
   `1e-3` mm. The stress tensor is evaluated from the P2 displacement solution
   and projected onto the continuous piecewise-linear (P1) Lagrange space of
   the same mesh; each reported stress is the maximum of that P1 function over
   the arc vertices. The displacements are read at the P1 vertices of the
   loaded edge and averaged without weights.

Solve with dolfinx. The evaluator re-solves the submitted mesh independently;
the reported numbers must come from your own run.
