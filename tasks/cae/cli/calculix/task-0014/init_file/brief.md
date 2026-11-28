# Cantilever column: natural frequencies, axial shortening and buckling (CalculiX)

One deck, three steps in order: the natural frequencies of the unloaded column, its
shortening under a unit compressive load, and its buckling factors under that same
load.

- geometry: straight cantilever column, L = 1000 mm along x, clamped at `x = 0`,
  free at `x = L`; rectangular section 24 mm (y) x 12 mm (z)
- material: `E = 210000 MPa`, `nu = 0.3`, density `7.85e-9`
- units: mm, N, MPa, tonne (frequencies come out in Hz)

`column.inp`:

- 21 nodes at `(50*i, 0, 0)`, i = 0..20 (node numbers are your choice)
- 20 `B31` elements forming one chain from `x = 0` to `x = 1000`
- one `*Beam Section, section=RECT` over all elements: `24., 12.` (first size along
  local direction 1, second along local direction 2) and the 1-direction stated
  explicitly so that local 1 is y and local 2 is z (`24., 12.` then `0., 1., 0.`)
- material with `*Elastic` and `*Density` (the frequency step needs the density)
- node sets `ROOT` (`x = 0`), `TIP` (`x = 1000`) and `MID` (`x = 500`)
- `ROOT` clamped in dofs 1-6; nothing else constrained; no geometric nonlinearity
- step 1: `*Frequency`, first two modes of the unloaded column, no loads
- step 2: `*Static` (linear), unit compressive load `*Cload` of -1 in dof 1 at
  `TIP`, and `*Node Print` of `U` for `TIP`
- step 3: `*Buckle`, first two buckling factors, with the same unit load restated
  inside the step (`TIP, 1, -1.0`); no other load, boundary conditions unchanged
- run `/usr/bin/ccx column` and keep `column.dat`

Use only the cards listed here, plus CalculiX output requests such as `*Node File` or
`*El File`. CalculiX allows at most 16 entries per data line. Results reach `.dat`
as the eigenvalue table of step 1 (frequencies in the CYCLES/TIME column), the
displacement table of step 2 and the buckling factor table of step 3.

Write `summary.txt` as one line with five comma-separated numbers, at full printed
precision: `f1, f2, lam1, lam2, ux2`, where

- `f1`, `f2` are the first two natural frequencies in Hz from step 1
- `lam1`, `lam2` are the first two buckling factors from step 3, i.e. the buckling
  loads in N because the reference load is 1 N
- `ux2` is the x displacement of `TIP` at the end of step 2 in mm (negative)

The evaluator re-checks the deck, re-runs it independently and compares your numbers
with your own `column.dat` and with its re-run. The numbers must come from your own
CalculiX run.
