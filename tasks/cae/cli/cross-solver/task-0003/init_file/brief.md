# Software selection: heterogeneous modulus (challenge token)

The plate has a smooth, spatially varying Young's modulus
E(x,y) = 210000*(1 + 0.5*sin(pi*x/100)*sin(pi*y/100)) MPa. CalculiX can only
carry per-element constant material cards, so the required field-exact
solution with the prescribed P2 discretisation is out of its reach; the
deliverables (gmsh mesh + dolfinx checkpoint) are the FEniCS native pair.

The evaluator re-solves the submitted mesh with the exact E(x,y) field and
compares the checkpoint field at every mesh vertex, not only the summary.
The physical curve `VCAX_AUDIT_0003` must name the loaded edge in the mesh.
