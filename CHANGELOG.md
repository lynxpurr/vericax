# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2-alpha] - 2026-11-27

Tooling patch release; the 26-package task suite is unchanged. `vericax batch`
now survives sandbox losses (fail-fast, retry, breaker), cost accounting reads
every stack and the cache reads, and the published B2 tables are corrected
(infra 19/217 = 8.8 %, the openclaw token column, a cache-read column).

### Added
- Cache-read and cache-write tokens are recorded in the cost record
  (`cache_read_tokens`, `cache_write_tokens`; spec/03) and shown per task in
  the capability report. token/task stays prompt + completion. In B2, cache
  reads were 77 % of what the gateway served to dsh and 88 % for openclaw
  (opencode reports none), so token/task showed about a fifth of the usage.
- Sandbox-loss fail-fast (spec/09 section 9): when a controller call gives up
  on the sandbox, the proxy waits out the runtime's fast-fail window and probes
  once. On confirmation the agent container is stopped (about a minute after
  the first error, instead of at the deadline) and the episode is recorded as
  infra. `logs/sandbox-loss.json` then holds the host memory, load and
  pressure-stall figures, the VM process tree with its peak memory, and the
  VM container's state and log tail.
- Every episode keeps the sandbox guest's console log
  (`logs/vm-console.log`) and a guest baseline (`logs/guest-profile.txt`: OS,
  kernel, init, memory and active timers). The guest console is the only place
  a guest-side crash shows: two VMs left over from a B2-era batch had died in
  a kernel panic (PID 1, systemd, segfaulted) about 35 minutes after boot.
- `vericax batch` retries infra jobs with a new episode once the pass has
  drained (`--infra-retries`, default 2; spec/11 section 3.4) and stops after
  three infra results in a row (`--infra-breaker`). Every attempt is recorded
  in `batch.json` with its attempt number; the verdict is `pass_after_retry`
  when a retry succeeded.
- `vericax batch` checks every task offline before the first VM boots, reports
  VeriCAx VM containers left over from earlier episodes, and waits for free
  memory before each launch (`--min-free-mb`, `--memory-wait`).
- A sandbox that never answers after network isolation now fails the episode
  before the agent starts.
- `capability_report.py --reextract-cost [missing|all]` re-derives cost from
  the stored agent streams: `missing` fills episodes without a cost record,
  `all` re-derives every episode and reports how many recorded token totals
  differ. Used to re-score B2's openclaw tokens and the cache-read column; no
  `summary.json` was changed.
- `tests/test_runtime_reliability.py`: 31 offline tests for the loss check,
  the agent abort, the episode wiring, batch retries and breaker, container
  release and the VM inventory.

### Fixed
- `SandboxVM.close()` retries and verifies the removal of the VM container. A
  transient docker API error used to skip the removal silently and leave a VM
  running; an unverifiable removal now writes `logs/leak.json`.
- A control-channel loss at freeze is classified as `infra_incomplete` with its
  cause; it used to surface as `unexpected: SandboxUnavailable`.
- A harness or configuration error inside a batch job (a stale manifest, for
  example) stops the batch instead of being recorded as infra and retried.
- The proxy closes every accepted connection.
- GitHub Actions runs `tests.test_capability_report`; it was only in the local
  gate.
- Openclaw token usage is read. `openclaw --json` prints one indented JSON
  envelope after a few plain log lines on stderr; the cost extractor only
  parsed whole-line JSON events or an entire-output envelope, so every openclaw
  episode recorded `cost: null`. Re-running the extractor on the 68
  native-scored openclaw episodes of B2 reads usage for all of them. The
  published B2 table carries the re-extracted column since 2026-11-27.
- The pre-batch VM inventory recognises symlinked suite images. It resolved a
  container's image path before comparing it with the images directory, and a
  suite directory links to images stored elsewhere, so every image but the
  batch's own looked foreign and its VM went unreported.
- The proxy's `sandbox_error` record was mislabelled: a field of the same name
  overwrote the record's label in `commands.jsonl`. The loss event is now set
  only after the `sandbox_lost` record is written.

### Known limitations
- The sandbox losses seen in B2 are guest kernel panics. In the self-built
  images PID 1 (systemd 255.4-1ubuntu8.18, kernel 6.8.0-147-generic) dies when
  its main thread faults on return from a system call (`epoll_wait`,
  `clone3`), and a dead PID 1 is a kernel panic. It happens without any agent
  activity: an untouched VM panicked 41 minutes after boot, and VMs with an
  agent at 3.4 and 7 minutes. Host pressure and guest memory were ruled out
  for the captured cases. The trigger is not known. `vericax batch` detects
  the loss about a minute after the first error, records the episode as infra
  and retries it with a new VM; `logs/vm-console.log` and
  `logs/sandbox-loss.json` hold the evidence.

## [0.2.1-alpha] - 2026-11-26

Patch release of the tooling: the per-episode proxy socket fix, the Bailian
adapter variants, the n>=3 capability report tool and the published B2
results. The 26-package task suite is unchanged from v0.2.0-alpha (same
task `tree_version`s).

### Added
- `docs/spec/11-capability-runs.md`: the n>=3 capability-run protocol, batch
  plan (B0–B3), go/no-go gates and the reporting contract.
- `scripts/capability_report.py`: capability x solver x stack matrix with n,
  mean/range, infra count, cost per task, median active time and error
  categories; 9 offline tests, wired into `scripts/ci_local.sh`.
- `adapters/opencode-bailian.toml` and `adapters/openclaw-bailian.toml` with
  their profiles: the same headless contracts on the Aliyun Bailian Token Plan
  gateway; credentials stay in `BAILIAN_API_KEY` via `env_from`.
- v0.2 B2 capability results: 22 tasks × 3 stacks × n=3 on the v0.2.0-alpha
  suite (198 native-scored episodes), published in
  `docs/results/2026-11-24-b2.md`.

### Fixed
- `capability_report.py` now reads `active_duration_seconds` (the previous
  field name left the active-time coverage at 0), reports token/task alongside
  $/task (subscription gateways have no USD estimate), and includes the split
  version per task; unknown token counts render as `-` rather than 0.
- The per-episode proxy socket now lives in a short private `/tmp` directory
  instead of the episode directory. Long adapter names (e.g.
  `opencode-bailian`) pushed the AF_UNIX path over the 108-byte limit and
  failed the episode as `infra_incomplete`; the temp directory is removed when
  the proxy stops.
- `vericax --version` reported `0.1.0` on both release branches; `__version__`
  now tracks the release tag.

### Known limitations
- B2 infra failures were all sandbox control-channel losses; `vericax batch`
  records them but does not retry them automatically yet.
- The openclaw and hermes adapters do not read token usage; their cost is
  reported as `n/a`.

## [0.2.0-alpha] - 2026-11-22

Alpha release of the 26-package suite on the three self-built VM images.
Conformance for the three new stacks is n=1; leaderboard-style comparisons
require n>=3 runs.

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
  hook; `docs/ci.md` records the account-level CI blocker (E), resolved by the
  public repository.
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

### Known limitations
- Conformance for opencode/hermes/openclaw is n=1; no leaderboard claims yet.
- FEniCS ground-truth `.h5` bytes differ between regenerations; pins and
  summaries are stable, and `tree_version` identifies the audited tree.
- `cross-solver/task-0005`'s verifier is 454 lines, a recorded exception in
  spec/02 section 5.

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
