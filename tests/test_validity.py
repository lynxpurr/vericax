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
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from vericax import adapters, lifecycle, proxy, summary, validity  # noqa: E402


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


class ChallengeBindingTests(unittest.TestCase):
    def _task(self, instruction, provenance=None):
        task = {"instruction": instruction, "id": "t"}
        if provenance is not None:
            task["provenance"] = provenance
        return task

    def test_placeholder_is_rendered_per_episode(self):
        text = lifecycle.instruction_text(
            self._task("name the set {challenge}"), ["/tmp/a"], 0, challenge="VCAX_EP_AB")
        self.assertIn("name the set VCAX_EP_AB", text)
        self.assertNotIn("{challenge}", text)

    def test_placeholder_without_token_is_an_error(self):
        with self.assertRaises(SystemExit):
            lifecycle.instruction_text(
                self._task("name the set {challenge}"), ["/tmp/a"], 0)

    def test_l6_task_without_placeholder_gets_a_fallback_paragraph(self):
        text = lifecycle.instruction_text(
            self._task("legacy text", {"challenge": "VCAX_AUDIT_1"}),
            ["/tmp/a"], 0, challenge="VCAX_EP_AB")
        self.assertIn("Episode challenge token", text)
        self.assertIn("VCAX_EP_AB", text)

    def test_non_l6_task_gets_no_token(self):
        self.assertIsNone(lifecycle.episode_challenge(self._task("plain")))
        self.assertIsNotNone(lifecycle.episode_challenge(
            self._task("plain", {"challenge": "VCAX_AUDIT_1"})))
        self.assertNotEqual(
            lifecycle.episode_challenge(self._task("plain", {"challenge": "VCAX_AUDIT_1"})),
            lifecycle.episode_challenge(self._task("plain", {"challenge": "VCAX_AUDIT_1"})))

    def test_summary_records_binding(self):
        data = summary.build_summary(
            task_id="t", episode_id="e", run_index=1, run_total=1,
            agent={"name": "a"}, harness={"name": "a"}, model={"name": "m"},
            score=1.0, scoring_basis=summary.SCORING_BASIS_NATIVE,
            native_evaluator_executed=True, error=None, error_category=None,
            result_dir="/tmp/e", artifact_uri=None, cost=None,
            wall_duration_seconds=1.0, active_duration_seconds=1.0,
            active_time_limit_seconds=10, split_version="v", image_sha256="x",
            challenge="VCAX_EP_AB", required_tool="calculix")
        self.assertEqual(data["challenge"], "VCAX_EP_AB")
        self.assertEqual(data["required_tool"], "calculix")


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

    def test_single_pretty_json_envelope(self):
        # openclaw --json prints one indented envelope, not NDJSON.
        envelope = json.dumps(
            {"usage": {"input": 9, "output": 1, "cost": {"total": 0.0}}}, indent=2)
        cost = lifecycle._extract_cost(self._adapter([]), envelope)
        self.assertEqual(cost["llm_calls"], 1)
        self.assertEqual(cost["prompt_tokens"], 9)
        self.assertEqual(cost["completion_tokens"], 1)


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
            # scripted/cheat episodes declare their kind at run time; the
            # harness never infers it from a stack name (rule A1)
            self._write(tmp, "ep-2", self._row("fake", 0.0, kind="test"))
            with redirect_stdout(io.StringIO()):
                text = lifecycle.report(Path(tmp))
            self.assertIn("dsh", text)
            self.assertNotIn("fake", text)
            self.assertIn("excluded 1", text)

    def test_include_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "ep-1", self._row("dsh", 1.0))
            self._write(tmp, "ep-2", self._row("fake", 0.0, kind="test"))
            with redirect_stdout(io.StringIO()):
                text = lifecycle.report(Path(tmp), include_tests=True)
            self.assertIn("fake", text)

    def test_unlabelled_episode_defaults_to_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "ep-1", self._row("fake", 0.0))  # no kind
            with redirect_stdout(io.StringIO()):
                text = lifecycle.report(Path(tmp))
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


class ProxySocketPathTests(unittest.TestCase):
    def test_temp_socket_path_is_short_and_unique(self):
        first = proxy.temp_socket_path()
        second = proxy.temp_socket_path()
        try:
            # AF_UNIX paths are capped at 108 bytes; the episode directory is
            # much longer than this once the adapter name is included.
            self.assertLess(len(str(first)), 100)
            self.assertLess(len(str(second)), 100)
            self.assertNotEqual(first, second)
            self.assertTrue(first.parent.is_dir())
        finally:
            shutil.rmtree(first.parent, ignore_errors=True)
            shutil.rmtree(second.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)