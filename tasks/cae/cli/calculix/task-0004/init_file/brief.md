# Thick-walled cylinder under internal pressure (plane strain)

A thick-walled cylinder with inner radius 10 mm and outer radius 20 mm is
loaded by an internal pressure of 50 MPa. Model a plane-strain slice with
axisymmetric CAX4 elements in the x-y plane at `z = 0` (CalculiX requires 2D
elements in the z=0 plane), radial coordinate `x in [10, 20]`, axial
coordinate `y in [0, 1]` mm, and the axial displacement `u_y = 0` on every
node.

Build `/home/user/Desktop/solution.inp`:

- 21 radial stations at `x = 10 + 0.5*i` for i = 0..20, each duplicated at
  `y = 0` and `y = 1` (42 nodes; node ids and ordering are yours)
- 20 CAX4 elements, one per radial interval; use a valid counter-clockwise
  node ordering in the x-y plane
- material: `E = 210000 MPa`, `nu = 0.3`, one `*Solid Section` covering all
  elements
- boundary: `u_y = 0` (dof 2) on every node; do not constrain the radial
  displacement
- load: 50 MPa internal pressure on the inner surface (CAX4 face P4 for the
  counter-clockwise ordering); apply it only to the element touching `r = 10`
- step: `*Static`

CalculiX allows at most 16 entries per data line; split long `*Nset` /
`*Elset` lists across multiple lines. Results reach `.dat` through
`*Node Print`, which needs an explicit node set.

Submit with `/usr/bin/ccx` and produce `solution.dat`, then write
`summary.txt` as two comma-separated numbers: `ur_inner, ur_outer` — the
radial (x) displacements at `x = 10` and `x = 20` (mm).

The evaluator re-solves your deck independently.