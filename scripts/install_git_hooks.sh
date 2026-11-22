#!/usr/bin/env bash
# Point this clone at the repository's tracked hooks.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true
echo "core.hooksPath -> .githooks"
echo "pre-push now rejects direct pushes to main and develop."
