"""Resolve VeriCAx's external dependencies (runtime checkout, VM images).

Same contract as ``scripts/_config.py``: environment variables win over the
machine-local ``vericax.toml``. There is deliberately no fallback path.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO / "vericax.toml"
CACHE_DIR = REPO / "cache" / "harness"

# Parallel episodes may hash the same multi-GB image at the same time. One
# process-wide lock keeps the cache check and the write atomic; separate
# processes still race benignly because the cache key is content-addressed by
# (size, mtime_ns) and the write goes through os.replace.
_SHA_LOCK = threading.Lock()


def _from_config(section: str, key: str) -> str | None:
    if not CONFIG_FILE.is_file():
        return None
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        return None
    with CONFIG_FILE.open("rb") as fh:
        data = tomllib.load(fh)
    value = data.get(section, {}).get(key)
    return str(value) if value else None


def runtime_path() -> Path:
    """EngiWorld-compatible runtime checkout providing ``desktop_env``."""
    raw = os.environ.get("VERICAX_RUNTIME") or _from_config("runtime", "path")
    if not raw:
        raise SystemExit(
            "VeriCAx cannot locate the evaluation runtime.\n"
            "  set VERICAX_RUNTIME, or fill [runtime] path in vericax.toml."
        )
    path = Path(raw).expanduser().resolve()
    if not (path / "engine" / "desktop_env").is_dir():
        raise SystemExit(f"VERICAX_RUNTIME={path} does not look like a runtime checkout.")
    return path


def image_path(snapshot: str, override: str | Path | None = None) -> Path:
    """Decompressed qcow2 for a snapshot, e.g. CalculiX-2.21 -> <dir>/CalculiX-2.21.qcow2.

    ``override`` is the per-episode/batch form: a batch spanning several
    snapshots cannot use the single ``VERICAX_IMAGE`` environment variable, so
    the scheduler passes the resolved path explicitly.
    """
    if override is not None:
        path = Path(override).expanduser().resolve()
    else:
        explicit = os.environ.get("VERICAX_IMAGE")
        if explicit:
            path = Path(explicit).expanduser().resolve()
        else:
            raw_dir = os.environ.get("VERICAX_IMAGE_DIR") or _from_config("images", "dir")
            if not raw_dir:
                raise SystemExit(
                    "VeriCAx cannot locate VM images.\n"
                    "  set VERICAX_IMAGE_DIR, or fill [images] dir in vericax.toml."
                )
            path = Path(raw_dir).expanduser().resolve() / f"{snapshot}.qcow2"
    if not path.is_file():
        raise SystemExit(f"VM image not found: {path}")
    return path


def image_sha256(path: Path) -> str:
    """SHA-256 of the base image, cached by (size, mtime_ns) in the harness cache.

    The qcow2 is several GB; hashing it per episode would dominate the runtime,
    so the digest is cached on disk and invalidated when the file changes.
    """
    stat = path.stat()
    cache_dir = CACHE_DIR / "image-sha256"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{path.name}.{stat.st_size}.{stat.st_mtime_ns}.sha256"
    with _SHA_LOCK:
        if cache_file.is_file():
            return cache_file.read_text().strip()
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 22), b""):
                digest.update(block)
        value = digest.hexdigest()
        # Atomic replace: a concurrent reader must never observe a partial file.
        tmp = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.tmp")
        tmp.write_text(value + "\n")
        os.replace(tmp, cache_file)
        return value
