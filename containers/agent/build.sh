#!/usr/bin/env bash
# Build the agent container image from a minimal context: the Dockerfile plus
# the vericax-sh client. The repository itself never enters the build context.
set -euo pipefail
cd "$(dirname "$0")"

TAG="${1:-vericax-agent:phase1}"
CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT

cp ../../vericax/sh_client.py "$CTX/vericax-sh"
chmod 0755 "$CTX/vericax-sh"
cp Dockerfile "$CTX/Dockerfile"
cp Dockerfile.fakeslim "$CTX/Dockerfile.fakeslim"

FAKE_TAG="vericax-agent:fakeslim"
docker build -t "$FAKE_TAG" -f "$CTX/Dockerfile.fakeslim" "$CTX"
echo "built $FAKE_TAG"

docker build -t "$TAG" -f "$CTX/Dockerfile" "$CTX"
echo "built $TAG"
