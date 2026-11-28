#!/usr/bin/env python3
"""Mechanical re-spellings of a CalculiX deck that keep its meaning.

Agents write legal decks in spellings an author does not imagine. The
published verifiers rejected 34 correct B2 episodes on such spellings (the
third correction of 2026-11-28 in docs/results). Each function here rewrites
a deck into one of those spellings, or returns None when the deck has nothing
to re-spell. ``tests/test_deck_spellings.py`` applies every variant to every
gold deck and requires each verifier's deck checks to accept the result; the
audit cases of a package can use the same functions.

    python3 scripts/deck_variants.py <deck.inp>        # list what a deck can be re-spelled into
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

INT = re.compile(r"^[+-]?\d+$")
NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([DdEe][+-]?\d+)?$")
LOAD_CARDS = ("*DLOAD", "*CLOAD", "*DSLOAD")
SET_NAME = re.compile(r"(ELSET|NSET)\s*=\s*([A-Za-z0-9_.-]+)")


def _keyword(line: str) -> bool:
    s = line.strip()
    return s.startswith("*") and not s.startswith("**")


def _skippable(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("**")


def _base(line: str) -> str:
    return line.strip().split(",")[0].strip().upper()


def _has_flag(keyword_line: str, flag: str) -> bool:
    return any(part.strip() == flag for part in keyword_line.upper().split(",")[1:])


def _number(token: str) -> float:
    return float(token.replace("D", "E"))


def _tokens(line: str) -> list[str]:
    return [t.strip() for t in line.strip().split(",") if t.strip()]


def _cards(lines: list[str]):
    """Yield (card name, keyword line index, data line indices) for every card."""
    base, start, data = None, None, []
    for i, line in enumerate(lines):
        if _keyword(line):
            if base is not None:
                yield base, start, data
            base, start, data = _base(line), i, []
        elif base is not None and not _skippable(line):
            data.append(i)
    if base is not None:
        yield base, start, data


def _first_step(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if _keyword(line) and _base(line) == "*STEP":
            return i
    return len(lines)


def _progression(ids: list[int]) -> tuple[int, int, int] | None:
    """(first, last, increment) when the ids form one arithmetic progression."""
    ordered = sorted(set(ids))
    if len(ordered) < 2 or len(ordered) != len(ids):
        return None
    step = ordered[1] - ordered[0]
    if step <= 0 or any(b - a != step for a, b in zip(ordered, ordered[1:])):
        return None
    return ordered[0], ordered[-1], step


def set_members(lines: list[str]) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Members of every element set and node set, in either spelling."""
    elsets: dict[str, list[int]] = {}
    nsets: dict[str, list[int]] = {}
    for base, start, data in _cards(lines):
        keyword = lines[start].upper()
        if base in ("*ELSET", "*NSET"):
            match = SET_NAME.search(keyword)
            if not match:
                continue
            store = elsets if match.group(1) == "ELSET" else nsets
            name = match.group(2).upper()
            ids: list[int] = []
            for i in data:
                toks = _tokens(lines[i])
                if toks and all(INT.match(t) for t in toks):
                    ids.extend(int(t) for t in toks)
            if _has_flag(keyword, "GENERATE") and len(ids) == 3 and ids[2] > 0:
                store[name] = list(range(ids[0], ids[1] + 1, ids[2]))
            else:
                store.setdefault(name, []).extend(ids)
        elif base in ("*ELEMENT", "*NODE"):
            match = SET_NAME.search(keyword)
            if match:
                store = elsets if match.group(1) == "ELSET" else nsets
                for i in data:
                    toks = _tokens(lines[i])
                    if toks and INT.match(toks[0]):
                        store.setdefault(match.group(2).upper(), []).append(int(toks[0]))
    return elsets, nsets


def generate_sets(text: str) -> str | None:
    """Element and node sets listed in full become ``GENERATE`` (first, last, step)."""
    lines = text.splitlines()
    changed = False
    for base, start, data in reversed(list(_cards(lines))):
        if base not in ("*ELSET", "*NSET") or not data or _has_flag(lines[start], "GENERATE"):
            continue
        ids: list[int] = []
        for i in data:
            toks = _tokens(lines[i])
            if not toks or not all(INT.match(t) for t in toks):
                ids = []
                break
            ids.extend(int(t) for t in toks)
        span = _progression(ids)
        if span is None:
            continue
        lines[start] = lines[start].rstrip() + ", GENERATE"
        lines[data[0]] = "{}, {}, {}".format(*span)
        for i in reversed(data[1:]):
            del lines[i]
        changed = True
    return "\n".join(lines) + "\n" if changed else None


