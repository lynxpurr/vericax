# CI notes

GitHub Actions is the primary CI. While the repository was private, a run could
be blocked before the first step by an **account-level condition** (not a code
failure, and not a workflow bug). The authoritative local replica is:

```bash
scripts/ci_local.sh
```

It runs the same three steps as `.github/workflows/ci.yml` plus the offline
tests; the `pre-push` hook runs it automatically (install once with
`scripts/install_git_hooks.sh`). `SKIP_LOCAL_CI=1 git push` is the documented
escape hatch. The local gate is also part of the Phase 2 acceptance evidence.

The repository became public on 2026-11-22. Standard GitHub-hosted runners run
the workflow again, and `main` and `develop` are green. If a run still fails
before step 1, treat it as an account-level condition rather than a code
regression and run `scripts/ci_local.sh`.

Account-level details are not published; they are kept in the maintainer's
private release records.