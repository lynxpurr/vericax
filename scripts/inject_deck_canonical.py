#!/usr/bin/env python3
"""Put the canonical-deck block into the deck verifiers that read CalculiX decks.

The block is scripts/deck_canonical.py between two marker lines, and
``inp_blocks`` of each verifier starts with ``text = canonical_deck(text)``.
Re-running replaces an existing block, so the copies can be refreshed after the
source changes. Each verifier is imported afterwards and tried on a small deck;
tests/test_deck_spellings.py then requires every copy to equal the source.

    python3 scripts/inject_deck_canonical.py                   # every deck verifier
    python3 scripts/inject_deck_canonical.py cae--cli--calculix--task-0013
"""
import importlib.util
import sys
from pathlib import Path

START = "# ---- deck spellings: copied verbatim from scripts/deck_canonical.py (tests/test_deck_spellings.py checks the copy) ----"
END = "# ---- end of the copied block ----"


def block_lines(repo: Path) -> list[str]:
    body = repo.joinpath("scripts", "deck_canonical.py").read_text().rstrip("\n").splitlines()
    return [START + "\n"] + [line + "\n" for line in body] + [END + "\n"]


def patch(path: Path, block: list[str]) -> bool:
    lines = path.read_text().splitlines(keepends=True)
    while True:
        starts = [i for i, l in enumerate(lines) if l.rstrip("\n") == START]
        if not starts:
            break
        a = starts[0]
        b = next(i for i in range(a, len(lines)) if lines[i].rstrip("\n") == END)
        del lines[a:b + 1]
        if a < len(lines) and lines[a].strip() == "":
            del lines[a]
    a = next(i for i, l in enumerate(lines) if l.startswith("def inp_blocks("))
    while a > 0 and lines[a - 1].lstrip().startswith("#"):
        a -= 1                    # keep the section comment above the block
    lines[a:a] = block + ["\n"]
    target = next(i for i, l in enumerate(lines) if l.startswith("def inp_blocks("))
    body = target + 1
    if '"""' in lines[body] or "'''" in lines[body]:
        quote = '"""' if '"""' in lines[body] else "'''"
        if lines[body].count(quote) < 2:
            body = next(i for i in range(body + 1, len(lines)) if quote in lines[i])
        body += 1
    call = "    text = canonical_deck(text)\n"
    if lines[body] != call:
        lines.insert(body, call)
    new = "".join(lines)
    if new != path.read_text():
        path.write_text(new)
        return True
    return False


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    ids = sys.argv[1:] or [f"cae--cli--calculix--task-{n:04d}" for n in range(1, 15)] + [
        f"cae--cli--cross-solver--task-{n:04d}" for n in (1, 2, 5)]
    block = block_lines(repo)
    changed = 0
    for task_id in ids:
        path = repo / "tasks" / task_id.replace("--", "/") / "eval.py"
        if not path.is_file() or "def inp_blocks(" not in path.read_text():
            print("skip (no inp_blocks):", task_id)
            continue
        if patch(path, block):
            changed += 1
        spec = importlib.util.spec_from_file_location("v_" + task_id.replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sample = ("*Node, nset=NA\n1, 0.0, 0.0\n*Nset, nset=NB, generate\n1, 2, 1\n"
                  "*Boundary\nNB, 1\n*Cload\nNA, 2, -5\n")
        got = {kw: data for kw, data in module.inp_blocks(sample)}
        assert got["*NODE"] == ["1, 0.0, 0.0, 0.0"], (task_id, got["*NODE"])
        assert got["*BOUNDARY"] == ["1, 1, 1, 0.0", "2, 1, 1, 0.0"], (task_id, got["*BOUNDARY"])
        assert got["*CLOAD"] == ["1, 2, -5"], (task_id, got["*CLOAD"])
        assert "*NSET, NSET=NA" in got and got["*NSET, NSET=NA"] == ["1"], (task_id, got)
        print("ok", task_id)
    print("changed:", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
