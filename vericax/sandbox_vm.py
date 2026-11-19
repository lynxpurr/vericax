"""Sandbox VM wrapper around the external runtime's DesktopEnv.

The wrapper owns the control plane only: boot, bash, upload, download, close.
It is stack-agnostic and knows nothing about agents, adapters or scoring roles;
both the agent sandbox and the tier-1 scoring instance are booted through it.
"""
from __future__ import annotations

import base64
import shlex
import sys
import time
from pathlib import Path

from . import config


class SandboxBootError(Exception):
    """The VM could not be started or made ready."""


class SandboxCommandTimeout(Exception):
    """A single bash script exceeded its server-side timeout."""


class SandboxUnavailable(Exception):
    """The VM server is unreachable or failed below the HTTP layer."""


class SandboxVM:
    """One VM boot. Create, ``boot()``, operate, ``close()``. Never reuse."""

    def __init__(self, snapshot: str, cache_dir: Path | str):
        self.snapshot = snapshot
        self.image = config.image_path(snapshot)
        self.cache_dir = Path(cache_dir)
        self._env = None

    # ------------------------------------------------------------ lifecycle
    def boot(self, task_config: dict | None = None) -> None:
        """Start the VM and optionally apply a task config (uploads init files).

        The DesktopEnv constructor boots the emulator, so any exception raised
        here means the VM never became ready (spec/09 section 9: prepare).
        """
        runtime = config.runtime_path()
        engine = str(runtime / "engine")
        if engine not in sys.path:
            sys.path.insert(0, engine)
        try:
            import logging
            if not logging.getLogger().handlers:
                logging.basicConfig(level=logging.INFO,
                                    format="%(asctime)s %(name)s %(message)s")
            from desktop_env.desktop_env import DesktopEnv
        except Exception as exc:  # noqa: BLE001 - infra, not capability
            raise SandboxBootError(f"cannot import runtime DesktopEnv: {exc}") from exc
        try:
            self._env = DesktopEnv(
                provider_name="docker", path_to_vm=str(self.image), os_type="Ubuntu",
                action_space="pyautogui", require_a11y_tree=False,
                screen_size=(1920, 1080), headless=True, client_password="",
                cache_dir=str(self.cache_dir),
            )
            self._env.reset(task_config=task_config)
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise SandboxBootError(f"VM boot failed: {exc}") from exc

    def close(self) -> None:
        """Stop the VM. ``env.close()`` is trusted but verified: the docker
        provider's container is removed by force if it survived the shutdown,
        so a failed boot can never leak a VM (spec/09 section 4, E1)."""
        if self._env is not None:
            container = getattr(self._env.provider, "container", None)
            try:
                self._env.close()
            except Exception:  # noqa: BLE001 - close must never raise upward
                pass
            if container is not None:
                try:
                    container.reload()
                    if container.status != "removed":
                        container.remove(force=True)
                except Exception:  # noqa: BLE001 - already gone
                    pass
            self._env = None

    # ------------------------------------------------------------ control plane
    def bash(self, script: str, timeout: int = 120, cwd: str | None = None) -> dict:
        """Run a bash script in the VM; returns {returncode, output}.

        stderr is merged into output by the runtime server. Raises
        SandboxCommandTimeout for a server-side timeout and SandboxUnavailable
        when the control channel itself is broken.
        """
        assert self._env is not None, "VM not booted"
        try:
            result = self._env.controller.run_bash_script(
                script, timeout=timeout, working_dir=cwd)
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if "HardTimeout" in name:
                raise SandboxCommandTimeout(str(exc)) from exc
            raise SandboxUnavailable(f"{name}: {exc}") from exc
        return {
            "returncode": int(result.get("returncode", -1)),
            "output": str(result.get("output", "")),
        }

    def get(self, remote: str) -> bytes | None:
        """Fetch a file from the VM; None when the path does not exist."""
        assert self._env is not None, "VM not booted"
        try:
            return self._env.controller.get_file(remote)
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if "NotFound" in name:
                return None
            raise SandboxUnavailable(f"{name}: {exc}") from exc

    def upload(self, remote: str, data: bytes) -> None:
        """Write bytes to a VM path, chunked through the bash channel.

        The bash channel caps a single argument near 128 KiB (MAX_ARG_STRLEN),
        so payloads travel as base64 slices appended in order.
        """
        self.bash(f"mkdir -p {shlex.quote(str(Path(remote).parent))}", timeout=60)
        encoded = base64.b64encode(data).decode()
        if not encoded:
            self.bash(f": > {shlex.quote(remote)}", timeout=60)
            return
        chunk = 96_000  # base64 chars; decodes to ~72 KiB, well under the cap
        for start in range(0, len(encoded), chunk):
            part = encoded[start:start + chunk]
            op = ">" if start == 0 else ">>"
            self.bash(
                f"echo '{part}' | base64 -d {op} {shlex.quote(remote)}", timeout=60)

    # ------------------------------------------------------------ environment
    def isolate_network(self) -> tuple[bool, str]:
        """Guest-level egress block, best effort: allow only the local NAT subnet.

        The bash channel is a non-root user, so the rules go through sudo with
        the image's default password (the runtime's own client_password
        convention). One SINGLE root invocation applies all four rules:
        separate sudo child processes per rule proved flaky here - the VM
        server dropped the control connection mid-sequence.

        The first rule (conntrack ESTABLISHED,RELATED) is essential: the
        controller's replies belong to inbound-initiated flows, and without it
        the REJECT rule severed the control channel itself. The remaining
        rules keep the local subnet (gateway, DNS) and loopback reachable and
        reject new outbound connections. Verified on the CalculiX-2.21 image:
        the controller stays alive with the rules active, while external ping
        and curl fail.

        A failure is recorded, never fatal; host-level DOCKER-USER enforcement
        stays a Phase 2 item.
        """
        script = r"""
GW=$(ip route show | awk '/^default/ {print $3; exit}')
[ -n "$GW" ] || { echo VCAX_RESULT=no-default-route; exit 0; }
SUB=${GW%.*}.0/24
printf 'password\n' | sudo -S sh -c "iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT; iptables -A OUTPUT -d $SUB -j ACCEPT; iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT; iptables -A OUTPUT ! -d $SUB -j REJECT" >/dev/null 2>&1
if ping -c1 -W2 1.1.1.1 >/dev/null 2>&1; then echo "VCAX_RESULT=reachable subnet=$SUB"; else echo "VCAX_RESULT=blocked subnet=$SUB"; fi
""".strip()
        try:
            result = self.bash(script, timeout=120)
            output = result.get("output", "")
            if "VCAX_RESULT=blocked" in output:
                subnet = output.split("subnet=")[-1].strip()
                return True, f"guest iptables blocks egress (subnet {subnet})"
            if "VCAX_RESULT" in output:
                return False, output.strip().splitlines()[-1][:120]
            return False, f"isolation script produced no verdict (rc={result.get('returncode')})"
        except Exception as exc:  # noqa: BLE001 - hardening only, never fatal
            return False, f"isolation attempt failed: {type(exc).__name__}: {exc}"

    def wait_healthy(self, timeout_s: int = 180) -> bool:
        """Poll a trivial bash call until the control plane answers again.

        Clears the runtime's post-failure fast-fail window before the proxy
        starts serving agent traffic (a stale window would make the agent's
        first vericax-sh call fail without cause).
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                probe = self.bash("echo vericax-ok", timeout=30)
                if probe.get("returncode") == 0 and "vericax-ok" in probe.get("output", ""):
                    return True
            except Exception:  # noqa: BLE001 - retry until the deadline
                pass
            time.sleep(5)
        return False

    def process_snapshot(self) -> str:
        try:
            return self.bash("ps -eo pid,ppid,user,etime,cmd --sort=pid", timeout=60)["output"]
        except Exception:  # noqa: BLE001 - forensics only, never fatal
            return "<snapshot unavailable>"
