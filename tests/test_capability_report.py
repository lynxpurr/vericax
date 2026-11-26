#!/usr/bin/env python3
"""Offline tests for scripts/capability_report.py (spec/11 report contract).

No VM, no docker, no model: synthetic summary.json + task packages in a
temporary directory.

    python3 tests/test_capability_report.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capability_report = _load("capability_report",
                          REPO / "scripts" / "capability_report.py")

TASK_ID = "cae--cli--calculix--task-0001"


def make_layout(root: Path) -> tuple[Path, Path]:
    tasks = root / "tasks"
    runs = root / "runs"
    task_dir = tasks / "cae" / "cli" / "calculix" / "task-0001"
    task_dir.mkdir(parents=True)
    (task_dir / "task-0001.json").write_text(json.dumps({
        "id": TASK_ID,
        "capability": "single-execution",
        "snapshot": "CalculiX-2.21",
    }))
    fenics_dir = tasks / "cae" / "cli" / "fenics" / "task-0001"
    fenics_dir.mkdir(parents=True)
    (fenics_dir / "task-0001.json").write_text(json.dumps({
        "id": "cae--cli--fenics--task-0001",
        "capability": "design-optimization",
        "snapshot": "FEniCS",
    }))
    runs.mkdir()
    return tasks, runs


def write_episode(runs: Path, name: str, **overrides) -> Path:
    row = {
        "episode_id": name,
        "task_id": TASK_ID,
        "agent": {"name": "dsh", "version": "0.2.1"},
        "model": {"name": "deepseek-flash"},
        "tree_version": "sha256:aaaaaaaaaaaaaaaa",
        "run_mode": "rerun",
        "kind": "capability",
        "score": 1.0,
        "scoring_basis": "native_evaluator",
        "cost": {"usd_estimate": 0.1, "prompt_tokens": 100, "completion_tokens": 20},
        "active_duration_seconds": 10,
        "error_category": None,
    }
    row.update(overrides)
    episode = runs / f"ep-{name}"
    episode.mkdir()
    (episode / "summary.json").write_text(json.dumps(row))
    return episode


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tasks, self.runs = make_layout(self.root)
        self.registry = capability_report.task_registry(self.tasks)

    def tearDown(self):
        self._tmp.cleanup()

    def _report(self, **kwargs):
        rows, _meta = capability_report.load_rows(
            self.runs, kwargs.pop("batch_dirs", None))
        return capability_report.aggregate(rows, self.registry, **kwargs)

    def test_cell_stats(self):
        for name, score in (("a", 1.0), ("b", 0.5), ("c", 0.0)):
            write_episode(self.runs, name, score=score)
        report = self._report()
        self.assertEqual(report["selected"], 3)
        cell = report["cells"][0]
        self.assertEqual(cell["capability"], "single-execution")
        self.assertEqual(cell["solver"], "CalculiX-2.21")
        self.assertEqual(cell["n"], 3)
        self.assertAlmostEqual(cell["mean"], 0.5)
        self.assertEqual(cell["min"], 0.0)
        self.assertEqual(cell["max"], 1.0)
        self.assertAlmostEqual(cell["usd_per_task"], 0.1)
        self.assertEqual(cell["tokens_total"], 360)
        self.assertEqual(cell["tokens_per_task"], 120)
        self.assertEqual(cell["active_median"], 10)
        self.assertEqual(cell["active_coverage"], "3/3")

    def test_test_and_debug_are_excluded_by_default(self):
        write_episode(self.runs, "a")
        write_episode(self.runs, "b", kind="test", score=0.0)
        write_episode(self.runs, "c", kind="debug", score=0.0)
        report = self._report()
        self.assertEqual(report["selected"], 1)
        self.assertEqual(report["excluded"], 2)
        self.assertEqual(report["cells"][0]["n"], 1)

        report = self._report(include_tests=True)
        self.assertEqual(report["selected"], 3)

    def test_infra_failures_are_counted_not_scored(self):
        write_episode(self.runs, "a")
        write_episode(self.runs, "b", scoring_basis="infra", score=None)
        report = self._report()
        cell = report["cells"][0]
        self.assertEqual(cell["episodes"], 2)
        self.assertEqual(cell["n"], 1)
        self.assertEqual(cell["infra"], 1)

    def test_cost_is_na_when_any_episode_lacks_it(self):
        write_episode(self.runs, "a")
        write_episode(self.runs, "b", cost=None)
        cell = self._report()["cells"][0]
        self.assertIsNone(cell["usd_per_task"])

    def test_require_n_gate(self):
        write_episode(self.runs, "a")
        write_episode(self.runs, "b")
        report = self._report(require_n=3)
        gate = [c for c in report["checks"] if c["level"] == "gate"]
        self.assertEqual(len(gate), 1)
        self.assertIn("n=2", gate[0]["message"])

    def test_mixed_tree_is_an_error_unless_allowed(self):
        write_episode(self.runs, "a", tree_version="sha256:aaaa")
        write_episode(self.runs, "b", tree_version="sha256:bbbb")
        report = self._report()
        self.assertEqual([c["level"] for c in report["checks"]], ["error"])
        allowed = self._report(allow_mixed_tree=True)
        self.assertEqual([c["level"] for c in allowed["checks"]], ["warning"])

    def test_batch_filter_limits_to_recorded_episodes(self):
        write_episode(self.runs, "a")
        write_episode(self.runs, "b")
        batch = self.root / "batch"
        batch.mkdir()
        (batch / "batch.json").write_text(json.dumps({
            "adapter": "dsh", "runs": 3, "kind": "capability",
            "jobs": 1, "verdict": "pass",
            "episodes": [{"episode_id": "a"}],
        }))
        rows, meta = capability_report.load_rows(self.runs, [batch])
        report = capability_report.aggregate(rows, self.registry)
        self.assertEqual(report["selected"], 1)
        self.assertEqual(meta["batches"][0]["adapter"], "dsh")

    def test_reextract_cost_fills_only_missing_values(self):
        episode = write_episode(self.runs, "a", cost=None, adapter_name="openclaw-bailian",
                                result_dir=str(self.runs / "ep-a"))
        # openclaw --json leaves one indented envelope after plain log lines.
        (episode / "logs").mkdir()
        (episode / "logs" / "agent.stderr").write_text(
            "[agent] settled turn\n" + json.dumps(
                {"usage": {"input": 3884, "output": 9196, "cacheRead": 18176,
                           "cost": {"total": 0}}}, indent=2) + "\n")
        write_episode(self.runs, "b", cost={"prompt_tokens": 7, "completion_tokens": 3})
        rows, _meta = capability_report.load_rows(self.runs)
        self.assertEqual(capability_report.reextract_cost(rows), 1)
        by_id = {row["episode_id"]: row for row in rows}
        self.assertEqual(by_id["a"]["cost"]["prompt_tokens"], 3884)
        self.assertEqual(by_id["a"]["cost"]["completion_tokens"], 9196)
        self.assertEqual(by_id["b"]["cost"]["prompt_tokens"], 7)  # never overwritten
        # A re-score of cost only: the summary on disk still has no cost.
        self.assertIsNone(json.loads((episode / "summary.json").read_text())["cost"])

    def test_different_tasks_may_have_different_trees(self):
        write_episode(self.runs, "a", tree_version="sha256:aaaa")
        write_episode(self.runs, "b",
                      task_id="cae--cli--fenics--task-0001",
                      tree_version="sha256:bbbb")
        report = self._report()
        errors = [c for c in report["checks"] if c["level"] == "error"]
        self.assertEqual(errors, [])
        self.assertEqual(len(report["trees"]), 2)

    def test_render_contains_matrix_and_task_rows(self):
        write_episode(self.runs, "a")
        rows, meta = capability_report.load_rows(self.runs)
        report = capability_report.aggregate(rows, self.registry)
        text = capability_report.render_markdown(report, meta)
        self.assertIn("## Capability × solver × stack", text)
        self.assertIn("single-execution", text)
        self.assertIn("CalculiX-2.21", text)
        self.assertIn("## Per task", text)
        self.assertIn(TASK_ID, text)

    def test_short_tree(self):
        self.assertEqual(capability_report.short_tree("sha256:" + "a" * 64),
                         "sha256:aaaaaaaaaaaa…")
        self.assertEqual(capability_report.short_tree(None), "-")


if __name__ == "__main__":
    unittest.main()