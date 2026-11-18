#!/usr/bin/env bash
# Start a feature branch off an up-to-date develop.
#
#   ./scripts/start_feature.sh task-0004-modal-analysis
set -euo pipefail
slug="${1:?usage: start_feature.sh <slug>}"
cd "$(git rev-parse --show-toplevel)"

git fetch origin
git switch develop
git merge --ff-only origin/develop
git switch -c "feature/$slug"
echo "created feature/$slug off develop; push with: git push -u origin feature/$slug"
