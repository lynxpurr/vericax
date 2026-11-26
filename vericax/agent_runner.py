"""Run the agent process as a per-episode container (D2b, spec/09 section 4).

The agent's launch argv is the container's main process, so:
  - its exit code is the container's exit code,
  - the hard deadline maps to ``docker stop`` (SIGTERM, grace, SIGKILL),
  - killing the container kills the whole cgroup (spec/08 section 7),
  - a lost sandbox maps to the same stop, long before the deadline.

The container never mounts the repository: only harness-owned episode files
(instruction, state seed, optional payload) and the proxy socket.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentResult:
    exit_code: int | None = None
    killed_by_deadline: bool = False
    aborted: bool = False
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
    abort_event: threading.Event | None = None,
) -> AgentResult:
    import docker  # provided by the runtime venv

    client = docker.from_env(timeout=600)
    started = time.monotonic()
    container = None
    # The host may run unrelated workloads against the same daemon; a
    # transient API timeout is infra, retried once with a name cleanup.
    for attempt in (1, 2):
        try:
            container = client.containers.run(
                image,
                command=command,
                name=container_name,
                environment=env,
                volumes=mounts,
                network="bridge",      # never host (spec/09 section 5)
                working_dir="/vericax",
                detach=True,
                stdin_open=bool(stdin_bytes),
                auto_remove=False,
            )
            break
        except Exception:  # noqa: BLE001 - retried once below
            cleanup_container(container_name)
            if attempt == 2:
                raise
    result = AgentResult(container=container.name)

    if stdin_bytes:
        _feed_stdin(container, stdin_bytes)

    # ---- deadline enforcement (I6): harness polls; agent self-exit wins.
    # docker-py's wait(timeout=N) is an HTTP read timeout, NOT a poll window:
    # a healthy long-running agent would raise ReadTimeout after N seconds.
    # Poll the container status instead and only wait once, at the end.
    while True:
        container.reload()
        if container.status not in ("running", "created"):
            break
        if abort_event is not None and abort_event.is_set():
            # The sandbox is gone: every remaining call would fail, so stop the
            # agent now. The lifecycle records the episode; nothing is scored.
            result.aborted = True
            _stop(container, grace_seconds)
            container.reload()
            break
        if time.time() >= deadline_epoch:
            result.killed_by_deadline = True
            _stop(container, grace_seconds)
            container.reload()
            break
        time.sleep(2.0)
    try:
        container.wait(timeout=60)
    except Exception:  # noqa: BLE001 - the exit code below still applies
        pass

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


def _stop(container, grace_seconds: int) -> None:
    """SIGTERM, grace, SIGKILL: the same path for the deadline and an abort."""
    try:
        container.stop(timeout=grace_seconds)
    except Exception:  # noqa: BLE001
        container.kill()


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
