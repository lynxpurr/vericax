# Two-step load history with linear superposition (CalculiX)

A uniform cantilever beam 100 mm long with a 10 x 10 mm square section carries
a two-step load history.

Build `/home/user/Desktop/solution.inp`:

- 11 nodes at `(10*(i-1), 0, 0)`, i = 1..11; 10 B31 elements, element e joins
  nodes `e` and `e+1`
- material `E = 210000 MPa`, `nu = 0.3`; one `*Beam Section` with
  `section=RECT` and `10.0, 10.0`
- boundary: node 1 dofs 1-6 clamped
- Step 1: FY = -100 N at node 11 (dof 2)
- Step 2: add FX = +50 N at node 11 (dof 1) without removing the step-1 load;
  the final tip load must be (50, -100) N. Either add the new load
  (default / `OP=MOD`) or reset with `*Cload, OP=NEW` and list both loads.
- request nodal displacements in BOTH steps (`*Node Print` needs a node set)

CalculiX allows at most 16 entries per data line; split long `*Nset` /
`*Elset` lists.

Submit the single job with `/usr/bin/ccx` and produce `solution.dat` with both
steps. Write `summary.txt` as three comma-separated numbers:
`uy_step1, ux_step2, uy_step2`.

The evaluator re-solves the deck and checks that step 2 is consistent with
step 1 (linear superposition).