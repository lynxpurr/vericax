# Release checklist

Status: alpha release preparation, started 2026-11-22.

## Decisions

| Date | Decision | Rationale |
|---|---|---|
| 2026-11-22 | First public release stays under the `lynxpurr` account; moving to a `vericax` organisation is deferred | The organisation name is not registered yet; the benchmark content is ready before the account move (spec/06 §3) |
| 2026-11-22 | Licence: MIT, covering code, task definitions, verifiers and audit records | `LICENSE`; third-party software keeps its own licence and VM images are built from the committed recipes, not vendored |
| 2026-11-22 | Release scope: alpha code and task-suite release with n=1 conformance labelled | n>=3 capability runs are required for leaderboard or paper claims, not for the code release |

Public launch is a separate decision from the GitHub Actions billing blocker
(`docs/ci.md`); do not make the repository public merely as a CI fix.

## Engineering

- [x] MIT `LICENSE`, `README`, `CONTRIBUTING`, `CODE_OF_CONDUCT`, `SECURITY`,
      `CITATION.cff`, `ACKNOWLEDGEMENTS.md`
- [x] VM image build recipes committed (`containers/images/*`); images are not
      vendored
- [x] 26 task packages audited on the default self-built images; splits frozen
- [x] Local gate `scripts/ci_local.sh`: 26 packages, 29 offline tests, hygiene
- [x] Git history scan: no host paths, no `vericax.toml`, no credentials
- [x] GitHub workflow runs the same offline tests as the local gate
- [x] Clean clone passes `scripts/ci_local.sh` (2026-11-22: 364 files,
      26 packages, 29 tests, no `vericax.toml`)
- [ ] Tag `v0.2.0-alpha` and publish release notes
- [ ] Verify the quickstart from a clean clone with fresh external assets
      (runtime plus one self-built image)

## Owner and legal (required before the repository is public)

- [ ] Trademark search: UK IPO, 中国商标网, EUIPO, USPTO (Class 9/42) —
      spec/06 §3 marks this mandatory before release
- [ ] Decide the announcement scope: code-only alpha, or a paper/leaderboard
      launch (the latter needs n>=3 capability runs; current conformance is n=1)
- [ ] Flip repository visibility, then confirm the `ci` badge turns green

## Post-release (not blockers)

- [ ] Register the `vericax` GitHub and HuggingFace organisations, then move the
      repositories (spec/06 §3)
- [ ] n>=3 capability/leaderboard run
- [ ] Publish the qcow2 images to HuggingFace if demand justifies hosting them