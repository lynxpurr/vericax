#!/usr/bin/env python3
"""Pack a VeriCAx task package: write resources.sha256 and validate structure.

    python scripts/pack_task.py --task cae--cli--calculix--task-0001 [--check]

The manifest covers every file that makes up the task package *except* the
manifest itself: task JSON, verifier, init resources and ground truth. The
verifier's own hash is included, so silently editing the scoring logic
invalidates the package — same discipline as pinning inputs for anti-tamper.

--check verifies an existing manifest without rewriting it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = "resources.sha256"
L0_RECORD = "reference_selfcheck.json"   # derived audit output, not a resource
REQUIRED_FILES = ("eval.py",)


def task_dir_for(task_id: str) -> Path:
    domain, iface, software, task = task_id.split("--")
    return REPO / "tasks" / domain / iface / software / task


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def package_files(task_dir: Path) -> list[Path]:
    files = []
    for path in sorted(task_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in (MANIFEST, L0_RECORD):
            continue
        if "__pycache__" in path.parts:
            continue
        files.append(path)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    task_dir = task_dir_for(args.task)
    if not task_dir.is_dir():
        print(f"no such task: {task_dir}", file=sys.stderr)
        return 2

    errors = []
    task_json = task_dir / f"{task_dir.name}.json"
    if not task_json.is_file():
        errors.append(f"missing task definition {task_json.name}")
    else:
        definition = json.loads(task_json.read_text())
        if definition.get("id") != args.task:
            errors.append(f"task id mismatch: {definition.get('id')} != {args.task}")
        if definition.get("interface") not in ("cli", "gui"):
            errors.append("interface must be cli or gui")
        if definition.get("interface") == "cli" and definition.get("limits", {}).get("cli_max_steps") is None:
            errors.append("cli tasks need limits.cli_max_steps")
    for name in REQUIRED_FILES:
        if not (task_dir / name).is_file():
            errors.append(f"missing {name}")
    for sub in ("init_file", "ground_truth"):
        if not (task_dir / sub).is_dir():
            errors.append(f"missing {sub}/")
    # verifier must not be reachable from the agent's init payload
    for path in (task_dir / "init_file").rglob("*"):
        if path.is_file() and path.name in ("eval.py", "audit.md", MANIFEST):
            errors.append(f"scoring artifact leaked into init_file/: {path.name}")
    audit = task_dir / "ground_truth" / "audit.md"
    if not audit.is_file():
        errors.append("ground_truth/audit.md missing (run scripts/audit_task.py)")
    elif "MISS" in audit.read_text():
        errors.append("audit record contains MISS entries")
    l0_path = task_dir / "ground_truth" / L0_RECORD
    if l0_path.is_file():
        try:
            l0 = json.loads(l0_path.read_text())
        except ValueError:
            errors.append(f"{L0_RECORD} is not valid JSON")
        else:
            if not l0.get("passed"):
                errors.append("L0 reference self-check did not pass")
    else:
        print(f"note: no {L0_RECORD}; run `vericax audit --task {args.task}` before publishing")

    if errors:
        print("PACKAGE INVALID:")
        for e in errors:
            print(" -", e)
        return 1

    files = package_files(task_dir)
    lines = [f"{sha256(p)}  {p.relative_to(task_dir).as_posix()}" for p in files]
    content = "\n".join(lines) + "\n"
    manifest = task_dir / MANIFEST

    if args.check:
        if not manifest.is_file():
            print("no manifest to check", file=sys.stderr)
            return 1
        ok = manifest.read_text() == content
        print("manifest matches" if ok else "manifest STALE (rerun without --check)")
        return 0 if ok else 1

    manifest.write_text(content)
    print(f"wrote {manifest.relative_to(REPO)} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
