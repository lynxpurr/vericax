# VeriCAx

**Artifact-centric verification benchmark for agents in professional CAx (CAD/CAE/CAM) environments.**

[![ci](https://github.com/lynxpurr/vericax/actions/workflows/ci.yml/badge.svg)](https://github.com/lynxpurr/vericax/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#status)

VeriCAx evaluates a **complete agent stack** (harness + model, not a bare LLM) on
its ability to deliver engineering artifacts inside professional CAx software.
The first principle:

> **Scores only come from re-opening artifacts and checking them executably.**
> An agent's own summary, logs and trajectory are never evidence.
> Every verifier is itself audited (positive / alternative / negative / robust)
> — an unaudited verifier is not trusted.

## Status

Alpha, under active development. Code, task definitions, verifiers and audit
records are released under MIT. Current contents:

| Area | State |
|---|---|
| Specifications | `docs/spec/00`–`10`; latest calibration 2026-11-22 (P4 parallel scheduling, per-episode L6 challenge tokens, P5 stack expansion) |
| Task packages | 26 packages (25 Phase-2 targets + 1 L6 prototype) across CalculiX, FEniCS and a merged cross-solver image; every package has an audit record and L0 self-check |
| Default images | three self-built qcow2 (CalculiX 2.21, FEniCS 0.10.0.post2, merged); all 26 packages re-audited on them on 2026-11-22 |
| Tooling | audit harness, package validator, VM probe, dependency resolver, parallel `vericax batch`, `scripts/audit_suite.py`, local CI gate |
| Agent stacks | dsh 0.2.1-rc.5, pi 1.4.0, opencode 1.19.5, hermes 0.21.6, openclaw 2026.9.9; all five have n≥1 conformance episodes |
| Runtime | Phase 2 complete: tier-1 scoring, per-episode overlays, 2-VM parallel batches, L6 provenance/challenge binding |
| CI | `scripts/ci_local.sh` mirrors the workflow and adds the offline tests; see `docs/ci.md` for the Actions billing history |

## Layout

```
docs/spec/         specifications (the current bulk of the project)
docs/setup.md      how to obtain the external runtime and VM images
docs/lessons-2026-11-19.md  audit-calibration lessons behind the 2026-11-19 spec changes
tasks/             task packages: <domain>/<interface>/<software>/task-<NNNN>/
scripts/           audit_task.py, pack_task.py, vm_exec.py, _config.py, check_setup.py
containers/        agent and VM image build recipes (CalculiX, FEniCS, merged)
tests/             offline validity and audit-tooling tests; conformance/acceptance runners
tasks/_template/   starting point for a new task package
```

## Quickstart

See [docs/setup.md](docs/setup.md). In short: bring an external evaluation
runtime and a VM image, point `vericax.toml` at them, then

```bash
python scripts/check_setup.py
<runtime-venv>/bin/python scripts/audit_task.py \
  --task cae--cli--calculix--task-0001
```

The audit boots one VM, regenerates the ground truth from the gold case, runs
every audit case in `audit_cases.py`, and writes `ground_truth/audit.md`.

## What a task package contains

```
tasks/cae/cli/calculix/task-0001/
├── task-0001.json       instruction, integrity policy, evaluator and metric
├── init_file/           starting resources (injected into the agent environment)
├── eval.py              verifier; declares IMPLEMENTS = ("L1", "L2", "L3", ...)
├── audit_cases.py       positive / alternative / negative cases with expectations
├── ground_truth/        reference artifacts + audit.md (never reachable by the agent)
├── resources.sha256     package manifest, verifier included
```

## Verifier layers

| Layer | Meaning |
|---|---|
| L1 | deliverable completeness — files exist, are non-empty, and re-open |
| L2 | design conformance — the deck actually encodes what the task asked for |
| L3 | independent re-solve — submitted numbers must match the submitted model's own physics |
| L4 | cross-stage consistency — multi-step/multi-artifact invariants |
| L5 | two-stage scoring — feasibility gate, then a normalised quality score |

Details, anti-cheat requirements and the audit protocol:
[`docs/spec/02-verifier-spec.md`](docs/spec/02-verifier-spec.md).

## Repository boundary and external dependencies

This is an independent project, not a mirror of, or workspace for, any other
benchmark repository. Two large assets are **external** and never vendored:

| Dependency | Purpose | Configure with |
|---|---|---|
| evaluation runtime (provides `engine/desktop_env`) | boots VMs, runs episodes | `VERICAX_RUNTIME` or `vericax.toml` → `[runtime] path` |
| decompressed VM image `<snapshot>.qcow2` | task environment | `VERICAX_IMAGE_DIR` or `vericax.toml` → `[images] dir` |

When they are missing the tools fail with setup instructions; they never guess a
sibling directory. `vericax.toml` is gitignored.

## Roadmap

- [x] Specifications and the audit protocol
- [x] Three audited CalculiX pilot tasks covering L1–L5
- [x] Second solver (FEniCS) and a 26-package suite across two solvers and a merged image
- [x] Tier 1 trusted loop: out-of-band verifier execution and the anti-cheat layer as runtime code
- [x] Five agent stacks and 2-VM parallel scheduling with per-episode challenge binding
- [ ] Public alpha release of the task suite and tooling (organisation move deferred)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Task contributions require a verifier and
a `MISS`-free audit record. Security aspects (evaluation bypasses) are described in
[SECURITY.md](SECURITY.md).

## Provenance

Several structural ideas come from a hands-on study of
[EngiWorld](https://arxiv.org/abs/2609.37686) (MIT): the three-asset layout, the
task definition shape, artifact-centric verification and its audit protocol.
That study also produced a 20-task CalculiX baseline with one model (2/20
delivered correct artifacts); the failures were dominated by *wrong physics*
rather than an inability to drive the solver, which is precisely the gap
artifact-level verification is meant to expose. Attribution details:
[ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).

## License

MIT — see [LICENSE](LICENSE). Third-party engineering software keeps its own
licence: task definitions may be published for proprietary applications
(Abaqus, ANSYS), but their images are never distributed here.
