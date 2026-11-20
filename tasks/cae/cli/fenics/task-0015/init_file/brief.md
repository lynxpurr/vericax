# Install pygmsh and solve the plate with a central hole

The image has **no internet**. A local wheelhouse is at
`/home/user/Desktop/wheels`; it contains `pygmsh` 7.1.17.

1. Install it, for example:

   ```bash
   python3 -m pip install --user --no-index --find-links wheels pygmsh==7.1.17
   ```

2. Use pygmsh to mesh ONE QUARTER of a thin square plate 200 x 200 mm with a
   central circular hole of radius 10 mm:
   - domain: `x in [0,100]`, `y in [0,100]`, excluding the quarter disk
     `x^2 + y^2 <= 10^2`
   - symmetry: `ux = 0` on `x = 0`; `uy = 0` on `y = 0`
   - hole and `y = 100` traction-free
   - material: `E = 210000 MPa`, `nu = 0.3`, plane stress, thickness 1 mm
   - load: uniform traction `t = (100, 0) MPa` on `x = 100`
   - mesh: triangular, at least 80 element edges along the hole arc, at least
     3000 elements, no nodes inside the hole

3. Solve with dolfinx and deliver in `/home/user/Desktop`:
   - `mesh.msh` — the pygmsh/meshio mesh
   - `solve.py` — the script that meshes with pygmsh and solves; it must import
     `pygmsh`
   - `summary.txt` — one line, two comma-separated numbers:
     `sigma_xx_max, ux_max`, with the same definitions as in the plate task
     (`sigma_xx_max` at the hole arc with a P1 projection; `ux_max` on the
     loaded edge).

The evaluator re-solves the submitted mesh independently and checks that
`solve.py` uses pygmsh.