"""Run the agent process as a per-episode container (D2b, spec/09 section 4).

The agent's launch argv is the container's main process, so:
  - its exit code is the container's exit code,
  - the hard deadline maps to ``docker stop`` (SIGTERM, grace, SIGKILL),
  - killing the container kills the whole cgroup (spec/08 section 7).

The container never mounts the repository: only harness-owned episode files
(instruction, state seed, optional payload) and the proxy socket.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentResult:
    exit_code: int | None = None
    killed_by_deadline: bool = False
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    container: str = ""
    logs_tail: list[str] = field(default_factory=list)


def _demux(logs: bytes) -> tuple[bytes, bytes]:
    """Split docker's multiplexed stream (8-byte frames) into (stdout, stderr)."""
    out, err, offset = [], [], 0
    while offset + 8 <= len(logs):
        header = logs[offset:offset + 8]
        length = int.from_bytes(header[4:8], "big")
        payload = logs[offset + 8:offset + 8 + length]
        (out if header[0] == 1 else err).append(payload)
        offset += 8 + length
    if offset < len(logs):  # trailing bytes without a full frame: non-multiplexed
        out.append(logs[offset:])
    return b"".join(out), b"".join(err)


def run_agent(
    image: str,
    command: list[str],
    env: dict[str, str],
    mounts: dict[str, dict[str, str]],
    container_name: str,
    deadline_epoch: float,
    grace_seconds: int,
    stdin_bytes: bytes | None = None,
) -> AgentResult:
    import docker  # provided by the runtime venv

    client = docker.from_env()
    started = time.monotonic()
    container = client.containers.run(
        image,
        command=command,
        name=container_name,
        environment=env,
        volumes=mounts,
        network="bridge",          # never host (spec/09 section 5)
        working_dir="/vericax",
        detach=True,
        stdin_open=bool(stdin_bytes),
        auto_remove=False,
    )
    result = AgentResult(container=container.name)

    if stdin_bytes:
        _feed_stdin(container, stdin_bytes)

    # ---- deadline enforcement (I6): harness polls; agent self-exit wins.
    while True:
        container.reload()
        if container.status not in ("running", "created"):
            break
        remaining = deadline_epoch - time.time()
        if remaining <= 0:
            result.killed_by_deadline = True
            try:
                container.stop(timeout=grace_seconds)
            except Exception:  # noqa: BLE001
                container.kill()
            container.reload()
            break
        container.wait(timeout=min(remaining, 5.0))
        container.reload()

    result.duration_seconds = time.monotonic() - started
    exit_state = container.wait(timeout=30) or {}
    code = exit_state.get("StatusCode")
    result.exit_code = int(code) if code is not None else None
    if result.killed_by_deadline:
        # docker stop reports 137/143 for killed processes; keep the signal
        result.exit_code = result.exit_code or None

    stdout, stderr = _demux(container.logs(stdout=True, stderr=True, tail="all"))
    result.stdout = stdout.decode(errors="ignore")
    result.stderr = stderr.decode(errors="ignore")
    try:
        container.remove(force=True)
    except Exception:  # noqa: BLE001 - cleanup is best effort; name stays in logs
        pass
    return result


def _feed_stdin(container, payload: bytes) -> None:
    """Write the instruction to the container's stdin, then signal EOF."""
    sock = container.attach_socket(params={"stdin": 1, "stream": 1, "logs": 0})
    raw = getattr(sock, "_sock", None) or sock
    try:
        raw.sendall(payload)
        try:
            raw.shutdown(2)  # SHUT_WR -> EOF for the reader inside
        except (AttributeError, OSError):
            sock.close()
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass


def cleanup_container(container_name: str) -> None:
    import docker

    try:
        client = docker.from_env()
        client.containers.get(container_name).remove(force=True)
    except Exception:  # noqa: BLE001
        pass
