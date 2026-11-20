# Install trimesh and measure a provided part

The image has **no internet**. A local wheelhouse is at
`/home/user/Desktop/wheels`; it contains `trimesh` 5.2.1.

1. Install it, for example:

   ```bash
   python3 -m pip install --user --no-index --find-links wheels trimesh==5.2.1
   ```

2. Load `/home/user/Desktop/part.stl` with trimesh and compute the volume and
   the total surface area of the solid.

3. Deliver in `/home/user/Desktop`:
   - `solve.py` — the script that loads the STL with trimesh and writes the
     summary; it must import `trimesh`.
   - `summary.txt` — one line, two comma-separated numbers: `volume, area`.

The evaluator checks both values and that `solve.py` uses trimesh. Do not
hard-code the answer.