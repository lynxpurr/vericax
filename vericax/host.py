"""Host-side state for batch safety and sandbox-loss forensics (spec/09 section 9).

Two consumers:

- ``vericax batch`` reads the available memory before it launches an episode and
  lists the VeriCAx VM containers that are already running. A VM left behind by
  an earlier episode keeps its RAM and cores busy and makes every later episode
  more likely to lose its control channel.
- the episode lifecycle writes ``logs/sandbox-loss.json`` when the sandbox
  control channel is lost: the host and the VM container as they were at that
  moment. The container is removed when the episode ends, so the cause cannot
  be reconstructed afterwards.

Process records carry a name and a size only, never argv: an agent's argv holds
its instruction, and a launch line can hold credentials.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

SYSTEM_IMAGE_MOUNT = "/System.qcow2"


def meminfo_mb() -> dict:
    """MemTotal / MemAvailable / SwapTotal / SwapFree from ``/proc/meminfo``, in MB."""
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                values[key] = int(rest.split()[0]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return values


def mem_available_mb() -> int | None:
    return meminfo_mb().get("MemAvailable")


def loadavg() -> list[float] | None:
    try:
        return [float(value) for value in Path("/proc/loadavg").read_text().split()[:3]]
    except (OSError, ValueError):
        return None


def top_processes(limit: int = 12) -> list[dict]:
    """The heaviest processes by resident size: ``pid``, ``name``, ``rss_mb``."""
    rows: list[dict] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return rows
    for entry in entries:
        if not entry.name.isdigit():
            continue
        name = rss = None
        try:
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) // 1024
        except (OSError, ValueError, IndexError):
            continue
        if name is not None and rss is not None:
            rows.append({"pid": int(entry.name), "name": name, "rss_mb": rss})
    rows.sort(key=lambda row: row["rss_mb"], reverse=True)
    return rows[:limit]


def is_vericax_vm(attrs: dict, images_dir: Path | None, extra_images: set[str] | None = None) -> bool:
    """True for a VM container that boots one of VeriCAx's images.

    The runtime's docker provider binds the qcow2 as ``/System.qcow2``. An image
    under the configured ``[images] dir`` counts, and so does one this batch
    passes through ``--image SNAPSHOT=PATH``. Other projects' VM containers are
    never claimed, whatever image they run.
    """
    base = Path(images_dir).resolve() if images_dir is not None else None
    explicit = set()
    for source in extra_images or ():
        try:
            explicit.add(Path(source).resolve())
        except OSError:
            continue
    for mount in attrs.get("Mounts") or []:
        if mount.get("Destination") != SYSTEM_IMAGE_MOUNT:
            continue
        try:
            path = Path(mount.get("Source") or "").resolve()
        except OSError:
            continue
        if path in explicit or (base is not None and path.is_relative_to(base)):
            return True
    return False


def vericax_vm_containers(images_dir: Path | None, extra_images: set[str] | None = None,
                          client=None) -> dict:
    """Running VeriCAx VM containers: ``{"ok", "containers", "error"}``.

    An unreachable docker daemon is reported, not raised: the caller decides
    whether a missing inventory is acceptable.
    """
    if client is None:
        try:
            import docker  # provided by the runtime venv

            client = docker.from_env()
        except Exception as exc:  # noqa: BLE001 - reported, the caller decides
            return {"ok": False, "containers": [], "error": f"{type(exc).__name__}: {exc}"}
    try:
        containers = client.containers.list()
    except Exception as exc:  # noqa: BLE001 - reported, the caller decides
        return {"ok": False, "containers": [], "error": f"{type(exc).__name__}: {exc}"}
    found = []
    for container in containers:
        try:
            attrs = container.attrs
        except Exception:  # noqa: BLE001 - a container that vanished mid-list is not ours
            continue
        if is_vericax_vm(attrs, images_dir, extra_images):
            found.append({
                "name": str(attrs.get("Name", "")).lstrip("/"),
                "image": (attrs.get("Config") or {}).get("Image"),
                "created": attrs.get("Created"),
            })
    return {"ok": True, "containers": found, "error": None}


def sandbox_loss_record(*, episode_id: str, task_id: str, adapter: str, stage: str,
                        detail: str, proxy: dict | None, agent: dict | None,
                        vm_state: dict | None) -> dict:
    """Everything known about a lost sandbox, at the moment it is declared lost."""
    return {
        "episode_id": episode_id,
        "task_id": task_id,
        "adapter": adapter,
        "stage": stage,
        "detail": detail[:400],
        "captured_at": time.time(),
        "proxy": proxy,
        "agent": agent,
        "vm_container": vm_state,
        "host": {
            "memory_mb": meminfo_mb(),
            "loadavg": loadavg(),
            "top_processes": top_processes(),
        },
    }


def write_loss_record(logs_dir: Path, record: dict) -> Path:
    path = Path(logs_dir) / "sandbox-loss.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path
