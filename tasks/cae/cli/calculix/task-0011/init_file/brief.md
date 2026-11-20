# Reconstruct a stepped cantilever from the drawing

`drawing.svg` is the only source of the geometry and the tip load. Read it,
then build the CalculiX model and solve it.

- material: steel, `E = 210000 MPa`, `nu = 0.3`
- use 10 mm B31 elements along the beam; nodes are numbered 1..13 from the
  clamped root to the tip
- the root segment gets one square RECT section and the tip segment another,
  as dimensioned in the drawing
- clamp the root node in dofs 1-6; apply the drawing's tip load in the
  negative y direction
- submit with `/usr/bin/ccx` and produce `solution.inp`, `solution.dat`

Write `summary.txt` as one number: `tip_uy`, the y displacement of the tip
node, in mm.

The evaluator re-solves your deck independently; the reported number must come
from your own run.