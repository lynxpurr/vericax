# Branching model

```
main      ●────────────●────────────●      releases only (tags)
           ╲          ╱ ╲          ╱
            ╲        ╱   ╲        ╱        release PRs, develop -> main
develop  ●──●──●──●──●─────●──●──●         integration branch (default)
           ╲    ╱     ╲       ╱
feature/*   ●──●       ●─────●             one branch per change, PR into develop
```

| Branch | Role | Who writes |
|---|---|---|
| `main` | Release branch. Every commit here is a released state; tagged `vX.Y.Z` | merge from `develop` only, through a PR |
| `develop` | Integration branch, repository default. Everything that passes review and CI lands here | merge from `feature/*` (or `hotfix/*`) through a PR |
| `feature/<slug>` | One logical change, branched off `develop` | the author, freely |
| `hotfix/<slug>` | Urgent fix for a released state, branched off `main` | the author |

## Daily flow

```bash
git switch develop && git pull
git switch -c feature/<slug>
# ... work, commit ...
git push -u origin feature/<slug>
gh pr create --base develop --fill
# wait for CI, then:
gh pr merge --squash --delete-branch
```

Release:

```bash
gh pr create --base main --head develop --title "release: vX.Y.Z"
gh pr merge --merge          # keep the history of develop visible on main
git switch main && git pull
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
```

Hotfix (released state is broken):

```bash
git switch main && git pull
git switch -c hotfix/<slug>
# fix, then PR to main; after the release tag, back-merge into develop:
gh pr create --base develop --head main --title "chore: back-merge hotfix"
```

## Rules that apply to every PR

1. Target `develop` (features) or `main` (releases/hotfixes) — never push directly.
2. CI must pass (`validate` in this repository).
3. One logical change per PR; a changed task package updates its `resources.sha256` in the same PR.
4. Squash-merge features; plain merge for `develop -> main` releases.
5. Delete the branch after merge.
6. Tag releases on `main` only.

## Enforcement

Server-side rulesets (require PR, require status checks, block force-push and
deletion) need **GitHub Pro** for private repositories: the API currently
returns `403 Upgrade to GitHub Pro`. Until then, protection is **local**:

```bash
./scripts/install_git_hooks.sh      # sets core.hooksPath to .githooks
```

`.githooks/pre-push` rejects any push to `main` or `develop`; pushes of
`feature/*` and `hotfix/*` branches pass. Override for an emergency only:

```bash
ALLOW_DIRECT_PUSH=1 git push origin develop
```

When the plan allows (or the repository goes public), apply this ruleset and the
local hook becomes a second line of defence:

```bash
gh api --method POST repos/<owner>/<repo>/rulesets --input - <<'JSON'
{
  "name": "protected-branches",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["refs/heads/main", "refs/heads/develop"], "exclude": [] }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true
      } },
    { "type": "required_status_checks",
      "parameters": {
        "required_status_checks": [{ "context": "validate" }],
        "strict_required_status_checks_policy": true
      } }
  ]
}
JSON
```

Drop the `required_status_checks` rule for repositories without CI.
