# First natural frequency of a uniform cantilever (CalculiX)

Find the first natural frequency of a uniform steel cantilever beam: 100 mm
long, 10 x 10 mm square cross-section.

Build `/home/user/Desktop/solution.inp`:

- 11 nodes: node i at `(10*(i-1), 0, 0)` for i = 1..11
- 10 B31 elements: element e connects nodes `e` and `e+1`
- material: `E = 210000 MPa`, `nu = 0.3`, density `7.85e-9 t/mm^3`
  (CalculiX consistent mm-N-s units), one `*Beam Section` with
  `section=RECT` and `10.0, 10.0`
- boundary: node 1 dofs 1-6 clamped to zero; no other constraints, no loads
- step: `*Frequency`, first eigenmode (`1, 1`)

Submit with `/usr/bin/ccx` and produce `solution.dat`. CalculiX writes the
eigenvalue block automatically; its columns are mode number, eigenvalue,
frequency in rad/time, frequency in cycles/time.

Write `summary.txt` as two comma-separated numbers: `eigenvalue, f1_hz` —
the first eigenvalue and its frequency in Hz.

The evaluator re-solves the deck independently.