"""Artifact freeze (spec/08 section 6): pull declared artifacts out of the
sandbox into a read-only store and describe them in ``artifacts.json``.

- basename flattening: task packages must declare basename-unique artifact
  paths (enforced here and in ``lifecycle.check_task``);
- a missing or empty artifact is a capability failure (L1), not an infra
  error: it is recorded ``present=false`` with a reason and scoring proceeds;
- symlinks are resolved and rejected when their target escapes the allowed
  roots, so the frozen store can never become a path out of the sandbox.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import posixpath
from pathlib import Path

ALLOWED_ROOTS = ("/home/user", "/tmp")


def check_basename_uniqueness(artifact_paths: list[str]) -> None:
    names = [posixpath.basename(p) for p in artifact_paths]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise SystemExit(f"artifact_paths basenames must be unique; duplicates: {duplicates}")


def _probe_script(artifact_paths: list[str]) -> str:
    lines = []
    for path in artifact_paths:
        q = shlex.quote(path)
        lines.append(
            f'if [ -L "{q}" ]; then t=$(readlink -f "{q}" 2>/dev/null || true); '
            f'case "$t" in /home/user/*|/tmp/*) echo "{path}|LINK_OK|$t";; '
            f'*) echo "{path}|LINK_ESCAPE|${{t:-<unresolved>}}";; esac; '
            f'elif [ -e "{q}" ]; then echo "{path}|OK|-"; '
            f'else echo "{path}|ABSENT|-"; fi'
        )
    return "\n".join(lines)


def freeze(
    vm,
    artifact_paths: list[str],
    episode_dir: Path,
    image_sha256: str,
    task_id: str,
    episode_id: str,
) -> dict:
    """Copy artifacts into ``<episode_dir>/artifacts/`` and write artifacts.json."""
    check_basename_uniqueness(artifact_paths)
    artifacts_dir = episode_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    probe = vm.bash(_probe_script(artifact_paths), timeout=120)
    statuses: dict[str, tuple[str, str]] = {}
    for line in probe["output"].splitlines():
        parts = line.strip().split("|")
        if len(parts) == 3 and parts[0] in artifact_paths:
            statuses[parts[0]] = (parts[1], parts[2])

    entries = []
    for path in artifact_paths:
        name = posixpath.basename(path)
        status, resolved = statuses.get(path, ("ABSENT", "-"))
        entry: dict = {"path": path, "name": name}
        if status == "LINK_ESCAPE":
            entry.update(present=False, reason="symlink_escape", target=resolved)
        elif status == "ABSENT":
            entry.update(present=False, reason="absent")
        else:
            fetch_path = resolved if status == "LINK_OK" else path
            data = vm.get(fetch_path)
            if data is None:
                entry.update(present=False, reason="fetch_failed")
            elif len(data) == 0:
                entry.update(present=False, reason="empty")
            else:
                target = artifacts_dir / name
                target.write_bytes(data)
                entry.update(present=True, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        entries.append(entry)

    manifest = {
        "task_id": task_id,
        "episode_id": episode_id,
        "image_sha256": image_sha256,
        "artifacts": entries,
    }
    (artifacts_dir / "artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def all_present(manifest: dict) -> bool:
    return all(entry.get("present") for entry in manifest.get("artifacts", []))
