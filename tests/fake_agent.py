#!/usr/bin/env python3
"""Scripted fake agent (runs INSIDE the agent container; spec/08 section 10.1).

It exercises the contract surface exactly like a real agent would - the only
tools it uses are `vericax-sh` and its own payload dir:

    /vericax/payload/config.json   {"mode": solve|empty|summary_only|tamper|background, ...}
    /vericax/payload/recipe.sh     the task's reference submission script (solve)

Modes map 1:1 to the acceptance matrix:
    solve         reference submission -> verifier must accept
    empty         deliver empty artifact files        -> L1 reject
    summary_only  fabricate a plausible summary only  -> L1 reject
    tamper        solve, then rewrite the summary     -> L3 A-vs-B reject
    background    solve, then leave a VM-side writer  -> tier-1 must not care
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

CONFIG_PATH = "/vericax/payload/config.json"
RECIPE_PATH = "/vericax/payload/recipe.sh"


def sh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, text=True, capture_output=True)
    if check and result.returncode != 0:
        print(f"[fake-agent] command failed: {' '.join(args)}\n{result.stdout}\n{result.stderr}",
              file=sys.stderr)
        sys.exit(result.returncode or 1)
    return result


def sh_run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    return sh("vericax-sh", "run", "--timeout", "600", "--", cmd, check=check)


def main() -> int:
    config = json.loads(open(CONFIG_PATH).read())
    mode = config.get("mode", "solve")
    artifacts = json.loads(os.environ.get("VERICAX_ARTIFACTS", "[]"))
    print(f"[fake-agent] mode={mode} artifacts={artifacts}", flush=True)

    if mode == "solve" or mode in ("tamper", "background"):
        sh("vericax-sh", "put", RECIPE_PATH, "/tmp/recipe.sh")
        result = sh_run("bash /tmp/recipe.sh", check=False)
        if result.returncode != 0:
            print(f"[fake-agent] recipe failed rc={result.returncode}: "
                  f"{result.stdout[-400:]}", file=sys.stderr)
            return result.returncode or 1

    if mode == "empty":
        paths = " ".join(artifacts)
        sh_run(f"rm -f {paths} ; touch {paths}")

    if mode == "summary_only":
        fab = config["fabricate"]
        sh_run(f"mkdir -p \"$(dirname '{fab['path']}')\" ; "
               f"printf '%s\\n' '{fab['line']}' > '{fab['path']}'")

    if mode == "tamper":
        tamp = config["tamper"]
        sh_run(f"printf '%s\\n' '{tamp['line']}' > '{tamp['path']}'")

    if mode == "background":
        noise = config.get("noise_file", "/home/user/Desktop/_noise.txt")
        sh_run(f"nohup sh -c \"while true; do echo noise >> '{noise}'; sleep 1; done\" "
               f">/dev/null 2>&1 & echo writer-started")

    print("[fake-agent] done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
