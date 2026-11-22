# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `vericax batch --parallel 2` (P4): concurrent episodes with per-episode
  overlay/container/proxy/cache/scoring, `--payload-dir-map` and
  `--image SNAPSHOT=PATH` for mixed task sets. Two fake episodes scored 1.0
  each in 423 s wall (841 s serial).
- Per-episode L6 challenge binding (P4): `{challenge}` instruction placeholder,
  `VERICAX_CHALLENGE` in the agent container, `VERICAX_CHALLENGE` +
  `VERICAX_TOOL` in the scoring instance. Replayed audit-token artifact is
  rejected (1.0 dynamic vs 0.0 replay).
- Adapters and phase-2 agent image for `opencode 1.19.5`, `hermes 0.21.6`,
  `openclaw 2026.9.9` (P5); n=1 conformance on task-0001 is 1.0 for all three.
- `scripts/ci_local.sh` (CI replica + offline tests), wired into the pre-push
  hook; `docs/ci.md` records the GitHub Actions billing blocker (E).
- `scripts/audit_suite.py`: audit → pack → L0 → pack-check for every package,
  two tasks in flight; used for the default-image switch.
- Self-built default images: all 26 packages re-audited on CalculiX
  `91b1d6c8…`, FEniCS `b0e2f239…` and merged `e6514410…` (2026-11-22).
- task-0014/0016 wheelhouses include `scipy 1.13.1`, the runtime dependency of
  scikit-fem/trimesh that the self-built FEniCS image does not ship.
- `vericax audit --task <id> --group reference`: the L0 benchmark-validity gate.
  It replays the reference case, compares the produced summary with the shipped
  GT summary, runs the verifier, and writes
  `ground_truth/reference_selfcheck.json` (excluded from `resources.sha256`).
- `summary.json` provenance: `run_mode`, `tree_version`, `reference_selfcheck`
  and `kind`. `vericax report` groups by tree/run mode and excludes test/debug
  episodes by default.
- Adapter `output.cost_event_types`; pi uses `message_end` at `message.usage`,
  so streamed `message_update` events are no longer counted as LLM calls.
- `tests/test_audit_tooling.py`: offline tests for verdict expectations, the
  rejection margin and the per-case workspace restore. `scripts/ci_local.sh`
  and the GitHub workflow run 29 tests in total.

### Changed
- `run_episode` now closes the sandbox before booting the scoring instance
  (spec/09 E5), so N parallel episodes hold at most N VMs.
- L6 task instructions use `{challenge}`; `provenance.challenge` remains the
  fixed audit token. Verifiers read `VERICAX_CHALLENGE`/`VERICAX_TOOL` with
  audit-safe defaults.
- Spec calibration from the 2026-11-18/19 EngiWorld audit: L0 GT self-check
  (`02`), `run_mode`/`tree_version`/`reference_selfcheck` (`03`), tolerant
  verifier parsing, CLI artifact-write policy (`04`/`08`/`09`), and the
  benchmark-validity gate (`05`/`10`). Provenance updated.
- Added `docs/lessons-2026-11-19.md` with the audit-calibration rationale.
- `scripts/audit_task.py` snapshots the Desktop after VM reset and restores it
  before every case, and removes regular files created in `/tmp` by the previous
  case. Declared artifacts, solver side files and undeclared scratch can no
  longer leak across audit cases.
- Numeric audit records include the rejection margin
  (`min(accepted) - max(rejected)`); an audit fails when the positive and
  negative score bands overlap. Exact-match tasks record `n/a`.
- `integrity_policy.allow_native_deck_edit` is confirmed in spec/01 section 2
  and spec/02 section 2 as a channel declaration: native decks may be edited,
  but the verifier re-runs the submitted deck and the L6.2 comparison plus the
  N5 fabricated-summary negative cover the anti-forgery path.
- Release preparation: image build recipes now require
  `VERICAX_OSWORLD_SERVER` instead of falling back to an author-specific path;
  the code-of-conduct reporting channel, provenance wording and the task
  proposal capability list were aligned with the public-release policy.

### Fixed
- pi cost accounting on the recorded task-0001 episode: 7 LLM calls / 4,593
  input / 2,897 output / 1,399 reasoning tokens instead of summing every
  streamed update event.

### Planned
- Public alpha release of the task suite and tooling. Moving to a dedicated
  organisation is deferred until the `vericax` name is held.

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
