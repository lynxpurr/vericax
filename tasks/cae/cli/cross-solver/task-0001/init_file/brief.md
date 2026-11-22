# L6 provenance conformance (CalculiX, challenge token)

This is the P2 provenance spike prototype. The evaluator re-runs the deck and
compares the **full-field** result, not only the summary.

Problem: uniform cantilever beam 100 mm long, 10 x 10 mm square section,
clamped at `x = 0`, tip load `FY = -100 N`.

Build `/home/user/Desktop/solution.inp`:

- 11 nodes at `(10*(i-1), 0, 0)`, i = 1..11; 10 B31 elements, element e joins
  nodes `e` and `e+1`
- material `E = 210000 MPa`, `nu = 0.3`; `*Beam Section` `section=RECT`,
  `10.0, 10.0`
- boundary: node 1 dofs 1-6 clamped
- step: `*Static`, tip load `11, 2, -100.0`
- define a node set named exactly as the challenge token in your task
  instruction, with all 11 nodes, and request `*Node Print, NSET=<that name>`, `U`

Submit with `/usr/bin/ccx` and produce `solution.dat`. Write `summary.txt` as
one number: `tip_uy`, the y displacement of node 11 (mm).

The evaluator re-runs `ccx` and compares every nodal displacement in your
`solution.dat` for that set to its fresh run within 1e-4 relative
tolerance. A fabricated non-empty `.dat`, a result from another solver, a
mixed native result, or a different challenge token is rejected.