#!/usr/bin/env bash
# Local replica of .github/workflows/ci.yml plus the offline validity tests.
#
# GitHub Actions is currently blocked at the account level (the job never
# starts: "recent account payments have failed or your spending limit needs
# to be increased"). Until billing is fixed, this script is the authoritative
# gate; it runs the same three CI steps and adds tests.test_validity.
#
#   scripts/ci_local.sh            # full gate
#   SKIP_LOCAL_CI=1 git push ...   # bypass the pre-push hook
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"

echo "[ci-local] syntax check"
"$PY" -m compileall -q scripts tasks vericax tests

echo "[ci-local] task package validation"
shopt -s nullglob
checked=0
for dir in tasks/*/*/*/task-*; do
    id="${dir#tasks/}"
    id="${id//\//--}"
    "$PY" scripts/pack_task.py --task "$id" --check >/dev/null
    checked=$((checked + 1))
done
echo "[ci-local] $checked task package(s) match their manifests"

echo "[ci-local] offline validity + audit-tooling + capability-report tests"
"$PY" -m unittest tests.test_validity tests.test_audit_tooling tests.test_capability_report

echo "[ci-local] repository hygiene"
"$PY" scripts/check_repo_hygiene.py

echo "[ci-local] PASS"