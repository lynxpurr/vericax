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
containers/agent/build.sh                # -> vericax-agent:phase1 (dsh, pi)
containers/agent/build-phase2.sh         # -> vericax-agent:phase2 (all five stacks)
```

The build context is assembled from the Dockerfile plus `vericax/sh_client.py`
(the `vericax-sh` the agent calls). Pinned versions live in the Dockerfile and
must match `adapters/*.toml`.

### Phase 2 image (P5)

`Dockerfile.phase2` starts from `nousresearch/hermes-agent:v0.21.6` (Python,
Node 26, Hermes under `/opt/hermes`, `HERMES_HOME=/opt/data`), then installs
dsh, pi, opencode and openclaw from npm at the adapter-pinned versions.
npm 12 ignores lifecycle scripts unless allow-listed, so the install passes
`--allow-scripts` for opencode (native binary download) and the native module
builders. The base image's `ENTRYPOINT` is cleared so the adapter launch argv
is the container's main process.

Credentials are never baked in: the new adapters forward
`DEEPSEEK_API_KEY` via `[container] env_from`. The opencode profile uses
`{env:DEEPSEEK_API_KEY}`; the openclaw profile uses a `source: "env"`
SecretRef; Hermes reads the same variable for its `deepseek` provider.

## Residual risk (Phase 1, documented)

The runtime's docker provider publishes the VM's server ports on all host
interfaces, so a container could reach the VM control server via the host
gateway, bypassing proxy logging. Scoring integrity is unaffected (tier-1
scores in a separate VM from frozen copies), but the proxy audit log could be
bypassed by a misbehaving agent. Host-level `DOCKER-USER` iptables enforcement
needs one-time root access and is deferred to Phase 2 hardening.
