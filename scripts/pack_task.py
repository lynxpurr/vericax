#!/usr/bin/env python3
"""Pack a VeriCAx task package: write resources.sha256 and validate structure.

    python scripts/pack_task.py --task cae--cli--calculix--task-0001 [--check]

The manifest covers every file that makes up the task package *except* the
manifest itself: task JSON, verifier, init resources and ground truth. The
verifier's own hash is included, so silently editing the scoring logic
invalidates the package — same discipline as pinning inputs for anti-tamper.

Gate policy:

* The audit matrix is checked structurally (groups, six negative kinds,
  robustness record) **and row by row**: the case table in
  ``ground_truth/audit.md`` must contain exactly the cases declared in
  ``audit_cases.py`` and every row must be ``PASS``. A hand-written or stale
  record therefore cannot pass the gate.
* The L0 reference record (``ground_truth/reference_selfcheck.json``) is a
  **hard gate when the manifest is written** — no L0, no publish. It is
  gitignored (a derived artifact), so ``--check`` only warns when it is
  absent: a fresh checkout cannot verify L0 offline, and the manifest was
  gated when it was written.

--check verifies an existing manifest without rewriting it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = "resources.sha256"
L0_RECORD = "reference_selfcheck.json"   # derived audit output, not a resource
REQUIRED_FILES = ("eval.py",)
REQUIRED_NEGATIVE_KINDS = {
    "empty", "metrics_only", "tampered_input",
    "skipped_steps", "encoded_payload", "fabricated_field",
}


def parse_audit_table(text: str) -> list[tuple[str, str]]:
    """Return ``(label, verdict)`` rows from the generated audit table.

    The record renders as ``| case | expectation | actual | verdict |``
    (``scripts/audit_task.py::render_audit_md``). Rows are only collected from
    inside that table; anything else in the file is ignored.
    """
    rows: list[tuple[str, str]] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0].lower() == "case":
            in_table = True
            continue
        if set(cells[0]) <= set("-: "):
            continue
        if in_table:
            rows.append((cells[0], cells[-1]))
    return rows


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

    # ---- audit matrix gate (spec/02 section 4.1)
    audit_text = audit.read_text() if audit.is_file() else ""
    cases_path = task_dir / "audit_cases.py"
    if not cases_path.is_file():
        errors.append("missing audit_cases.py (cannot verify the audit matrix)")
    else:
        spec = importlib.util.spec_from_file_location("_vcax_audit_cases", cases_path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 - a broken case file fails the pack
            errors.append(f"audit_cases.py failed to import: {exc}")
            module = None
        if module is not None:
            labels = [case[0] for case in getattr(module, "CASES", [])]
            positive = [label for label in labels if label[:1].upper() == "P"]
            alternative = [label for label in labels if label[:1].upper() == "A"]
            negative = [label for label in labels if label[:1].upper() == "N"]
            if len(positive) < 1:
                errors.append("audit matrix: positive group needs >= 1 case")
            if len(alternative) < 2:
                errors.append("audit matrix: alternative group needs >= 2 legal "
                              f"cases (found {len(alternative)})")
            if len(negative) < 6:
                errors.append("audit matrix: negative group needs >= 6 cases "
                              f"(found {len(negative)})")
            kinds = getattr(module, "NEGATIVE_KINDS", None)
            if not isinstance(kinds, dict):
                errors.append("audit matrix: audit_cases.py must declare NEGATIVE_KINDS")
            else:
                unknown = sorted(set(kinds.values()) - REQUIRED_NEGATIVE_KINDS)
                if unknown:
                    errors.append(f"audit matrix: unknown negative kinds {unknown}")
                missing = sorted(REQUIRED_NEGATIVE_KINDS - set(kinds.values()))
                if missing:
                    errors.append(f"audit matrix: negative kinds missing {missing}")
                stray = sorted(label for label in kinds if label not in labels)
                if stray:
                    errors.append(f"audit matrix: NEGATIVE_KINDS names unknown cases {stray}")
            table_rows = parse_audit_table(audit_text)
            if not table_rows:
                errors.append("audit record has no case table "
                              "(rerun scripts/audit_task.py)")
            else:
                labels_in_table = [label for label, _ in table_rows]
                duplicate = sorted({label for label in labels_in_table
                                    if labels_in_table.count(label) > 1})
                if duplicate:
                    errors.append(f"audit table has duplicate rows: {duplicate}")
                table = dict(table_rows)
                missing_rows = [label for label in labels if label not in table]
                extra_rows = [label for label in table if label not in labels]
                if missing_rows:
                    errors.append(f"audit table is missing cases: {missing_rows}")
                if extra_rows:
                    errors.append(f"audit table has unknown rows: {extra_rows}")
                not_pass = [label for label, verdict in table_rows
                            if verdict.upper() != "PASS"]
                if not_pass:
                    errors.append(f"audit table rows are not PASS: {not_pass}")
    robust = re.search(r"robust: (\d+)/(\d+) consistent", audit_text)
    if not robust:
        errors.append("audit record has no robustness record "
                      "(run scripts/audit_task.py --repeat 10)")
    else:
        agreeing, runs = int(robust.group(1)), int(robust.group(2))
        if runs < 10:
            errors.append(f"robustness group has only {runs} runs; need >= 10")
        if agreeing != runs:
            errors.append(f"robustness group inconsistent ({agreeing}/{runs})")
    l0_path = task_dir / "ground_truth" / L0_RECORD
    if l0_path.is_file():
        try:
            l0 = json.loads(l0_path.read_text())
        except ValueError:
            errors.append(f"{L0_RECORD} is not valid JSON")
        else:
            if not l0.get("passed"):
                errors.append("L0 reference self-check did not pass")
    elif args.check:
        print(f"warning: no {L0_RECORD} in this checkout (it is gitignored); "
              f"L0 was gated when the manifest was written", file=sys.stderr)
    else:
        errors.append(f"missing {L0_RECORD}: run `vericax audit --task "
                      f"{args.task}` before writing the manifest")

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
