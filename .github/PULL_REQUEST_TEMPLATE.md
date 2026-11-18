## What changed

<!-- one paragraph: the behaviour change and why -->

## Type

- [ ] New task package
- [ ] Verifier change (audit record updated?)
- [ ] Tooling
- [ ] Spec/documentation

## Verification

- [ ] `python scripts/pack_task.py --task <id> --check` passes for every touched task
- [ ] For verifier changes: `scripts/audit_task.py` re-run and `audit.md` shows no `MISS`
- [ ] No credentials, machine paths, or proprietary binaries added
- [ ] Spec updated where behaviour changed

## Notes for reviewers

<!-- tricky tolerances, alternative encodings considered, negative cases added -->
