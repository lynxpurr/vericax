#!/usr/bin/env python3
"""Offline tests for the audit harness: expectations, rejection margin and the
per-case workspace restore.

No VM, no docker, no model: these cover the pure helpers behind
``scripts/audit_task.py`` and the table parser in ``scripts/pack_task.py``.

    python3 tests/test_audit_tooling.py
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit_task = _load("audit_task", REPO / "scripts" / "audit_task.py")
pack_task = _load("pack_task", REPO / "scripts" / "pack_task.py")


class ExpectationTests(unittest.TestCase):
    def test_exact_match_has_no_numeric_value(self):
        ok, detail, value = audit_task.check_expectation(("true",), "True\nrc=0")
        self.assertTrue(ok)
        self.assertIsNone(value)
        self.assertIn("want=True", detail)

        ok, _, _ = audit_task.check_expectation(("false",), "True\nrc=0")
        self.assertFalse(ok)

    def test_numeric_bounds_return_the_score(self):
        ok, detail, value = audit_task.check_expectation(("ge", 0.34), "0.5\nrc=0")
        self.assertTrue(ok)
        self.assertEqual(value, 0.5)
        self.assertIn("want>=0.34", detail)

        ok, _, value = audit_task.check_expectation(("le", 0.001), "0.0\nrc=0")
        self.assertTrue(ok)
        self.assertEqual(value, 0.0)

        ok, _, _ = audit_task.check_expectation(("le", 0.001), "0.5\nrc=0")
        self.assertFalse(ok)

    def test_unparseable_verdict(self):
        ok, detail, value = audit_task.check_expectation(("le", 0.001), "boom")
        self.assertFalse(ok)
        self.assertIsNone(value)
        self.assertIn("unparseable", detail)


class RejectionMarginTests(unittest.TestCase):
    def test_margin_is_lowest_accept_minus_highest_reject(self):
        observed = [
            (("ge", 0.9), 0.95),
            (("ge", 0.5), 0.55),
            (("le", 0.001), 0.0),
            (("le", 0.001), 0.02),
        ]
        margin = audit_task.rejection_margin(observed)
        self.assertAlmostEqual(margin["margin"], 0.53)
        self.assertAlmostEqual(margin["min_positive"], 0.55)
        self.assertAlmostEqual(margin["max_negative"], 0.02)

    def test_overlapping_bands_are_negative(self):
        margin = audit_task.rejection_margin(
            [(("ge", 0.2), 0.2), (("le", 0.3), 0.3)])
        self.assertLess(margin["margin"], 0)

    def test_exact_match_tasks_have_no_margin(self):
        observed = [(("true",), None), (("false",), None)]
        self.assertIsNone(audit_task.rejection_margin(observed))

    def test_unparseable_verdicts_do_not_enter_the_margin(self):
        self.assertIsNone(audit_task.rejection_margin(
            [(("ge", 0.1), None), (("le", 0.0), None)]))


class AuditRecordTests(unittest.TestCase):
    def test_render_records_margin_and_keeps_the_table_parseable(self):
        results = [
            ("P1 positive (gold)", "want>=0.34 got=0.500000", True, ""),
            ("N1 empty delivery", "want<=0.0 got=0.000000", True, ""),
        ]
        margin = {"margin": 0.5, "min_positive": 0.5, "max_negative": 0.0}
        text = audit_task.render_audit_md(
            {"id": "cae--cli--calculix--task-9999",
             "evaluator": {"func": "quantified_score"}},
            results, "0.5", margin=margin)
        self.assertIn("- rejection margin: 0.500000", text)

        rows = pack_task.parse_audit_table(text)
        self.assertEqual([label for label, _ in rows],
                         ["P1 positive (gold)", "N1 empty delivery"])
        self.assertTrue(all(verdict == "PASS" for _, verdict in rows))

    def test_render_marks_exact_match_tasks_as_na(self):
        text = audit_task.render_audit_md(
            {"id": "x"}, [("P1", "want=True got=True", True, "")], "True")
        self.assertIn("rejection margin: n/a", text)


class WorkspaceIsolationTests(unittest.TestCase):
    def test_setup_snapshots_the_pristine_desktop(self):
        script = audit_task.workspace_setup_script()
        self.assertIn(f"tar -C {audit_task.DESK} -cf {audit_task.BASE_TAR}", script)
        self.assertIn(audit_task.TMP_BASELINE, script)
        self.assertIn("mkdir -p /home/user/vericax", script)

    def test_clean_restores_desktop_and_removes_new_tmp_files(self):
        script = audit_task.workspace_clean_script()
        self.assertIn(f"tar -C {audit_task.DESK} -xf {audit_task.BASE_TAR}", script)
        self.assertIn(f"find {audit_task.DESK} -mindepth 1 -maxdepth 1", script)
        self.assertIn("find /tmp -mindepth 1 -maxdepth 1 -type f", script)
        self.assertIn(f"comm -13 {audit_task.TMP_BASELINE}", script)
        self.assertIn(f"rm -rf {audit_task.SCRATCH}", script)
        # never wipe /tmp wholesale: the live desktop session owns sockets/dirs
        self.assertNotIn("rm -rf /tmp;", script)
        self.assertNotIn("rm -rf /tmp ", script)


if __name__ == "__main__":
    unittest.main()