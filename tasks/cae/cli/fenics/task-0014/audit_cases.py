"""Audit cases for cae--cli--fenics--task-0014 (open-environment).

The agent installs scikit-fem from the local wheelhouse and solves a Poisson
problem whose exact maximum is 1. The verifier checks the script uses
scikit-fem and the reported maximum.
"""

INSTALL = r"""
set -e
cd /home/user/Desktop
python3 -m pip install --user --no-index --find-links wheels scikit-fem==12.0.2 >/dev/null 2>&1
"""

SOLVE = r'''import numpy as np
from skfem import *
from skfem.models.poisson import laplace

m = MeshTri().refined(REFINE)
basis = Basis(m, ElementTriP1())
A = laplace.assemble(basis)

@LinearForm
def rhs(v, w):
    return 2 * np.pi**2 * np.sin(np.pi * w.x[0]) * np.sin(np.pi * w.x[1]) * v

b = rhs.assemble(basis)
u = solve(*condense(A, b, D=basis.get_dofs()))
with open("summary.txt", "w") as fh:
    fh.write(f"{float(u.max()):.8f}\n")
'''


def _run(refine=5) -> str:
    return (
        INSTALL
        + "cat > solve.py <<'PYEOF'\n"
        + SOLVE.replace("REFINE", str(refine))
        + "PYEOF\n"
        + "python3 solve.py\n"
    )


GOLD = _run(5)
FINER = _run(6)
ALT2 = INSTALL + r"""
cat > solve.py <<'PYEOF'
import numpy as np
from skfem import *
from skfem.models.poisson import laplace

m = MeshTri().refined(4)
basis = Basis(m, ElementTriP2())
A = laplace.assemble(basis)

@LinearForm
def rhs(v, w):
    return 2 * np.pi**2 * np.sin(np.pi * w.x[0]) * np.sin(np.pi * w.x[1]) * v

b = rhs.assemble(basis)
u = solve(*condense(A, b, D=basis.get_dofs()))
with open("summary.txt", "w") as fh:
    fh.write(f"{float(u.max()):.8f}\n")
PYEOF
python3 solve.py
"""

COARSE = _run(1)

WRONG_SOURCE = INSTALL + r"""
cat > solve.py <<'PYEOF'
import numpy as np
from skfem import *
from skfem.models.poisson import laplace

m = MeshTri().refined(5)
basis = Basis(m, ElementTriP1())
A = laplace.assemble(basis)

@LinearForm
def rhs(v, w):
    return np.pi**2 * np.sin(np.pi * w.x[0]) * np.sin(np.pi * w.x[1]) * v

b = rhs.assemble(basis)
u = solve(*condense(A, b, D=basis.get_dofs()))
with open("summary.txt", "w") as fh:
    fh.write(f"{float(u.max()):.8f}\n")
PYEOF
python3 solve.py
"""

NO_SKFM = r"""
set -e
cd /home/user/Desktop
cat > solve.py <<'PYEOF'
value = 1.0
with open("summary.txt", "w") as fh:
    fh.write(f"{value}\n")
PYEOF
python3 solve.py
"""

MISSING_SCRIPT = GOLD + "\nrm -f /home/user/Desktop/solve.py\n"

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = float(Path("/home/user/Desktop/summary.txt").read_text())
Path("/home/user/Desktop/summary.txt").write_text(f"{v * 1.10!r}\n")
PYEOF
"""

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '1.0' > summary.txt
"""

ENCODE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
import base64
from pathlib import Path
raw = Path("/home/user/Desktop/summary.txt").read_text().strip().encode()
Path("/home/user/Desktop/summary.txt").write_text(base64.b64encode(raw).decode() + "\n")
PYEOF
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N2 wrong source term": "tampered_input",
    "N5 fabricated summary": "fabricated_field",
    "N6 missing solve.py": "skipped_steps",
    "N7 metrics only": "metrics_only",
    "N8 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (finer mesh)", FINER, ("true",)),
    ("A2 alternative legal (P2 element)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 wrong source term", WRONG_SOURCE, ("false",)),
    ("N3 hand-written summary without skfem", NO_SKFM, ("false",)),
    ("N4 coarse mesh", COARSE, ("false",)),
    ("N5 fabricated summary", FABRICATE, ("false",)),
    ("N6 missing solve.py", MISSING_SCRIPT, ("false",)),
    ("N7 metrics only", METRICS_ONLY, ("false",)),
    ("N8 encoded payload", ENCODE_SUMMARY, ("false",)),
]