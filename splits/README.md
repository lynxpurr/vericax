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

Current contents: 18 tasks — `fenics/task-0001`, `calculix/task-0004..0012`,
`fenics/task-0002..0005`, `fenics/task-0013..0016`. This is the P0-gated
subset described in `docs/spec/10-suite-matrix.md` §7.1. The `-25` in the
file name is the frozen Phase 2 target label; the suite now has 26 packages
across four splits: `v0.1-cae-cli-pilot` (3), this one (18),
`v0.2-cae-cli-l6-pilot` (1) and `v0.2-cae-cli-merged` (4). Do not rename the
file as the suite grows.

All 26 packages were re-audited on the three self-built images on 2026-11-22
and their L0 records now carry the matching `image_sha256` (spec/10 §3).

### Why `calculix/task-0001..0003` are not listed

They are the Phase 1 validation tasks — the first three packages, built before
the P0 audit gate existed. They remain in the repository and are still
validated by CI (structure + manifest), but the v0.2 split is scoped to the
post-P0 suite: `fenics/task-0001` plus the P1 additions. Re-listing them is a
release decision for the suite owner; all three now have L0 records on the
current self-built CalculiX image (2026-11-22), so no technical L0 work
remains.

### Adding a task

1. It passes `scripts/pack_task.py --task <id>` (writes the manifest; L0 is a
   hard gate here) and `--check` afterwards.
2. It passes the repository test suite and the hygiene scan
   (`scripts/check_repo_hygiene.py`).
3. Append the ID to the split and say in the PR which spec row it advances.