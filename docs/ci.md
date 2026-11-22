# CI status — GitHub Actions billing blocker (E, 2026-11-22)

## Symptom

Every workflow run fails before the first step. The run annotation is:

> The job was not started because recent account payments have failed or your
> spending limit needs to be increased. Please check the 'Billing & plans'
> section in your settings.

Evidence (private repo `lynxpurr/vericax`, run `44918331036`, `develop` push
on 2026-11-21):

```text
X validate in 2s (ID 136888661329)
X The job was not started because recent account payments have failed ...
```

The job duration is 2–4 s because no runner is ever allocated. This is an
account-level condition, not a workflow bug: `gh api
/repos/lynxpurr/vericax/actions/permissions` reports Actions enabled
(`allowed_actions: all`).

## What is authoritative until this is fixed

`scripts/ci_local.sh` replicates `.github/workflows/ci.yml` and adds the
offline validity tests:

```bash
scripts/ci_local.sh
```

The `pre-push` hook runs it automatically (install once with
`scripts/install_git_hooks.sh`); `SKIP_LOCAL_CI=1 git push` is the documented
escape hatch. The local gate is also part of the Phase 2 acceptance evidence.

## Human options

Only an account owner can clear the root cause:

1. **Fix billing** — settle the failed payment / raise the spending limit in
   GitHub *Settings → Billing & plans*. No code change is needed; the existing
   workflow then starts. This is the least disruptive option.
2. **Make the repository public** — standard GitHub-hosted runners are free
   for public repositories. This publishes code and history and is a separate
   release decision (spec/06, D4); it is *not* implied by fixing CI.
3. **Self-hosted runner** — add a runner and switch `runs-on`; requires a host
   with the toolchain and a registration token, and is out of scope for the
   current single-workstation setup.

Option 1 is recommended. Until one is chosen, do not treat a red `ci` badge as
a code regression; run `scripts/ci_local.sh` instead.