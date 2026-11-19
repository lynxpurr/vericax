# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Spec calibration from the 2026-11-18/19 EngiWorld audit: L0 GT self-check
  (`02`), `run_mode`/`tree_version`/`reference_selfcheck` (`03`), tolerant
  verifier parsing, CLI artifact-write policy (`04`/`08`/`09`), and the
  benchmark-validity gate (`05`/`10`). Provenance updated.
- Added `docs/lessons-2026-11-19.md` with the audit-calibration rationale.

### Planned
- Fourth pilot task on a second solver (FEniCS) to demonstrate that the verifier
  layers are solver-agnostic.
- Tier 1 (trusted loop): out-of-band verifier execution and the anti-cheat layer
  from `docs/spec/02` section 2 implemented as reusable runtime code.
- Public release of the task suite under the `vericax` organisation.

## [0.1.0] - 2026-11-18

First working slice of the framework: specifications, three audited CalculiX
tasks, and the audit/packaging toolchain.

### Added
- Specification set `docs/spec/00`–`07`: vision and scope, task package schema,
  verifier specification (five layers, anti-cheat, audit protocol), scoring and
  result schema, environment specification, roadmap, naming/legal analysis, and
  an Abaqus porting guide.
- `tasks/cae/cli/calculix/task-0001` — stepped cantilever, `exact_match`,
  implements L1/L2/L3; audit 7/7.
- `tasks/cae/cli/calculix/task-0002` — mass-minimising stepped beam,
  `quantified_score`, implements L1/L2/L3/L5 with a two-stage gate; audit 9/9.
  The reference design scores exactly the analytic optimum (0.350000).
- `tasks/cae/cli/calculix/task-0003` — two load cases in one job, implements
  L1/L2/L3/L4; the cross-stage check requires a step-2/step-1 displacement ratio
  of exactly 2; audit 8/8.
- `scripts/audit_task.py` — one-boot audit harness driven by per-task
  `audit_cases.py`; supports boolean and numeric expectations and bakes pinned
  reference values from the gold run.
- `scripts/pack_task.py` — package validation (structure, leakage checks, audit
  record) and `resources.sha256` manifest.
- `scripts/vm_exec.py` — VM probe for task authoring.
- `scripts/_config.py` — single resolver for the two external assets (runtime
  checkout and VM images), with environment variables taking precedence over a
  gitignored `vericax.toml`. No fallback to any sibling directory.

### Notes
- Verifier behaviour is documented in `docs/spec/04` section 6, including the
  measured CalculiX output pitfalls: `.dat` requires `*Node Print` with explicit
  sets, beam stresses are reported at section Gauss points (~0.58x the
  outer-fibre value), and a 1-element-per-segment mesh underestimates deflection
  by 24% while a 10-element mesh converges within 1%.
