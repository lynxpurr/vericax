#!/usr/bin/env python3
"""Offline tests for benchmark-validity helpers and report filtering.

No VM, no model, no docker: these cover the schema additions (run_mode,
tree_version, reference_selfcheck, kind), L0 summary comparison, adapter-level
cost event filtering, and capability/test aggregation.

    python3 tests/test_validity.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from vericax import adapters, lifecycle, summary, validity  # noqa: E402


class TreeVersionTests(unittest.TestCase):
    def test_stable_and_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            manifest = task / validity.MANIFEST
            manifest.write_text("abc  eval.py\n")
            first = validity.tree_version(task)
            self.assertEqual(first, validity.tree_version(task))
            manifest.write_text("def  eval.py\n")
            self.assertNotEqual(first, validity.tree_version(task))
            self.assertTrue(first.startswith("sha256:"))

    def test_missing_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                validity.tree_version(Path(tmp))


class SummaryComparisonTests(unittest.TestCase):
    def test_numeric_tolerance(self):
        self.assertTrue(validity.compare_summaries("0.1, 1.0", "0.10000001, 1.0"))
        self.assertFalse(validity.compare_summaries("0.1, 1.0", "0.2, 1.0"))

    def test_text_fallback(self):
        self.assertTrue(validity.compare_summaries("True", "True"))
        self.assertFalse(validity.compare_summaries("True", "False"))

    def test_missing_side_fails(self):
        self.assertFalse(validity.compare_summaries(None, "1.0"))


class CostExtractionTests(unittest.TestCase):
    def _adapter(self, event_types):
        return adapters.Adapter(
            name="pi", version="1.4.0", command=["pi"],
            cost_path="usage", cost_event_types=event_types)

    def test_message_updates_are_not_calls(self):
        stdout = "\n".join(json.dumps(event) for event in [
            {"type": "message_start", "usage": {"input": 0, "output": 0}},
            {"type": "message_update", "usage": {"input": 9, "output": 9}},
            {"type": "message_end", "usage": {"input": 5, "output": 2, "reasoning": 1}},
            {"type": "turn_end", "usage": {"input": 5, "output": 2, "reasoning": 1}},
        ])
        cost = lifecycle._extract_cost(self._adapter(["message_end"]), stdout)
        self.assertEqual(cost["llm_calls"], 1)
        self.assertEqual(cost["prompt_tokens"], 5)
        self.assertEqual(cost["completion_tokens"], 2)
        self.assertEqual(cost["reasoning_tokens"], 1)

    def test_empty_filter_keeps_legacy_behavior(self):
        stdout = json.dumps({"type": "status", "usage": {"input": 3, "output": 4}})
        cost = lifecycle._extract_cost(self._adapter([]), stdout)
        self.assertEqual(cost["llm_calls"], 1)
        self.assertEqual(cost["prompt_tokens"], 3)


class ReportTests(unittest.TestCase):
    def _row(self, agent, score, kind=None):
        row = {
            "task_id": "t1", "agent": {"name": agent}, "model": {"name": "m"},
            "score": score, "scoring_basis": summary.SCORING_BASIS_NATIVE,
            "error_category": None, "tree_version": "sha256:" + "a" * 64,
            "run_mode": "rerun",
        }
        if kind:
            row["kind"] = kind
        return row

    def _write(self, root, name, row):
        episode = Path(root) / name
        episode.mkdir()
        (episode / "summary.json").write_text(json.dumps(row))

    def test_cheat_suite_excluded_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "ep-1", self._row("dsh", 1.0))
            self._write(tmp, "ep-2", self._row("fake", 0.0))
            with redirect_stdout(io.StringIO()):
                text = lifecycle.report(Path(tmp))
            self.assertIn("dsh", text)
            self.assertNotIn("fake", text)
            self.assertIn("excluded 1", text)

    def test_include_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "ep-1", self._row("dsh", 1.0))
            self._write(tmp, "ep-2", self._row("fake", 0.0))
            with redirect_stdout(io.StringIO()):
                text = lifecycle.report(Path(tmp), include_tests=True)
            self.assertIn("fake", text)

    def test_n_three_mean_and_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index, score in enumerate((0.0, 1.0, 1.0), start=1):
                self._write(tmp, f"ep-{index}", self._row("dsh", score))
            with redirect_stdout(io.StringIO()):
                text = lifecycle.report(Path(tmp))
            self.assertIn("3/3", text)
            self.assertIn("0.666666", text)
            self.assertIn("| 0.0 | 1.0 |", text)


class SummarySchemaTests(unittest.TestCase):
    def test_new_fields_have_defaults(self):
        data = summary.build_summary(
            task_id="t", episode_id="e", run_index=1, run_total=1,
            agent={"name": "a"}, harness={"name": "a"}, model={"name": "m"},
            score=1.0, scoring_basis=summary.SCORING_BASIS_NATIVE,
            native_evaluator_executed=True, error=None, error_category=None,
            result_dir="/tmp/e", artifact_uri=None, cost=None,
            wall_duration_seconds=1.0, active_duration_seconds=1.0,
            active_time_limit_seconds=10, split_version="v",
            image_sha256="x")
        self.assertEqual(data["run_mode"], "rerun")
        self.assertEqual(data["kind"], "capability")
        self.assertIsNone(data["tree_version"])
        self.assertEqual(data["reference_selfcheck"], "not_run")


if __name__ == "__main__":
    unittest.main(verbosity=2)