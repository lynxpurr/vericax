#!/usr/bin/env python3
"""Repository hygiene check: no secrets, no machine-specific absolute paths.

Runs locally and in CI. Placeholders used by the specs (`/home/user/...`,
`C:\\Users\\user\\...`) are explicitly allowed, because they are part of the
evaluation protocol rather than leftovers from a developer machine.

    python scripts/check_repo_hygiene.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9._-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
]

ALLOWED_HOME_NAMES = {"user", "<user>", "username", "runner", "azure"}
HOME_PATH = re.compile(r"/home/([A-Za-z0-9_.-]+)/")
WIN_PATH = re.compile(r"C:\\\\Users\\\\([A-Za-z0-9_.-]+)\\\\")

TEXT_SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".toml", ".cff", ".txt",
                 ".inp", ".sha256", ".gitignore", ".gitattributes", ".editorconfig"}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    if out.returncode != 0:
        print("not a git repository", file=sys.stderr)
        raise SystemExit(2)
    return [REPO / line for line in out.stdout.splitlines() if line]


def main() -> int:
    problems: list[str] = []
    for path in tracked_files():
        if path.suffix not in TEXT_SUFFIXES and path.name not in {".gitignore", ".gitattributes", ".editorconfig"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(REPO)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    problems.append(f"{rel}:{lineno}: possible secret ({pattern.pattern})")
            for match in HOME_PATH.finditer(line):
                if match.group(1) not in ALLOWED_HOME_NAMES:
                    problems.append(f"{rel}:{lineno}: machine-specific home path ({match.group(0)})")
            for match in WIN_PATH.finditer(line):
                if match.group(1).lower() not in ALLOWED_HOME_NAMES:
                    problems.append(f"{rel}:{lineno}: machine-specific Windows path ({match.group(0)})")

    if problems:
        print("hygiene check FAILED:")
        for problem in problems:
            print(" -", problem)
        return 1
    print("hygiene check passed: no secrets, no machine-specific paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
