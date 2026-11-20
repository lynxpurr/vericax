import numpy as np
from skfem import *
from skfem.models.poisson import laplace

m = MeshTri().refined(5)
basis = Basis(m, ElementTriP1())
A = laplace.assemble(basis)

@LinearForm
def rhs(v, w):
    return 2 * np.pi**2 * np.sin(np.pi * w.x[0]) * np.sin(np.pi * w.x[1]) * v

b = rhs.assemble(basis)
u = solve(*condense(A, b, D=basis.get_dofs()))
with open("summary.txt", "w") as fh:
    fh.write(f"{float(u.max()):.8f}\n")
