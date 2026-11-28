#!/usr/bin/env python3
"""Offline tests for scripts/calibration_report.py.

No VM, no model: batch records, episode summaries and logs are written to a
temporary directory and the report is checked against them.

    python3 tests/test_calibration_report.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = _load("calibration_report", REPO / "scripts" / "calibration_report.py")

TASK = "cae--cli--fenics--task-9001"


def _tree(worktree: Path, task: str = TASK, manifest: bytes = b"manifest-v1\n") -> str:
    """Write a package manifest into the fake worktree and return its tree version."""
    domain, iface, software, name = task.split("--")
    package = worktree / "tasks" / domain / iface / software / name
    package.mkdir(parents=True, exist_ok=True)
    (package / "resources.sha256").write_bytes(manifest)
    return "sha256:" + hashlib.sha256(manifest).hexdigest()


def _episode(runs_dir: Path, batch: str, adapter: str, run: int, *, tree: str, score: float,
             basis: str = "native_evaluator", why: str = "", panic: bool = False,
             prompt: int = 1000, completion: int = 100, reasoning: int = 0,
             attempt: int = 1) -> dict:
    episode_dir = runs_dir / batch / f"ep-{adapter}-{run}-{attempt}"
    (episode_dir / "logs").mkdir(parents=True, exist_ok=True)
    summary = {
        "adapter": {"name": adapter, "version": "0"},
        "model": {"name": "model-x"},
        "active_duration_seconds": 12.5 * run,
        "tree_version": tree,
        "image_sha256": "ab" * 32,
        "cost": {"prompt_tokens": prompt, "completion_tokens": completion,
                 "reasoning_tokens": reasoning, "cache_read_tokens": 7, "llm_calls": 3},
    }
    (episode_dir / "summary.json").write_text(json.dumps(summary))
    (episode_dir / "logs" / "evaluator.stderr").write_text(
        f"debug: {why}\n" if why else "")
    (episode_dir / "logs" / "vm-console.log").write_text(
        "[   12.000000] systemd[1]: segfault at 7ffb8\nKernel panic - not syncing\n"
        if panic else "[    0.000000] Linux version 6.8\n[  120.5] foobar\n")
    return {
        "task_id": TASK, "run_index": run, "attempt": attempt, "scoring_basis": basis,
        "score": score, "error_category": None, "result_dir": str(episode_dir),
        "episode_id": episode_dir.name, "snapshot": "FEniCS", "wall_seconds": 1.0,
        "error": None,
    }


def _batch(runs_dir: Path, name: str, adapter: str, episodes: list[dict]) -> Path:
    (runs_dir / name).mkdir(parents=True, exist_ok=True)
    path = runs_dir / name / "batch.json"
    path.write_text(json.dumps({"adapter": adapter, "episodes": episodes}))
    return path


class CurrentTreeTests(unittest.TestCase):
    def test_manifest_digest_per_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            tree = _tree(worktree, TASK, b"abc\n")
            other = _tree(worktree, "cae--cli--calculix--task-0001", b"def\n")
            trees = report.current_trees(worktree)
            self.assertEqual(trees[TASK], tree)
            self.assertEqual(trees["cae--cli--calculix--task-0001"], other)
            self.assertEqual(trees[TASK], "sha256:" + hashlib.sha256(b"abc\n").hexdigest())


class CollectTests(unittest.TestCase):
    def test_episodes_off_the_current_tree_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = _tree(root / "wt")
            runs = root / "runs"
            on = _episode(runs, "b1", "dsh", 1, tree=tree, score=1.0)
            off = _episode(runs, "b1", "dsh", 2, tree="sha256:" + "0" * 64, score=0.0)
            rows, excluded = report.collect([_batch(runs, "b1", "dsh", [on, off])],
                                            report.current_trees(root / "wt"))
            self.assertEqual([r["run"] for r in rows], [1])
            self.assertEqual([r["run"] for r in excluded], [2])

    def test_without_a_worktree_everything_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            path = _batch(runs, "b1", "dsh", [_episode(runs, "b1", "dsh", 1, tree="sha256:x", score=1.0)])
            rows, excluded = report.collect([path], {})
            self.assertEqual((len(rows), len(excluded)), (1, 0))

    def test_row_fields_and_verifier_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            record = _episode(runs, "b1", "dsh", 1, tree="sha256:" + "f" * 64, score=0.0,
                              why="mesh has 12 triangles, fewer than 4000", prompt=10, completion=5,
                              reasoning=3)
            row = report.episode_row({"adapter": "dsh"}, record, "b1")
            self.assertEqual(row["adapter"], "dsh")
            self.assertEqual(row["model"], "model-x")
            self.assertEqual(row["prompt_completion"], 15)
            self.assertEqual(row["reasoning"], 3)
            self.assertEqual(row["cache_read"], 7)
            self.assertEqual(row["tree"], "f" * 12)
            self.assertEqual(row["why"], "mesh has 12 triangles, fewer than 4000")
            self.assertTrue(row["console"].startswith("clean ("))


class RenderTests(unittest.TestCase):
    def test_matrix_totals_and_panic_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = _tree(root / "wt")
            runs = root / "runs"
            episodes = [
                _episode(runs, "b1", "dsh", 1, tree=tree, score=1.0),
                _episode(runs, "b1", "dsh", 2, tree=tree, score=1.0),
                _episode(runs, "b1", "dsh", 3, tree=tree, score=1.0),
                _episode(runs, "b2", "opencode-bailian", 1, tree=tree, score=1.0),
                _episode(runs, "b2", "opencode-bailian", 2, tree=tree, score=0.0,
                         why="missing or empty artifact: mesh.msh"),
                _episode(runs, "b2", "opencode-bailian", 3, tree=tree, score=1.0),
                _episode(runs, "b3", "openclaw-bailian", 1, tree=tree, score=0.0, basis="infra"),
                _episode(runs, "b3", "openclaw-bailian", 2, tree=tree, score=0.0, panic=True),
            ]
            paths = [_batch(runs, "b1", "dsh", episodes[0:3]),
                     _batch(runs, "b2", "opencode-bailian", episodes[3:6]),
                     _batch(runs, "b3", "openclaw-bailian", episodes[6:8])]
            rows, excluded = report.collect(paths, report.current_trees(root / "wt"))
            text = report.render(rows, excluded)

        self.assertEqual(excluded, [])
        line = next(l for l in text.splitlines() if l.startswith(TASK))
        self.assertIn("n=3 mean=1.000 [1.00-1.00] infra=0", line)
        self.assertIn("n=3 mean=0.667 [0.00-1.00] infra=0", line)
        self.assertIn("n=1 mean=0.000 [0.00-0.00] infra=1", line)
        self.assertIn("verifier: missing or empty artifact: mesh.msh", text)
        self.assertIn("console PANIC:", text)
        self.assertIn("episodes with a guest panic in the console: 1 of 8", text)
        totals = next(l for l in text.splitlines()
                      if l.startswith("dsh ") and "attempts" in l)
        self.assertIn("prompt+completion      3300", totals)   # 3 x (1000 + 100)
        self.assertIn("active median 25 s", totals)            # median of 12.5, 25, 37.5
        self.assertIn(f"tree ['{tree[7:19]}']", text)

    def test_time_budget_episode_counts_as_a_scored_zero(self):
        # spec/03 section 2: an episode that used up its active time budget is
        # scored 0 on the basis active_time_budget; only infra attempts are excluded.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = _tree(root / "wt")
            runs = root / "runs"
            episodes = [
                _episode(runs, "b1", "dsh", 1, tree=tree, score=1.0),
                _episode(runs, "b1", "dsh", 2, tree=tree, score=1.0),
                _episode(runs, "b1", "dsh", 3, tree=tree, score=0.0, basis="active_time_budget"),
                _episode(runs, "b1", "dsh", 4, tree=tree, score=0.0, basis="infra"),
            ]
            rows, excluded = report.collect([_batch(runs, "b1", "dsh", episodes)], {})
            text = report.render(rows, excluded)

        line = next(l for l in text.splitlines() if l.startswith(TASK))
        self.assertIn("n=3 mean=0.667 [0.00-1.00] infra=1", line)
        self.assertIn("scored 0: the active time budget ran out", text)
        self.assertNotIn("verifier:", text)
        totals = next(l for l in text.splitlines()
                      if l.startswith("dsh ") and "attempts" in l)
        self.assertIn("attempts  4 scored  3 (time budget 1) infra  1", totals)


class CliTests(unittest.TestCase):
    def test_main_prints_the_report_and_skips_empty_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = _tree(root / "wt")
            runs = root / "runs"
            good = _batch(runs, "b1", "dsh", [_episode(runs, "b1", "dsh", 1, tree=tree, score=1.0)])
            empty = runs / "empty" / "batch.json"
            empty.parent.mkdir(parents=True)
            out, err = io.StringIO(), io.StringIO()
            sys.argv = ["calibration_report.py", "--worktree", str(root / "wt"), str(good), str(empty)]
            with redirect_stdout(out), redirect_stderr(err):
                code = report.main()
            self.assertEqual(code, 0)
            self.assertIn("n=1 mean=1.000", out.getvalue())
            self.assertIn("skip", err.getvalue())

    def test_no_episodes_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            sys.argv = ["calibration_report.py", str(Path(tmp) / "none.json")]
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = report.main()
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
