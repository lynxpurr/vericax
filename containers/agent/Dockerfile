# VeriCAx agent container recipe (D2b, spec/09 section 4).
#
# Carries the Phase 1 target stacks (dsh, pi) and the vericax-sh client.
# It deliberately contains NO repository content and NO credentials: the repo
# is never mounted (D2b) and credentials are injected at run time by the
# harness from the host environment (adapter [container] env_from).
#
# Build: containers/agent/build.sh  (the build context is assembled from this
# directory plus ../sh_client.py; nothing else is copied in).
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pinned stack versions match the adapters (spec/08 section 5, D1).
RUN npm install -g \
    "@deepseek-ai/dsh@0.2.1-rc.5" \
    "@earendil-works/pi-coding-agent@1.4.0"

COPY vericax-sh /usr/local/bin/vericax-sh
RUN chmod 0755 /usr/local/bin/vericax-sh

WORKDIR /vericax
