# Release checklist

Status: alpha release preparation, started 2026-11-22; public flip deferred.
Repository audit for this checklist: 2026-11-22.

## Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-11-22 | First public release stays under the `lynxpurr` account; moving to a `vericax` organisation is deferred | The organisation name is not registered yet; the benchmark content is ready before the account move (spec/06 §3) |
| 2026-11-22 | Licence: MIT, covering code, task definitions, verifiers and audit records | `LICENSE`; third-party software keeps its own licence and VM images are built from the committed recipes, not vendored |
| 2026-11-22 | Release scope: alpha code and task-suite release with n=1 conformance labelled | n>=3 capability runs are required for leaderboard or paper claims, not for the code release |
| 2026-11-22 | Repository stays private until a separate explicit go-ahead | Flipping visibility is irreversible (history, task packages, audit records) |

Public launch is a separate decision from the GitHub Actions billing blocker
(`docs/ci.md`); do not make the repository public merely as a CI fix.

## Verified state (2026-11-22 audit)

- [x] GitHub detects the licence as MIT; the only commit identity is
      `lynxpurr` with a `users.noreply.github.com` address
- [x] Git history contains no host paths, no `vericax.toml`, no credentials
- [x] No handoff documents are tracked (`docs/handoff-*` are local-only)
- [x] All 26 task packages declare `source: original`; instructions are English;
      splits are 3 + 18 + 1 + 4 = 26
- [x] The EngiWorld runtime dependency is public and MIT
      (<https://github.com/Hongcheng-Gao/EngiWorld>)
- [x] Packed repository is 37.9 MiB; the largest file is a 38 MB scipy wheel,
      below GitHub's 100 MB limit; the wheels embed their licence files
- [x] A clean clone passes `scripts/ci_local.sh` (364 files, 26 packages,
      29 tests, hygiene)

## Before public: code and docs

- [x] Image build recipes require `VERICAX_OSWORLD_SERVER`; no author-specific
      default path remains (`containers/images/*/build.sh` and READMEs)
- [x] `CODE_OF_CONDUCT.md` names a private reporting channel that is not the
      vulnerability-reporting flow
- [x] `docs/ci.md` describes the billing evidence as a historical private-repo
      incident
- [x] `docs/research-provenance.md` refers to an external research workspace
      without "local path" wording and links the public EngiWorld runtime
- [x] `task_proposal.yml` capability list matches the six capabilities in
      spec/10 §1 (`cross-software` is reserved for v1)

## Release mechanics

- [ ] Move `CHANGELOG.md` `[Unreleased]` to `[0.2.0-alpha]` with the release date
- [ ] Add `version` and `date-released` to `CITATION.cff`
- [ ] Release PR `develop -> main` (plain merge, per `BRANCHING.md`), then tag
      `v0.2.0-alpha` on `main` and publish release notes
- [ ] Flip repository visibility, trigger a `develop` CI run, confirm the `ci`
      badge turns green
- [ ] Enable private vulnerability reporting (SECURITY.md depends on it) and
      apply the branch ruleset prepared in `BRANCHING.md`; optionally enable
      Discussions and a social preview

Note: `.githooks/pre-push` blocks direct pushes to `main` and `develop`; release
changes must go through PRs.

## Owner and legal

- [ ] Trademark search: UK IPO, 中国商标网, EUIPO, USPTO (Class 9/42), or an
      explicitly accepted lightweight check (GitHub/PyPI/HuggingFace were 404 on
      2026-11-18). spec/06 §3 still marks the four-database search as mandatory
- [ ] Decide the announcement scope: code-only alpha, or a paper/leaderboard
      launch (the latter needs n>=3 capability runs; current conformance is n=1)

## Verification gap (needs a VM)

- [ ] Quickstart from a clean clone with fresh external assets: clone the
      EngiWorld runtime, build or obtain one self-built image, run one task
      audit end to end
- [ ] Record the image build date and sha256 in the release notes (Ubuntu
      dated cloud-image URLs have finite retention)

## Optional, not blockers

- [ ] Move the 38 MB scipy wheel to a release asset if clone size matters
- [ ] List scipy / scikit-fem / trimesh in `ACKNOWLEDGEMENTS.md` (their wheels
      already embed the licences)
- [ ] Add a PR template and Dependabot/CodeQL

## Post-release

- [ ] Register the `vericax` GitHub and HuggingFace organisations, then move the
      repositories (spec/06 §3)
- [ ] n>=3 capability/leaderboard run
- [ ] Publish the qcow2 images to HuggingFace if demand justifies hosting them