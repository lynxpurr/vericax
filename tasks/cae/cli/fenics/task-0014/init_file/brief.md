# Install scikit-fem and solve a Poisson problem

The image has **no internet**. A local wheelhouse is at
`/home/user/Desktop/wheels`; it contains `scikit-fem` 12.0.2 and its
`scipy` 1.13.1 dependency.

1. Install it into your Python environment, for example:

   ```bash
   python3 -m pip install --user --no-index --find-links wheels scikit-fem==12.0.2
   ```

2. Solve the Poisson problem on the unit square `[0,1] x [0,1]`:

   `-Delta u = 2*pi^2 * sin(pi x) * sin(pi y)`, with `u = 0` on all edges.

   The exact solution is `u = sin(pi x) sin(pi y)`; its maximum is 1.

3. Deliver in `/home/user/Desktop`:
   - `solve.py` — the script that installs/uses scikit-fem and writes the
     summary; it must import `skfem`.
   - `summary.txt` — one number: `max_u`, the maximum nodal value of the
     computed solution.

The evaluator checks that `solve.py` uses scikit-fem and that `max_u` is within
2% of 1. Do not hard-code the answer.