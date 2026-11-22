#!/usr/bin/env bash
# Build the phase-2 agent image (hermes + dsh + pi + opencode + openclaw).
# The build context is the Dockerfile plus the vericax-sh client; the
# repository itself never enters the context.
set -euo pipefail
cd "$(dirname "$0")"

TAG="${1:-vericax-agent:phase2}"
CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT

cp ../../vericax/sh_client.py "$CTX/vericax-sh"
chmod 0755 "$CTX/vericax-sh"
cp Dockerfile.phase2 "$CTX/Dockerfile.phase2"

docker build -t "$TAG" -f "$CTX/Dockerfile.phase2" "$CTX"
echo "built $TAG"