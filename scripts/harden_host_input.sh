#!/usr/bin/env bash
# R1 hardening: stop containers from reaching the VM control ports on the HOST.
#
# Background: the external runtime publishes the sandbox VM's control ports
# (5000/8006/9222/8080 base, allocated upward) on 0.0.0.0. An agent container
# on the default bridge can therefore reach the VM's control server through
# the host gateway, bypassing the vericax-sh proxy log. Scoring integrity is
# unaffected (tier-1 scores frozen copies in a separate VM), but the proxy
# audit trail can be bypassed.
#
# This script blocks host INPUT from the docker bridge subnet to the OSWorld
# port ranges, while leaving host->VM control traffic untouched. It needs root
# ONCE; rules do not survive a reboot (re-run after boot).
#
#   sudo scripts/harden_host_input.sh            # apply
#   sudo scripts/harden_host_input.sh --remove   # remove the rules
#
# Verify after applying:
#   docker run --rm --network bridge curlimages/curl -sS -m 3 \
#       "http://$HOST_GATEWAY:5000/screenshot"   # expected: connection refused/timeout
set -euo pipefail
[ "$(id -u)" = "0" ] || { echo "run as root (sudo $0)" >&2; exit 1; }

CHAIN=INPUT
BRIDGE_IF="${VERICAX_AGENT_BRIDGE_IF:-docker0}"
PORTS="5000:5100,8006:8100,9222:9300,8080:8200"

RULE=(-i "$BRIDGE_IF" -p tcp -m multiport --dports "$PORTS" -m comment \
      --comment "vericax: block container->host VM control ports (R1)" -j DROP)

remove_rules() {
    while iptables -C "$CHAIN" "${RULE[@]}" 2>/dev/null; do
        iptables -D "$CHAIN" "${RULE[@]}"
    done
}

if [ "${1:-}" = "--remove" ]; then
    remove_rules
    echo "removed vericax R1 rules from $CHAIN"
    exit 0
fi

if iptables -C "$CHAIN" "${RULE[@]}" 2>/dev/null; then
    echo "vericax R1 rule already present on $CHAIN"
else
    iptables -I "$CHAIN" 1 "${RULE[@]}"
    echo "inserted vericax R1 rule on $CHAIN (bridge $BRIDGE_IF, ports $PORTS)"
fi
iptables -S "$CHAIN" | grep -F "vericax: block container->host" || true