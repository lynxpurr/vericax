# Splits

`splits/*.txt` list the task IDs that make up a release split — one
`domain--interface--software--task` ID per line, blank lines ignored. A task
may only be listed after it passes the package gate:

```bash
python scripts/pack_task.py --task <id>            # writes resources.sha256
python scripts/pack_task.py --task <id> --check    # verifies an existing manifest
```

The gate covers the audit matrix (declared groups, the six negative kinds, the
robustness record, and every case-table row `PASS`) and the L0 reference
record. CI runs `--check` for every package on a fresh checkout, where the L0
record is absent because it is gitignored; L0 is therefore enforced when the
manifest is written and only warned about under `--check`.

## v0.2-cae-cli-25.txt

Current contents: 6 tasks — `fenics/task-0001`, `calculix/task-0004..0006`,
`fenics/task-0002..0003`. This is the P0-gated subset described in
`docs/spec/10-suite-matrix.md` §7.1; the file name keeps the `-25` target
(when the split reaches 25 tasks, rename it).

### Why `calculix/task-0001..0003` are not listed

They are the Phase 1 validation tasks — the first three packages, built before
the P0 audit gate existed. They remain in the repository and are still
validated by CI (structure + manifest), but the v0.2 split is scoped to the
post-P0 suite: `fenics/task-0001` plus the P1 additions. Re-listing them is a
release decision for the suite owner; before that they need an L0 reference
record regenerated on the current image and a fresh `pack_task` run under the
hard L0 gate.

### Adding a task

1. It passes `scripts/pack_task.py --task <id>` (writes the manifest; L0 is a
   hard gate here) and `--check` afterwards.
2. It passes the repository test suite and the hygiene scan
   (`scripts/check_repo_hygiene.py`).
3. Append the ID to the split and say in the PR which spec row it advances.