def boundary_on_sets(text: str) -> str | None:
    """``*BOUNDARY`` rows name a node set, and leave out the defaults (value 0,
    last dof = first dof)."""
    lines = text.splitlines()
    sets: dict[int, str] = {}
    changed = False
    for base, start, data in _cards(lines):
        if base != "*BOUNDARY":
            continue
        for i in data:
            toks = _tokens(lines[i])
            if not toks:
                continue
            new = list(toks)
            if INT.match(new[0]):
                node = int(new[0])
                sets.setdefault(node, f"VCAX_B{node}")
                new[0] = sets[node]
            if len(new) == 4 and NUM.match(new[3]) and _number(new[3]) == 0.0:
                new = new[:3]
            if len(new) == 3 and new[1] == new[2]:
                new = new[:2]
            if new != toks:
                lines[i] = ", ".join(new)
                changed = True
    if not changed:
        return None
    at = _first_step(lines)
    lines[at:at] = ["** node sets named by the *Boundary rows"] + [
        line for node, name in sorted(sets.items()) for line in (f"*Nset, nset={name}", str(node))]
    return "\n".join(lines) + "\n"


def nset_on_node_card(text: str) -> str | None:
    """The nodes of the first ``*NODE`` card are also declared as a set on that card."""
    lines = text.splitlines()
    for base, start, data in _cards(lines):
        if base == "*NODE" and not re.search(r"\bNSET\s*=", lines[start].upper()):
            lines[start] = lines[start].rstrip() + ", NSET=VCAX_ALLNODES"
            return "\n".join(lines) + "\n"
    return None


def trailing_commas(text: str) -> str | None:
    """The last data line of a card ends with a comma before the next keyword."""
    lines = text.splitlines()
    changed = False
    for base, start, data in _cards(lines):
        if base == "*HEADING" or not data:
            continue
        last = data[-1]
        if last + 1 < len(lines) and _keyword(lines[last + 1]) and not lines[last].rstrip().endswith(","):
            lines[last] = lines[last].rstrip() + ","
            changed = True
    return "\n".join(lines) + "\n" if changed else None


def two_coordinate_nodes(text: str) -> str | None:
    """A node on the plane z = 0 is written with two coordinates."""
    lines = text.splitlines()
    changed = False
    for base, start, data in _cards(lines):
        if base != "*NODE":
            continue
        for i in data:
            toks = _tokens(lines[i])
            if len(toks) == 4 and INT.match(toks[0]) and NUM.match(toks[3]) and _number(toks[3]) == 0.0:
                lines[i] = ", ".join(toks[:3])
                changed = True
    return "\n".join(lines) + "\n" if changed else None


def load_targets_by_id(text: str) -> str | None:
    """A load row names the element or node number where the deck names a
    one-member set, and a one-member set where the deck names the number."""
    lines = text.splitlines()
    elsets, nsets = set_members(lines)
    new_sets: list[str] = []
    counter = 0
    changed = False
    for base, start, data in _cards(lines):
        if base not in LOAD_CARDS:
            continue
        card, key, store = ("*Nset", "nset", nsets) if base == "*CLOAD" else ("*Elset", "elset", elsets)
        for i in data:
            toks = _tokens(lines[i])
            if not toks:
                continue
            new = list(toks)
            if INT.match(new[0]):
                counter += 1
                name = f"VCAX_L{counter}"
                new_sets += [f"{card}, {key}={name}", new[0]]
                new[0] = name
            else:
                members = store.get(new[0].upper(), [])
                if len(members) == 1:
                    new[0] = str(members[0])
            if new != toks:
                lines[i] = ", ".join(new)
                changed = True
    if not changed:
        return None
    at = _first_step(lines)
    lines[at:at] = ["** sets of one member, named by the load rows"] + new_sets
    return "\n".join(lines) + "\n"


def rounded_loads(text: str) -> str | None:
    """Every load number that has more digits is written with eight significant digits."""
    lines = text.splitlines()
    changed = False
    for base, start, data in _cards(lines):
        if base not in LOAD_CARDS:
            continue
        for i in data:
            toks = _tokens(lines[i])
            new = list(toks)
            for k, tok in enumerate(toks):
                if k >= 2 and NUM.match(tok):
                    value = _number(tok)
                    short = format(value, ".7g")
                    if float(short) != value:
                        new[k] = short
            if new != toks:
                lines[i] = ", ".join(new)
                changed = True
    return "\n".join(lines) + "\n" if changed else None


VARIANTS = (
    ("generate_sets", generate_sets),
    ("boundary_on_sets", boundary_on_sets),
    ("nset_on_node_card", nset_on_node_card),
    ("trailing_commas", trailing_commas),
    ("two_coordinate_nodes", two_coordinate_nodes),
    ("load_targets_by_id", load_targets_by_id),
    ("rounded_loads", rounded_loads),
)


def variants(text: str, apply_all: bool = False) -> list[tuple[str, str]]:
    """[(name, re-spelled deck)] of every variant the deck allows.

    ``apply_all`` chains the variants instead of applying each one to the
    original deck: the "every spelling at once" case of an audit.
    """
    out = []
    for name, fn in VARIANTS:
        result = fn(text)
        if result is not None:
            out.append((name, result))
            if apply_all:
                text = result
    return out if not apply_all else ([("all", text)] if out else [])


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    text = Path(sys.argv[1]).read_text()
    for name, deck in variants(text):
        print(f"{name}: {len(deck.splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
