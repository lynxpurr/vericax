"""Every verifier that reads a CalculiX deck must accept the deck in every legal spelling.

Agents write legal decks in spellings an author does not imagine. The
published verifiers rejected 34 correct B2 episodes on such spellings (the
third correction of 2026-11-28 in docs/results), and two new tasks rejected
14 of 18 correct decks in calibration although their audits passed. An audit
matrix checks the spellings the author thought of; this test re-spells every
gold deck mechanically (scripts/deck_variants.py) and requires each
verifier's deck checks to accept the result. No solver runs: the checks are
the ones that run before the re-solve.

    python3 -m unittest tests.test_deck_spellings
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import deck_canonical  # noqa: E402
import deck_variants  # noqa: E402

COPIED_START = ("# ---- deck spellings: copied verbatim from scripts/deck_canonical.py "
                "(tests/test_deck_spellings.py checks the copy) ----")
COPIED_END = "# ---- end of the copied block ----"

CALCULIX = "cae--cli--calculix--"
CROSS = "cae--cli--cross-solver--"


def _l2(module, text: str) -> bool:
    return module.l2_design_conformance(text) is True


def _grid(grid: str):
    def call(module, text: str) -> bool:
        return module.check_deck(text, *module.GRIDS[grid], grid) is True
    return call


# task id -> {gold deck file: the deck checks of its verifier, as (module, text) -> bool}
REGISTRY: dict[str, dict[str, object]] = {
    CALCULIX + "task-0001": {"solution.inp": _l2},
    CALCULIX + "task-0002": {"solution.inp": lambda m, t: m.parse_design(t) is not None},
    CALCULIX + "task-0003": {"solution.inp": lambda m, t: m.l2_design_and_loadcases(t) is True},
    CALCULIX + "task-0004": {"solution.inp": _l2},
    CALCULIX + "task-0005": {"solution.inp": _l2},
    CALCULIX + "task-0006": {"solution.inp": _l2},
    CALCULIX + "task-0007": {"solution.inp": _l2},
    CALCULIX + "task-0008": {"solution.inp": _l2},
    CALCULIX + "task-0009": {"coarse.inp": _grid("coarse"), "fine.inp": _grid("fine")},
    CALCULIX + "task-0010": {"beam.inp": lambda m, t: m.check_beam(t) is True,
                             "solid.inp": lambda m, t: m.check_solid(t) is True},
    CALCULIX + "task-0011": {"solution.inp": _l2},
    CALCULIX + "task-0012": {"solution.inp": _l2},
    CALCULIX + "task-0013": {"plate.inp": lambda m, t: m.conformance(t) is not None},
    CALCULIX + "task-0014": {"column.inp": lambda m, t: m.parse_deck(t) is not None},
    CROSS + "task-0001": {"solution.inp": _l2},
    CROSS + "task-0002": {"solution.inp": _l2},
    CROSS + "task-0005": {"solution.inp": _l2},
}

_CACHE: dict[str, object] = {}


def load_verifier(task_id: str):
    """The task's eval.py as a module (standard library only; nothing runs at import)."""
    if task_id not in _CACHE:
        path = REPO / "tasks" / task_id.replace("--", "/") / "eval.py"
        spec = importlib.util.spec_from_file_location("verifier_" + task_id.replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CACHE[task_id] = module
    return _CACHE[task_id]


class DeckSpellingTests(unittest.TestCase):
    def _cases(self):
        for task_id, decks in REGISTRY.items():
            if not (REPO / "tasks" / task_id.replace("--", "/")).is_dir():
                continue                       # a task not on this branch yet
            for deck_name, check in decks.items():
                yield task_id, deck_name, check

    def _accepts(self, check, text: str) -> tuple[bool, str]:
        err = io.StringIO()
        with redirect_stderr(err):
            try:
                ok = bool(check(load_verifier(self._task), text))
            except Exception as exc:            # noqa: BLE001 - a rejection raised as an error
                return False, f"{type(exc).__name__}: {exc}"
        return ok, err.getvalue().strip().replace("\n", " | ")

    def test_gold_and_every_spelling_are_accepted(self):
        for task_id, deck_name, check in self._cases():
            self._task = task_id
            text = (REPO / "tasks" / task_id.replace("--", "/") / "ground_truth" / deck_name).read_text()
            ok, why = self._accepts(check, text)
            self.assertTrue(ok, f"{task_id} {deck_name}: the gold deck is rejected: {why}")
            for name, variant in deck_variants.variants(text) + deck_variants.variants(text, apply_all=True):
                with self.subTest(task=task_id, deck=deck_name, spelling=name):
                    ok, why = self._accepts(check, variant)
                    self.assertTrue(ok, f"{task_id} {deck_name} rejected in the spelling '{name}': {why}")

    def test_every_deck_verifier_is_registered(self):
        # A CalculiX or cross-solver package whose verifier reads a deck and is
        # missing here gets no spelling check at all.
        for family in ("calculix", "cross-solver"):
            for path in sorted((REPO / "tasks" / "cae" / "cli" / family).glob("task-*")):
                task_id = "--".join(("cae", "cli", family, path.name))
                source = (path / "eval.py").read_text()
                reads_a_deck = "inp_blocks(" in source or "def parse_deck(" in source or "def conformance(" in source
                if reads_a_deck:
                    self.assertIn(task_id, REGISTRY, f"{task_id} reads a deck but has no entry")

    def test_the_copied_normaliser_matches_its_source(self):
        # Each deck verifier that carries canonical_deck must carry the current
        # scripts/deck_canonical.py, or a fix made to the source never reaches it.
        source = (REPO / "scripts" / "deck_canonical.py").read_text().rstrip("\n")
        carriers = 0
        for path in sorted((REPO / "tasks").rglob("eval.py")):
            text = path.read_text()
            if COPIED_START not in text:
                continue
            carriers += 1
            block = text.split(COPIED_START + "\n", 1)[1].split("\n" + COPIED_END, 1)[0]
            self.assertEqual(block.rstrip("\n"), source, f"{path}: run the injector again")
            self.assertIn("    text = canonical_deck(text)\n", text, f"{path}: inp_blocks does not call it")
        self.assertGreaterEqual(carriers, 15)


def _shape(text: str) -> list:
    """Cards of a canonical deck without the helper sets a variant adds; numbers as floats."""
    out = []
    card, skip = None, False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("**"):
            continue
        if s.startswith("*"):
            skip = bool(re.search(r"(ELSET|NSET)\s*=\s*VCAX_", s.upper()))
            card = [s.split(",")[0].strip().upper(), []]
            if not skip:
                out.append(card)
            continue
        if skip or card is None:
            continue
        row = []
        for token in [t.strip() for t in s.split(",") if t.strip()]:
            try:
                row.append(float(token.replace("D", "E")))
            except ValueError:
                row.append(token.upper())
        card[1].append(row)
    return out


def _same_meaning(a: list, b: list) -> bool:
    if len(a) != len(b):
        return False
    for (name_a, rows_a), (name_b, rows_b) in zip(a, b):
        if name_a != name_b or len(rows_a) != len(rows_b):
            return False
        for row_a, row_b in zip(rows_a, rows_b):
            if len(row_a) != len(row_b):
                return False
            for x, y in zip(row_a, row_b):
                if isinstance(x, float) and isinstance(y, float):
                    if abs(x - y) > 1e-6 * max(1.0, abs(x)):
                        return False
                elif x != y:
                    return False
    return True


class CanonicalDeckTests(unittest.TestCase):
    def test_every_re_spelling_has_the_meaning_of_the_gold(self):
        checked = 0
        for path in sorted((REPO / "tasks" / "cae" / "cli").glob("*/task-*/ground_truth/*.inp")):
            text = path.read_text()
            gold = deck_canonical.canonical_deck(text)
            self.assertEqual(deck_canonical.canonical_deck(gold), gold, f"{path}: not idempotent")
            for name, variant in deck_variants.variants(text):
                if name == "nset_on_node_card":
                    continue            # adds a set; compared by the verifiers instead
                checked += 1
                with self.subTest(deck=str(path.relative_to(REPO)), spelling=name):
                    self.assertTrue(_same_meaning(_shape(gold), _shape(deck_canonical.canonical_deck(variant))))
        self.assertGreaterEqual(checked, 60)

    def test_a_real_agent_spelling_is_unpacked(self):
        deck = ("*Node, NSET=ALL\n1, 0.0, 0.0\n2, 5.0, 0.0\n*Element, type=B31, ELSET=E\n1, 1, 2\n"
                "*Nset, nset=FIX, generate\n1, 1, 1\n*Boundary\nFIX, 1\n*Step\n*Static\n*Cload\nALL, 2, -100.0\n")
        got = deck_canonical.canonical_deck(deck)
        self.assertIn("1, 0.0, 0.0, 0.0", got)
        self.assertIn("*Nset, nset=ALL\n1, 2", got)
        self.assertIn("*Nset, nset=FIX\n1", got)
        self.assertIn("1, 1, 1, 0.0", got)
        self.assertIn("1, 2, -100.0\n2, 2, -100.0", got)

    def test_a_trailing_comma_continues_a_data_line(self):
        deck = "*Nset, nset=S\n1, 2,\n3\n*Cload\n1, 2,\n-5.0\n"
        got = deck_canonical.canonical_deck(deck)
        self.assertIn("*Nset, nset=S\n1, 2, 3", got)
        self.assertIn("1, 2, -5.0", got)


if __name__ == "__main__":
    unittest.main()
