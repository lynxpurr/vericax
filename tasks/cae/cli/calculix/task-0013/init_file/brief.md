# Stepped tension plate: one deck, three static steps (CalculiX)

A flat plate 200 mm long (x) and 100 mm high (y), in the plane z = 0 and 2 mm
thick, is clamped along x = 0 and loaded in three linear static steps inside
ONE deck. Check that the three steps stay consistent (step 3 = step 1 + step 2).

- units: mm, N, MPa, tonne
- material: E = 210000 MPa, nu = 0.3, density 7.85e-9 t/mm^3
- mesh: 861 nodes at (5*i, 5*j, 0), i = 0..40, j = 0..20; 800 `CPS4` cells of
  5 x 5 mm; numbering is yours; one `*SOLID SECTION` over all elements with
  thickness 2.0
- node sets: `CLAMP` (x = 0), `FREE` (x = 200), `MIDFREE` (200, 50),
  `CENTRE` (100, 50)
- boundary: every `CLAMP` node fixed in dofs 1 and 2 only, nothing else, and
  nothing added or changed after step 1
- loads, all with `*DLOAD` (no `*CLOAD`):
  - step 1: 100 MPa tensile traction in +x on x = 200, as face loads on the
    rightmost element column (a positive CalculiX pressure acts into the
    element; face label and sign follow from your node ordering)
  - step 2: traction removed; body force in -x with `GRAV` (unit direction
    vector), rho*g = 10/200 N/mm^3
  - step 3: both loads together
- output: in each step, `*NODE PRINT` of `U` for `FREE` and `RF` for `CLAMP`

Deliver on the Desktop: `plate.inp`, `plate.dat` (from `/usr/bin/ccx plate`)
and `summary.txt` with one line `ux1, uy1, ux2, ux3`: the mean ux over the 21
`FREE` nodes at the end of steps 1, 2 and 3, with the mean uy of step 1 in
second place (mm).

The evaluator re-runs the deck independently and checks the reported numbers,
the reaction forces in `plate.dat` and the consistency of the three steps.
