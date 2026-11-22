# 3D solid cantilever under a tip load (CalculiX)

A 3D cantilever block 100 mm long, 10 mm wide and 10 mm high is clamped at
`x = 0` and loaded by a total tip force of -100 N in the y direction at
`x = 100`.

Build `/home/user/Desktop/solution.inp`:

- structured C3D8 mesh: 40 elements along x, 4 along y and 4 along z
  (2.5 mm elements; 1025 nodes and 640 elements; ids are yours)
- nodes on the grid `x = 0..100`, `y = 0..10`, `z = 0..10` with 2.5 mm spacing
- material: `E = 210000 MPa`, `nu = 0.3`, one `*Solid Section` over all elements
- boundary: all three dofs fixed on the whole `x = 0` face
- load: -100 N total in y (dof 2) at `x = 100`, divided equally over the 25
  tip-face nodes (-4 N each); one `*Cload` line per node
- step: `*Static`

CalculiX allows at most 16 entries per data line; split long `*Nset` /
`*Elset` lists. Results reach `.dat` through `*Node Print`, which needs an
explicit node set.

Submit with `/usr/bin/ccx` and produce `solution.dat`, then write
`summary.txt` as one number: `tip_uy` — the y displacement of the node at
`(x, y, z) = (100, 5, 5)`, in mm.

The evaluator re-solves the deck independently.