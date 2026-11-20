# Reconstruct a two-bar truss from the report

`report.md` is the only source of the truss data. Read it, then build the
CalculiX model and solve it.

- use `T3D2` truss elements, 2 members
- the members' square area is in the report; one `*Solid Section` with the
  area line
- supports exactly as reported (nodes 1 and 2 pinned in x/y, all nodes fixed
  in z)
- apply the reported load at node 3
- submit with `/usr/bin/ccx` and produce `solution.inp`, `solution.dat`

Write `summary.txt` as two comma-separated numbers: `ux3, uy3` — the x and y
displacements of node 3, in mm.

The evaluator re-solves your deck independently; the reported numbers must come
from your own run.