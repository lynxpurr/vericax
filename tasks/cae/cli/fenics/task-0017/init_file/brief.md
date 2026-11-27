# Thermo-elastic two-stage analysis of a quarter plate with a hole

A thin square plate 200 mm x 200 mm with a central circular hole of radius
`20 mm` carries a volumetric heat source and, in one load case, a uniform
tension. Model **one quarter** of the plate (a 100 mm x 100 mm domain with the
hole quarter at the origin) and run two stages on the **same mesh**.

## Stage 1: steady heat conduction

`-k div(grad T) = f` with `k = 45` and the source

```
f(x) = 4.0 * cos(pi * x / 200)
```

(largest at `x = 0`, zero at `x = 100`).

- `T = 0` on the edge `x = 100`
- every other boundary, including the hole arc, is insulated (zero flux)
- continuous piecewise-linear (`P1 Lagrange`) elements for `T`

## Stage 2: plane-stress thermo-elasticity with the Stage-1 temperature

```
sigma = 2 mu eps + lam_star tr(eps) I - beta T I
mu        = E / (2 (1 + nu))
lam       = E nu / ((1 + nu) (1 - 2 nu))
lam_star  = 2 lam mu / (lam + 2 mu)
beta      = E alpha / (1 - nu)          (plane stress)
```

- `E = 210000 MPa`, `nu = 0.3`, `alpha = 1.2e-5 1/K`, thickness `1 mm`
- symmetry: `ux = 0` on the edge `x = 0`; `uy = 0` on the edge `y = 0`
- all other edges are traction-free unless a traction is listed
- continuous piecewise-quadratic (`P2 Lagrange`) vector elements for the
  displacement

Run three load cases of Stage 2 on the same mesh:

| case   | temperature                 | traction                                     |
|--------|-----------------------------|----------------------------------------------|
| `th`   | the Stage-1 temperature     | none                                         |
| `m`    | `T = 0`                     | `t = (100, 0) MPa` on the edge `x = 100`     |
| `both` | the Stage-1 temperature     | `t = (100, 0) MPa` on the edge `x = 100`     |

## Deliver in `/home/user/Desktop`

1. `mesh.msh`: a gmsh ASCII mesh (2.2 or 4.1) of the quarter domain with
   triangular elements, refined around the hole: at least 80 element edges
   along the hole arc, at least 3000 triangular elements in total, and no
   nodes inside the hole.
2. `solve.py`: the Python script that builds the mesh and solves both stages
   (kept for reproduction; the evaluator does not execute it).
3. `summary.txt`: exactly one line with four comma-separated numbers
   `T_max, ux_th, ux_m, ux_both` where
   - `T_max` is the maximum temperature over the mesh vertices, in K;
   - `ux_th`, `ux_m`, `ux_both` are, for the `th`, `m` and `both` cases, the
     mean of `ux` along the edge `x = 100` (the integral of `ux` over that
     edge divided by its length, 100 mm), in mm.

The three cases must come from one consistent model on the same mesh. Solve
with dolfinx. The evaluator re-solves both stages on the submitted mesh
independently and cross-checks the three cases against each other; the
reported numbers must come from your own computation on that mesh.
