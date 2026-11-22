# First Euler buckling factor of a cantilever column (CalculiX)

Find the first buckling factor of a uniform steel cantilever column: 100 mm
long, 10 x 10 mm square cross-section, under a 1000 N axial compressive
reference load.

Build `/home/user/Desktop/solution.inp`:

- 11 nodes: node i at `(10*(i-1), 0, 0)` for i = 1..11
- 10 B31 elements: element e connects nodes `e` and `e+1`
- material: `E = 210000 MPa`, `nu = 0.3`, one `*Beam Section` with
  `section=RECT` and `10.0, 10.0`
- boundary: node 1 dofs 1-6 clamped to zero; no other constraints
- step: `*Buckle`, first mode (`1, 1`)
- load: 1000 N axial compressive reference load at node 11, dof 1
  (`11, 1, -1000.0`); this is the reference load, not the critical load

Submit with `/usr/bin/ccx` and produce `solution.dat`. CalculiX writes a
`BUCKLING FACTOR OUTPUT` block; the factor multiplies the applied reference
load.

Write `summary.txt` as two comma-separated numbers: `buckling_factor, pcr_n`
— the first factor and the critical load in newtons (factor times 1000 N).

The evaluator re-solves the deck independently.