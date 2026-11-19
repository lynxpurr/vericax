# Agent container (Phase 1)

The agent never sees the repository or the VM's forwarded ports (D2b,
spec/09 §4). Per episode the harness runs ONE container whose main process is
the adapter's launch argv, with:

- bridge network only (never `--network=host`);
- no repo mounts — only harness-owned episode files: `instruction.md` (ro),
  the proxy socket, the per-run state dir (rw), and for scripted agents a
  payload dir (ro);
- credentials injected at run time from the host environment
  (adapter `[container] env_from`), never baked into the image;
- deadline enforced from outside: `docker stop` (SIGTERM, adapter grace,
  SIGKILL) kills the whole cgroup.

## Build

```bash
containers/agent/build.sh                # -> vericax-agent:phase1
```

The build context is assembled from the Dockerfile plus `vericax/sh_client.py`
(the `vericax-sh` the agent calls). Pinned versions live in the Dockerfile and
must match `adapters/*.toml`.

## Residual risk (Phase 1, documented)

The runtime's docker provider publishes the VM's server ports on all host
interfaces, so a container could reach the VM control server via the host
gateway, bypassing proxy logging. Scoring integrity is unaffected (tier-1
scores in a separate VM from frozen copies), but the proxy audit log could be
bypassed by a misbehaving agent. Host-level `DOCKER-USER` iptables enforcement
needs one-time root access and is deferred to Phase 2 hardening.
