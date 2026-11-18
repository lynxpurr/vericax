# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
private vulnerability reporting (Security → Advisories → "Report a
vulnerability") on this repository. Include reproduction steps and the affected
task or script.

We aim to acknowledge reports within 7 days.

## Threat model of a benchmark

VeriCAx scores agents, so the relevant "vulnerabilities" are usually
**evaluation bypasses** rather than memory-safety bugs:

| Risk | What we do |
|---|---|
| Agent reads the verifier or ground truth during an episode | Verifier and `ground_truth/` are injected only after the episode ends (spec/02 section 3); tasks ship an integrity policy that forbids reading scoring material |
| Agent fabricates the scored numbers | Every score is recomputed from re-opened artifacts; the submitted summary is cross-checked against an independent re-solve |
| Verifier accepts a wrong-but-plausible artifact | Negative audit cases (empty, fabricated, tampered, wrong-physics) must all be rejected before a task is published |
| Verifier rejects a legitimate alternative solution | Alternative-encoding audit case must pass before publication |
| Hidden rule leakage in error messages | Verifier failures print a single `debug:` reason on the scoring side; no rule enumeration to the agent |
| Malicious task package from a contributor | `scripts/pack_task.py` validates structure, blocks scoring artifacts inside `init_file/`, and pins file hashes in `resources.sha256` |

## Secrets

This repository must never contain credentials. Configuration that points at
external assets lives in `vericax.toml`, which is gitignored; CI fails on any
tracked file matching obvious secret patterns.
