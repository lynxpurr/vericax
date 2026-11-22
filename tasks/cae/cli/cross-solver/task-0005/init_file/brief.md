# Software selection: modal verification (challenge token)

The client needs a modal verification of a thin plate and requires the
deliverables in the solver's **native archive format**: an Abaqus-style deck
plus the solver's own printed eigenvalue table and mode shapes. Pick the tool
that can produce that native pair.

Problem: 2D plane-stress plate (see task JSON / instruction). The evaluator
re-runs the deck and compares the eigenvalue table and the mode-1 field, not
only the summary. The challenge node set named in your task instruction must
appear in the deck and in the printed result.
