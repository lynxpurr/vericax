# Mesh-refinement consistency on a 3D cantilever (CalculiX)

Study mesh refinement on a 3D cantilever block 100 x 10 x 10 mm, clamped at
`x = 0`, with a total tip load of -100 N in y at `x = 100`.

Build two decks for the same problem:

- `coarse.inp` — C3D8 mesh 20 x 2 x 2 (2.5 mm along x, 5 mm across y/z;
  189 nodes, 160 elements)
- `fine.inp` — C3D8 mesh 40 x 4 x 4 (2.5 mm cubes; 1025 nodes, 640 elements)
- node coordinates on the grids `x = 0..100`, `y = 0..10`, `z = 0..10`
- material `E = 210000 MPa`, `nu = 0.3`, one `*Solid Section` per deck
- boundary: all three dofs fixed on the whole `x = 0` face
- load: -100 N total in y at `x = 100`, divided equally over the tip-face
  nodes; one `*Cload` line per node
- step: `*Static`

CalculiX allows at most 16 entries per data line; split long sets. Results
reach `.dat` through `*Node Print` with an explicit node set.

Submit both jobs with `/usr/bin/ccx`, producing `coarse.dat` and `fine.dat`,
then write `summary.txt` as two comma-separated numbers:
`coarse_tip_uy, fine_tip_uy` — the y displacement of the node at
`(100, 5, 5)` in each model, in mm.

The evaluator re-runs both decks and checks that the refined result is closer
to beam theory while the two stay consistent.