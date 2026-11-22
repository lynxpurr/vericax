#!/usr/bin/env python3
"""Check that VeriCAx can see its two external assets.

Prints the resolved paths and validates them, so setup problems surface before a
VM boot. Exit code 0 when everything is in place.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _config  # noqa: E402


def main() -> int:
    ok = True
    try:
        runtime = _config.runtime_path()
        engine = runtime / "engine" / "desktop_env"
        print(f"runtime : {runtime}")
        print(f"  engine: {engine}  ({'ok' if engine.is_dir() else 'MISSING'})")
        venv = runtime / ".venv" / "bin" / "python"
        print(f"  venv  : {venv}  ({'ok' if venv.is_file() else 'not found (optional here)'})")
    except SystemExit as exc:
        print(f"runtime : ERROR\n{exc}")
        ok = False

    for snapshot in ("CalculiX-2.21", "FEniCS", "VeriCAx-merged"):
        try:
            image = _config.image_path(snapshot)
            size = image.stat().st_size / 1e9
            print(f"image   : {image}  ({size:.1f} GB)")
        except SystemExit as exc:
            print(f"image   : ERROR\n{exc}")
            ok = False

    print("\n" + ("setup looks complete" if ok else "setup incomplete — see docs/setup.md"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
