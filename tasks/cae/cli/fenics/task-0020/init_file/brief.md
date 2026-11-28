# Elliptical hole shape design under two load cases (quarter model)

A thin square plate 200 mm x 200 mm with a central elliptical hole carries
two independent uniform uniaxial tension load cases.

Model ONE QUARTER of the plate (a 100 mm x 100 mm domain with the quarter hole
at the origin):

- domain: `x in [0, 100]`, `y in [0, 100]`, excluding the quarter ellipse
  `x^2/a^2 + y^2/b^2 <= 1` around the origin
- design variables: the hole semi-axes `a` and `b`, with the hole area fixed:
  `a*b = 100 mm^2`, `5 <= a <= 20`, `5 <= b <= 20`
- symmetry (both load cases): `ux = 0` on the edge `x = 0`; `uy = 0` on the
  edge `y = 0`
- material: `E = 210000 MPa`, `nu = 0.3`, plane stress, thickness 1 mm
- load case 1 (`LC1`): uniform traction `t = (100, 0) MPa` on the edge
  `x = 100`; the edge `y = 100` is traction-free
- load case 2 (`LC2`): uniform traction `t = (0, 40) MPa` on the edge
  `y = 100`; the edge `x = 100` is traction-free
- the hole boundary is traction-free; the two load cases are independent and
  are each solved on the same mesh

Deliver in `/home/user/Desktop`:

1. `mesh.msh`: gmsh ASCII mesh (2.2 or 4.1), triangular elements, refined
   around the hole so the peak stresses are mesh-converged: at least 80
   element edges along the hole arc, between 3000 and 80000 triangles, and no nodes
   inside the hole.
2. `solve.py`: the script that builds and solves the model (not executed by
   the evaluator).
3. `summary.txt`: exactly one line with four comma-separated numbers:
   `a, b, s1, s2` where
   - `a`, `b` are the semi-axes of the meshed hole, in mm;
   - `s1` is the maximum `sigma_xx` at the mesh vertices on the hole
     boundary (`|sqrt((x/a)^2+(y/b)^2) - 1| <= 1e-3`) under `LC1`, in MPa,
     evaluated by projecting the stress field to a continuous field (for
     example P1) before taking the maximum;
   - `s2` is the maximum `sigma_yy` at the mesh vertices on the hole
     boundary (same vertex selection) under `LC2`, in MPa, evaluated with the
     same continuous projection.

Objective: minimise the worst-case stress index `K = max(s1, s2) / 100` at
the fixed hole area: the larger of the two peak stresses, divided by the
100 MPa reference stress. The score is the normalized reduction of `K` from
the circular baseline (`a=b=10`, `K` about 3.085) toward the best ellipse in
the design box (`a/b` about 2, `K` about 2.062): `score = clamp((3.085 - K) / (3.085 - 2.062), 0, 1)`.
A mesh that violates the geometry, fixed-area, bounds or refinement
requirements scores 0.

Solve both load cases with dolfinx using quadratic (P2) displacement
elements on the submitted linear-triangle mesh; the evaluator's re-solve
does the same. The evaluator re-solves the submitted mesh independently
under both load cases; the reported numbers must come from your own
computation on that mesh.
