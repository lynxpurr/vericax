"""Resolve VeriCAx's external dependencies.

VeriCAx does not vendor the evaluation runtime or any VM image: both are large
external assets with their own provenance. Point at them explicitly, either with
environment variables or with a machine-local `vericax.toml` (copy
`vericax.toml.example`). Environment variables win.

There is deliberately NO fallback to a sibling checkout: this project must not
assume that any research workspace happens to sit next to it.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO / "vericax.toml"
PACKAGED_ENGINE_HINT = "vericax.toml.example"


def _config() -> dict:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        import tomllib  # Python >= 3.11
    except ModuleNotFoundError:  # pragma: no cover
        return {}
    with CONFIG_FILE.open("rb") as fh:
        return tomllib.load(fh)


def _from_config(section: str, key: str) -> str | None:
    value = _config().get(section, {}).get(key)
    return str(value) if value else None


def _missing(what: str, env: str, section: str, key: str) -> SystemExit:
    return SystemExit(
        f"VeriCAx cannot locate {what}.\n"
        f"  set the {env} environment variable, or\n"
        f"  copy {PACKAGED_ENGINE_HINT} to vericax.toml and fill [{section}] {key}.\n"
        "Both are external dependencies; they are not part of this repository."
    )


def runtime_path() -> Path:
    """EngiWorld-compatible runtime checkout that provides `desktop_env`."""
    raw = os.environ.get("VERICAX_RUNTIME") or _from_config("runtime", "path")
    if not raw:
        raise _missing("the evaluation runtime", "VERICAX_RUNTIME", "runtime", "path")
    path = Path(raw).expanduser().resolve()
    if not (path / "engine" / "desktop_env").is_dir():
        raise SystemExit(
            f"VERICAX_RUNTIME={path} does not look like a runtime checkout "
            "(expected engine/desktop_env)."
        )
    return path


def image_path(snapshot: str) -> Path:
    """Decompressed qcow2 for a snapshot, e.g. CalculiX-2.21 -> <dir>/CalculiX-2.21.qcow2."""
    explicit = os.environ.get("VERICAX_IMAGE")
    if explicit:
        path = Path(explicit).expanduser().resolve()
    else:
        raw_dir = os.environ.get("VERICAX_IMAGE_DIR") or _from_config("images", "dir")
        if not raw_dir:
            raise _missing("VM images", "VERICAX_IMAGE_DIR", "images", "dir")
        path = (Path(raw_dir).expanduser().resolve() / f"{snapshot}.qcow2")
    if not path.is_file():
        raise SystemExit(
            f"VM image not found: {path}\n"
            "Decompress the published archive for this snapshot "
            "(docs/spec/04-environment-spec.md section 1)."
        )
    return path
