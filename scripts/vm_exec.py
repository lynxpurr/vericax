#!/usr/bin/env python3
"""Run a shell script inside the evaluation VM and fetch files back.

Reusable probe for VeriCAx task authoring and debugging.

    python scripts/vm_exec.py --script-file /tmp/probe.sh \
        --fetch /home/user/Desktop/solution.dat --fetch /tmp/probe.out

Fetched text files are printed with a header; binary ones just report size.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import _config  # noqa: E402  (external dependency resolution)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--script", default=None, help="inline bash script")
    ap.add_argument("--script-file", default=None)
    ap.add_argument("--fetch", action="append", default=[], help="remote path to fetch")
    ap.add_argument("--upload", action="append", default=[],
                    help="LOCAL:REMOTE pair, uploaded before the script runs")
    ap.add_argument("--snapshot", default="CalculiX-2.21")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    script = Path(args.script_file).read_text() if args.script_file else args.script
    if not script:
        ap.error("need --script or --script-file")

    runtime = _config.runtime_path()
    image = _config.image_path(args.snapshot)
    sys.path.insert(0, str(runtime / "engine"))
    from desktop_env.desktop_env import DesktopEnv  # noqa: E402

    env = DesktopEnv(
        provider_name="docker", path_to_vm=str(image), os_type="Ubuntu",
        action_space="pyautogui", require_a11y_tree=False,
        screen_size=(1920, 1080), headless=True, client_password="",
        cache_dir=str(REPO / "cache" / "probe"),
    )
    try:
        env.reset()
        import base64
        for pair in args.upload:
            local, remote = pair.split(":", 1)
            b64 = base64.b64encode(Path(local).read_bytes()).decode()
            env.step(("bash", f"mkdir -p $(dirname {remote}) && echo '{b64}' | base64 -d > {remote}"),
                     bash_timeout=120)
        env.step(("bash", script), bash_timeout=args.timeout)
        for remote in args.fetch:
            try:
                data = env.controller.get_file(remote)
            except Exception as exc:  # noqa: BLE001
                print(f"\n===== {remote}: FETCH FAILED ({exc}) =====")
                continue
            if data is None:
                print(f"\n===== {remote}: MISSING =====")
                continue
            head = data[:4000]
            try:
                text = head.decode()
                print(f"\n===== {remote} ({len(data)} bytes) =====")
                print(text)
            except UnicodeDecodeError:
                print(f"\n===== {remote}: {len(data)} bytes (binary) =====")
    finally:
        env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
