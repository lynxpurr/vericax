# Two-bar truss report

All dimensions are in mm; forces in N.

## Nodes

| node | x | y | z |
|---|---|---|---|
| 1 | 0 | 0 | 0 |
| 2 | 1000 | 0 | 0 |
| 3 | 500 | 500 | 0 |

## Members

| member | nodes | area (mm^2) |
|---|---|---|
| 1 | 1-3 | 100 |
| 2 | 2-3 | 100 |

## Supports

- node 1: pinned (x and y)
- node 2: pinned (x and y)
- all nodes: z fixed

## Load

- node 3: FY = -1000 N

## Material

- steel: E = 210000 MPa, nu = 0.3