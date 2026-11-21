# Software selection: advection-diffusion transport (challenge token)

A steady advection-diffusion transport problem with a spatially varying
diffusivity kappa(x,y) = 10*(1+0.3*sin(pi*x/100)*sin(pi*y/100)) and a
convective velocity b = (1, 0). Neither the advective term nor the smooth
coefficient field exists in CalculiX's equation set, and the required
deliverables (gmsh mesh + dolfinx checkpoint) are the FEniCS native pair.

The evaluator re-solves the submitted mesh with the exact coefficients and
compares the checkpoint field at every mesh vertex, not only the summary.
The physical curve `VCAX_AUDIT_0004` must name the outflow edge x = 100.
