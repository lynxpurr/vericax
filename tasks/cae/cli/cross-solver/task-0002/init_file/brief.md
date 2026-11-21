# Software selection: buckling verification (challenge token)

The client needs a linearized buckling verification of a slender column and
requires the deliverables in the solver's **native archive format**: an
Abaqus-style input deck plus the solver's own printed result file. Only one
of the two installed tools (CalculiX 2.21, FEniCSx/dolfinx 0.10) produces
that native pair for a buckling analysis.

Problem: uniform column 100 mm, 10 x 10 mm square section, clamped at
x = 0, axial reference load -1000 N at the tip. The evaluator re-runs the
deck and compares the buckling factors and the **full-field** eigenmode, not
only the summary. The node set `VCAX_AUDIT_0002` must appear in the deck and
in the printed result.
