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
import os
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


def _variants(path: Path) -> set[Path]:
    """A path as given, plus the same path with its symlinks resolved."""
    variants = {path}
    try:
        variants.add(path.resolve())
    except OSError:
        pass
    return variants


def is_vericax_vm(attrs: dict, images_dir: Path | None, extra_images: set[str] | None = None) -> bool:
    """True for a VM container that boots one of VeriCAx's images.

    The runtime's docker provider binds the qcow2 as ``/System.qcow2``. An image
    under the configured ``[images] dir`` counts, and so does one this batch
    passes through ``--image SNAPSHOT=PATH``. Other projects' VM containers are
    never claimed, whatever image they run.

    Paths are compared as given and with symlinks resolved. A suite directory
    usually links to images stored elsewhere (``suite/FEniCS.qcow2 ->
    ../fenics/out/FEniCS.qcow2``); resolving first made every image but the
    batch's own look foreign, which hid exactly the leftovers the inventory is
    for.
    """
    bases: set[Path] = set()
    if images_dir is not None:
        bases |= _variants(Path(images_dir))
    explicit: set[Path] = set()
    for source in extra_images or ():
        explicit |= _variants(Path(source))
    for mount in attrs.get("Mounts") or []:
        if mount.get("Destination") != SYSTEM_IMAGE_MOUNT or not mount.get("Source"):
            continue
        variants = _variants(Path(mount["Source"]))
        if variants & explicit:
            return True
        if any(path.is_relative_to(base) for path in variants for base in bases):
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


def pressure() -> dict | None:
    """/proc/pressure/{cpu,memory,io} as written by the kernel, when PSI is on.

    A guest that stalls long enough sees its clock jump and its timers elapse
    at once; host memory pressure is the usual reason, so it belongs next to
    the load average in a loss record.
    """
    result: dict[str, str] = {}
    try:
        for name in ("cpu", "memory", "io"):
            lines = Path(f"/proc/pressure/{name}").read_text().strip().splitlines()
            result[name] = " ".join(lines)
    except OSError:
        return None
    return result or None


def _children(pid: int) -> list[int]:
    try:
        kids: list[int] = []
        for task in Path(f"/proc/{pid}/task").iterdir():
            kids.extend(int(value) for value in (task / "children").read_text().split())
        return kids
    except (OSError, ValueError):
        return []


def _process_stats(pid: int) -> dict | None:
    try:
        name = state = rss = peak = threads = None
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key == "Name":
                name = rest.strip()
            elif key == "State":
                state = rest.strip().split("(")[-1].rstrip(")") if rest.strip() else None
            elif key in ("VmRSS", "VmHWM"):
                megabytes = int(rest.split()[0]) // 1024
                if key == "VmRSS":
                    rss = megabytes
                else:
                    peak = megabytes
            elif key == "Threads":
                threads = int(rest.split()[0])
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        ticks = os.sysconf("SC_CLK_TCK") or 100
        cpu_seconds = (int(fields[11]) + int(fields[12])) / ticks
    except (OSError, ValueError, IndexError):
        return None
    return {"pid": pid, "name": name, "state": state, "rss_mb": rss,
            "peak_mb": peak, "threads": threads, "cpu_seconds": round(cpu_seconds, 1)}


def process_tree(pid: int, limit: int = 64) -> list[dict]:
    """A process and everything below it: name, state, resident and peak memory.

    The peak matters most: with ``-m 4G`` a qemu process that never grew past
    about 2 GB was not under guest memory pressure when its sandbox was lost.
    """
    rows: list[dict] = []
    queue = [pid]
    seen: set[int] = set()
    while queue and len(rows) < limit:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        stats = _process_stats(current)
        if stats:
            rows.append(stats)
            queue.extend(_children(current))
    return rows


def cgroup_memory(pid: int) -> dict | None:
    """memory.current / max / peak / events of a process's cgroup (cgroup v2)."""
    try:
        line = next(item for item in Path(f"/proc/{pid}/cgroup").read_text().splitlines()
                    if item.startswith("0::"))
        base = Path("/sys/fs/cgroup") / line.split("::", 1)[1].strip().lstrip("/")
    except (OSError, StopIteration, IndexError):
        return None
    result: dict = {}
    for key in ("memory.current", "memory.max", "memory.peak"):
        try:
            result[key] = int((base / key).read_text().strip())
        except (OSError, ValueError):
            continue
    try:
        result["memory.events"] = dict(
            item.split() for item in (base / "memory.events").read_text().splitlines())
    except (OSError, ValueError):
        pass
    return result or None


def sandbox_loss_record(*, episode_id: str, task_id: str, adapter: str, stage: str,
                        detail: str, proxy: dict | None, agent: dict | None,
                        vm_state: dict | None) -> dict:
    """Everything known about a lost sandbox, at the moment it is declared lost."""
    processes = process_tree(vm_state["pid"]) if vm_state and vm_state.get("pid") else []
    cgroup = next((found for found in (cgroup_memory(row["pid"]) for row in processes)
                   if found), None)
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
        "vm_processes": processes,
        "vm_cgroup_memory": cgroup,
        "host": {
            "memory_mb": meminfo_mb(),
            "loadavg": loadavg(),
            "pressure": pressure(),
            "top_processes": top_processes(),
        },
    }


def write_loss_record(logs_dir: Path, record: dict) -> Path:
    path = Path(logs_dir) / "sandbox-loss.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path
