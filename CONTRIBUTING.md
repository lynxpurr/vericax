# Contributing to VeriCAx

Thanks for helping build an artifact-centric benchmark. Two contribution paths:
**new tasks** and **verifier/tooling improvements**.

## Ground rules

1. **Scores only come from re-opening artifacts.** A verifier that trusts the
   agent's `summary.txt`, logs, or trajectory will be rejected in review.
2. **Every task ships with an audit record.** No audit, no merge — see
   `docs/spec/02-verifier-spec.md` section 4.
3. **Verifiers use the standard library** plus the tested application's own API
   (and Pillow for images). No third-party parsers.
4. **No sealed knowledge in the instruction.** The task text may state formats
   and physical constraints; it must not reveal verifier thresholds or the
   ground-truth values.

## Contributing a task

```bash
cp -r tasks/_template tasks/<domain>/<interface>/<software>/task-<NNNN>
# 1. fill task-<NNNN>.json        (schema: docs/spec/01)
# 2. put starting resources in init_file/          (never verifier material)
# 3. implement eval.py             (declare IMPLEMENTS = ("L1", ...))
# 4. declare audit cases in audit_cases.py         (positive/alternative/negative)
# 5. run the audit inside the evaluation image
python scripts/audit_task.py --task <domain>--<interface>--<software>--task-<NNNN>
# 6. package and validate
python scripts/pack_task.py --task <domain>--<interface>--<software>--task-<NNNN>
```

The audit harness writes `ground_truth/audit.md`. A single `MISS` blocks the
package: fix the task or the verifier, then re-run.

### Task design checklist

- [ ] The scored quantity is measured from a re-opened artifact, not reported text
- [ ] At least one alternative legal encoding is accepted (order-independent checks)
- [ ] Negative cases: empty delivery, fabricated numbers, missing/zero-byte solver output, tampered inputs
- [ ] Numeric tolerances justified (convergence measured, not guessed)
- [ ] If a textbook/analytic value exists, the verifier cross-checks against it
- [ ] `instruction` states units, mesh/format requirements and constraints
- [ ] No proprietary software is redistributed (see `docs/spec/06-naming-and-legal.md`)

## Contributing tooling

- Keep scripts runnable with a plain Python interpreter plus the runtime venv
  used for evaluation (see `docs/setup.md`).
- Preserve the separation between the agent plane and the scoring plane: the
  verifier and ground truth must never be reachable during an episode.
- Add or update the corresponding spec section when behaviour changes; spec and
  code drift is treated as a bug.

## Pull requests

- One logical change per PR; if a task changes, bump the split version instead
  of silently editing an existing task in place (spec/01 section 3).
- CI must pass: syntax check, task package validation, manifest freshness.
- Reference the audit record in the PR description when a verifier changes.

## Commit messages

Short imperative subject, body explains *why*. Example:

```
fix(task-0003): inject print requests per step, not per deck

Unconditional injection duplicated output blocks and broke the L4 block
pairing; the audit caught it as a false negative on the gold case.
```
