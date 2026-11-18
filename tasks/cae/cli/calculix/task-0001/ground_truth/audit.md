# Verifier audit record

- date: 2026-11-18
- image: CalculiX-2.21.qcow2 (same image as evaluation)
- verifier: task-0001/eval.py (IMPLEMENTS L1, L2, L3)
- ground truth: `summary.txt` = -0.05981791, -0.3463916

| group | case | expected | actual | verdict |
|---|---|---|---|---|
| — | P1 positive (ground truth) | True | True | PASS |
| — | P2 robust (same input re-run) | True | True | PASS |
| — | A1 alternative legal deck | True | True | PASS |
| — | N1 empty delivery | False | False | PASS |
| — | N2 fabricated summary | False | False | PASS |
| — | N3 zero-byte dat | False | False | PASS |
| — | N4 tampered sections | False | False | PASS |

Notes:
- Scored quantities are NODAL displacements (uy at node 6 and node 11), which
  converge with mesh refinement. Beam stress output is deliberately not scored:
  CalculiX reports it at section Gauss points (~0.58x the outer-fibre stress)
  and the requested value would be ambiguous.
- Mesh convergence was measured before freezing the task: 1 element/segment
  gives -0.144 (24% below beam theory); the prescribed 10-element mesh gives
  -0.3464 vs analytic -0.3504 (1.1%), inside the verifier's 2% band.
- The alternative deck permutes node/element/section order, splits elements
  across two cards and adds output requests; L2 compares order-independently,
  so it must be accepted.
- N4 is rejected at L2 (the tampered section leaves the elset reference
  dangling), before L3 could compare physics: both layers are exercised by
  N2 (fabricated numbers) and N3 (missing solver output) respectively.
