# Beam vs solid consistency (CalculiX)

Deliver the same uniform cantilever in two representations and check that they
agree.

- geometry: 100 mm long, 10 x 10 mm square section, clamped at `x = 0`,
  tip load -100 N in y
- material: `E = 210000 MPa`, `nu = 0.3`

## Beam model

`beam.inp`:

- 11 nodes at `(10*(i-1), 0, 0)`, i = 1..11
- 10 B31 elements, element e joins nodes `e` and `e+1`
- one `*Beam Section` `section=RECT`, `10.0, 10.0`, covering all elements
- clamp node 1 dofs 1-6; tip load at node 11
- run `/usr/bin/ccx beam` and keep `beam.dat`

## Solid model

`solid.inp`:

- structured C3D8 mesh 40 x 4 x 4 (2.5 mm cubes; 1025 nodes, 640 elements)
- material and one `*Solid Section` over all elements
- clamp the whole `x = 0` face in dofs 1-3
- -100 N total in y at `x = 100`, equally divided over the 25 tip-face nodes
  (-4 N each), one `*Cload` line per node
- run `/usr/bin/ccx solid` and keep `solid.dat`

CalculiX allows at most 16 entries per data line; split long sets. Results
reach `.dat` through `*Node Print` with explicit node sets.

Write `summary.txt` as two comma-separated numbers:
`beam_tip_uy, solid_tip_uy` — the y displacement of the beam tip node (11) and
of the solid node at `(100, 5, 5)`, in mm. The two models must agree within 5%
and with beam theory.

The evaluator re-runs both decks independently.