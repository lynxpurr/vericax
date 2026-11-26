#!/usr/bin/env python3
"""Offline tests for the sandbox-loss and batch reliability rules (2026-11-26).

No VM, no model, no docker: a fake control plane and a fake docker client stand
in for the runtime.

    python3 tests/test_runtime_reliability.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from vericax import batch, host, lifecycle, proxy, summary as summary_mod  # noqa: E402
from vericax.agent_runner import AgentResult, run_agent  # noqa: E402
from vericax.sandbox_vm import SandboxUnavailable, SandboxVM  # noqa: E402

TASK_ID = "cae--cli--calculix--task-0001"


def _request(sock_path: Path, payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(20)
        client.connect(str(sock_path))
        client.sendall(json.dumps({"token": "tok", **payload}).encode() + b"\n")
        with client.makefile("rb") as fh:
            return json.loads(fh.readline())


class FakeVM:
    """Answers control-plane calls until ``dead`` is set."""

    def __init__(self):
        self.dead = False
        self.calls = 0

    def bash(self, script, timeout=120, cwd=None):
        self.calls += 1
        if self.dead:
            raise SandboxUnavailable("[run_bash_script] still failing after 90s")
        return {"returncode": 0, "output": "vericax-ok" if "vericax-ok" in script else ""}

    def get(self, path):
        return b""


class ProxyLossTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self._tmp.name)
        self.vm = FakeVM()
        self._patches = [
            mock.patch.object(proxy, "LOSS_WINDOW_WAIT", 0.05),
            mock.patch.object(proxy, "LOSS_PROBE_TIMEOUT", 1.0),
        ]
        for item in self._patches:
            item.start()
        self.server = proxy.ProxyServer(
            self.vm, self.logs / "p.sock", "tok", "ep", "/home/user/Desktop",
            log_dir=self.logs)
        self.server.start()

    def tearDown(self):
        self.server.stop()
        for item in reversed(self._patches):
            item.stop()
        self._tmp.cleanup()

    def test_loss_check_budget_is_under_a_minute(self):
        # B2 agents kept running 10-27 min against dead VMs; the check must
        # confirm a loss well inside one minute after the first error.
        self.assertLess(proxy.LOSS_WINDOW_WAIT + proxy.LOSS_PROBE_TIMEOUT, 60)

    def test_lost_sandbox_sets_the_event_and_stops_touching_the_vm(self):
        self.vm.dead = True
        first = _request(self.logs / "p.sock", {"v": "run", "cmd": "ls"})
        self.assertEqual(first["error"], "sandbox_unavailable")
        self.assertTrue(self.server.loss_event.wait(5))
        calls_after_loss = self.vm.calls

        again = _request(self.logs / "p.sock", {"v": "run", "cmd": "ls"})
        self.assertEqual(again["error"], "sandbox_unavailable")
        self.assertTrue(again["lost"])
        self.assertEqual(self.vm.calls, calls_after_loss)
        self.assertEqual(self.server.loss_info["first_error"]["verb"], "run")
        self.assertIn('"verb": "sandbox_lost"', (self.logs / "commands.jsonl").read_text())

    def test_a_single_failure_that_recovers_is_not_a_loss(self):
        class FlakyVM(FakeVM):
            def bash(self, script, timeout=120, cwd=None):
                self.calls += 1
                if self.calls == 1:
                    raise SandboxUnavailable("[run_bash_script] still failing after 90s")
                return {"returncode": 0, "output": "vericax-ok"}

        self.server._vm = FlakyVM()
        first = _request(self.logs / "p.sock", {"v": "run", "cmd": "ls"})
        self.assertEqual(first["error"], "sandbox_unavailable")
        time.sleep(0.5)  # past the check window: the probe found a healthy VM
        self.assertFalse(self.server.sandbox_lost)
        self.assertTrue(_request(self.logs / "p.sock", {"v": "run", "cmd": "ls"})["ok"])

    def test_a_command_timeout_is_not_a_sandbox_error(self):
        class SlowVM(FakeVM):
            def bash(self, script, timeout=120, cwd=None):
                raise type("SandboxCommandTimeout", (Exception,), {})("hard timeout")

        self.server._vm = SlowVM()
        response = _request(self.logs / "p.sock", {"v": "run", "cmd": "sleep 999"})
        self.assertEqual(response["error"], "timeout")
        time.sleep(0.3)
        self.assertFalse(self.server.sandbox_lost)


class _FakeContainer:
    def __init__(self):
        self.status = "running"
        self.name = "vericax-agent-test"

    def reload(self):
        pass

    def stop(self, timeout=None):
        self.status = "exited"

    def kill(self):
        self.status = "exited"

    def wait(self, timeout=None):
        return {"StatusCode": 137}

    def logs(self, **kwargs):
        return b""

    def remove(self, force=False):
        self.status = "removed"


def _fake_docker(container):
    containers = types.SimpleNamespace(
        run=lambda *args, **kwargs: container,
        get=lambda name: container)
    client = types.SimpleNamespace(containers=containers)
    return types.SimpleNamespace(from_env=lambda timeout=None: client)


class AgentAbortTests(unittest.TestCase):
    def test_abort_event_stops_the_agent_long_before_the_deadline(self):
        container = _FakeContainer()
        abort = threading.Event()
        threading.Timer(0.2, abort.set).start()
        started = time.monotonic()
        with mock.patch.dict(sys.modules, {"docker": _fake_docker(container)}):
            result = run_agent(
                image="img", command=["sleep", "3600"], env={}, mounts={},
                container_name="vericax-agent-test",
                deadline_epoch=time.time() + 600, grace_seconds=1, abort_event=abort)
        self.assertTrue(result.aborted)
        self.assertFalse(result.killed_by_deadline)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(container.status, "removed")

    def test_deadline_path_is_unchanged(self):
        container = _FakeContainer()
        with mock.patch.dict(sys.modules, {"docker": _fake_docker(container)}):
            result = run_agent(
                image="img", command=["sleep", "3600"], env={}, mounts={},
                container_name="vericax-agent-test",
                deadline_epoch=time.time() - 1, grace_seconds=1)
        self.assertTrue(result.killed_by_deadline)
        self.assertFalse(result.aborted)


class _FakeSandboxVM:
    def __init__(self, snapshot, cache_dir, image_override=None):
        pass

    def boot(self, task_config):
        pass

    def isolate_network(self):
        return True, "fake"

    def wait_healthy(self, timeout_s=180):
        return True

    def process_snapshot(self):
        return "fake"

    def bash(self, script, timeout=120, cwd=None):
        return {"returncode": 0, "output": "fake guest profile"}

    def container_state(self, log_tail=0):
        return {"name": "vm-ctr", "status": "running"}

    def console_log(self, max_bytes=2_000_000):
        return "fake guest console"

    def close(self):
        return True


class _FakeProxy:
    lost = False

    def __init__(self, vm, socket_path, token, episode_id, workdir, log_dir, default_timeout=120):
        self.loss_event = threading.Event()
        self.loss_info = None
        if self.lost:
            self.loss_info = {"first_error": {"verb": "run", "error": "SandboxUnavailable"}}
            self.loss_event.set()

    @property
    def sandbox_lost(self):
        return self.lost

    def start(self):
        pass

    def stop(self):
        pass


class _AbortedAgent:
    def __call__(self, **kwargs):
        assert kwargs["abort_event"] is not None, "the agent must be told about a loss"
        return AgentResult(exit_code=137, aborted=True, duration_seconds=12.0,
                           container="vericax-agent-test")


class EpisodeLossTests(unittest.TestCase):
    """The wiring in run_episode: a loss means infra, evidence, and no freeze."""

    def setUp(self):
        self.episode_dirs: list[Path] = []
        self.addCleanup(
            lambda: [shutil.rmtree(path, ignore_errors=True) for path in self.episode_dirs])

    def _run(self, **kwargs):
        with mock.patch.object(lifecycle, "SandboxVM", _FakeSandboxVM), \
                mock.patch.object(lifecycle, "ProxyServer", _FakeProxy), \
                mock.patch.object(lifecycle, "run_agent", _AbortedAgent()), \
                mock.patch.object(lifecycle, "cleanup_container", lambda name: None), \
                mock.patch.object(lifecycle.config, "image_path",
                                  lambda *args, **options: Path("/nonexistent.qcow2")), \
                mock.patch.object(lifecycle.config, "image_sha256",
                                  lambda *args, **options: "sha256:x"), \
                mock.patch.object(lifecycle.freeze, "freeze",
                                  mock.Mock(side_effect=SandboxUnavailable(
                                      "[run_bash_script] still failing after 90s"))), \
                redirect_stdout(io.StringIO()):
            result, episode_dir = lifecycle.run_episode(TASK_ID, "fake", kind="test", **kwargs)
        self.episode_dirs.append(episode_dir)
        return result, episode_dir

    def test_loss_during_the_run_is_infra_with_evidence(self):
        _FakeProxy.lost = True
        try:
            summary, episode_dir = self._run()
        finally:
            _FakeProxy.lost = False
        self.assertEqual(summary["scoring_basis"], summary_mod.SCORING_BASIS_INFRA)
        self.assertEqual(summary["error_category"], "infra_incomplete")
        self.assertIn("sandbox lost during the run", summary["error"])
        self.assertIsNone(summary["artifact_uri"])  # nothing was frozen
        record = json.loads((episode_dir / "logs" / "sandbox-loss.json").read_text())
        self.assertEqual(record["stage"], "run")
        self.assertEqual(record["task_id"], TASK_ID)
        self.assertTrue(record["agent"]["aborted"])
        self.assertEqual(record["vm_container"]["name"], "vm-ctr")
        self.assertIn("memory_mb", record["host"])
        self.assertIn("vm_processes", record)
        # The guest console is the only place a guest-side crash shows up,
        # and the container is gone once the episode ends.
        self.assertEqual((episode_dir / "logs" / "vm-console.log").read_text(),
                         "fake guest console")
        self.assertEqual((episode_dir / "logs" / "guest-profile.txt").read_text(),
                         "fake guest profile")

    def test_unavailable_at_freeze_is_infra_not_a_capability_zero(self):
        summary, episode_dir = self._run()
        self.assertEqual(summary["scoring_basis"], summary_mod.SCORING_BASIS_INFRA)
        self.assertIn("freeze failed, sandbox unavailable", summary["error"])
        record = json.loads((episode_dir / "logs" / "sandbox-loss.json").read_text())
        self.assertEqual(record["stage"], "freeze")
        self.assertTrue((episode_dir / "logs" / "vm-console.log").is_file())


class _NotFound(Exception):
    pass


class _APIError(Exception):
    pass


def _vm_with(container):
    vm = SandboxVM.__new__(SandboxVM)  # __init__ resolves a real image
    vm._env = types.SimpleNamespace(
        provider=types.SimpleNamespace(container=container), close=lambda: None)
    return vm


class ContainerReleaseTests(unittest.TestCase):
    def test_a_container_removed_by_the_runtime_is_confirmed_gone(self):
        container = types.SimpleNamespace(
            reload=mock.Mock(side_effect=_NotFound("gone")), name="vm-a")
        self.assertTrue(_vm_with(container).close())

    def test_a_failed_removal_is_retried(self):
        container = types.SimpleNamespace(name="vm-b")
        container.reload = mock.Mock(side_effect=[None, None, _NotFound("gone")])
        container.status = "running"
        container.remove = mock.Mock(side_effect=[_APIError("daemon busy"), None])
        with mock.patch.object(batch.time, "sleep"):
            self.assertTrue(_vm_with(container).close())
        self.assertEqual(container.remove.call_count, 2)

    def test_a_survivor_is_reported_not_skipped(self):
        container = types.SimpleNamespace(name="vm-c", status="running")
        container.reload = mock.Mock(return_value=None)
        container.remove = mock.Mock(side_effect=_APIError("daemon busy"))
        with mock.patch.object(batch.time, "sleep"):
            vm = _vm_with(container)
            self.assertFalse(vm.close())
        self.assertEqual(vm.surviving_container, "vm-c")

    def test_no_container_to_release(self):
        vm = SandboxVM.__new__(SandboxVM)
        vm._env = types.SimpleNamespace(provider=types.SimpleNamespace(container=None),
                                        close=lambda: None)
        self.assertTrue(vm.close())


class HostInventoryTests(unittest.TestCase):
    def setUp(self):
        self.images = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.images, ignore_errors=True)

    @staticmethod
    def _attrs(source: str | None):
        mounts = [] if source is None else [{
            "Type": "bind", "Source": source, "Destination": "/System.qcow2"}]
        return {"Name": "/vm", "Config": {"Image": "osworld-docker"},
                "Created": "2026-11-23T13:50:09Z", "Mounts": mounts}

    def test_only_vericax_images_are_claimed(self):
        ours = self.images / "CalculiX-2.21.qcow2"
        self.assertTrue(host.is_vericax_vm(self._attrs(str(ours)), self.images))
        other = self.images.parent / "engiworld-playground" / "CalculiX-2.21.qcow2"
        self.assertFalse(host.is_vericax_vm(self._attrs(str(other)), self.images))
        override = "/data/VeriCAx-merged.qcow2"
        self.assertTrue(host.is_vericax_vm(self._attrs(override), self.images,
                                           {override}))
        self.assertFalse(host.is_vericax_vm(self._attrs(None), self.images))

    def test_running_vericax_vms_are_listed_with_their_creation_time(self):
        containers = [
            types.SimpleNamespace(attrs=self._attrs(str(self.images / "FEniCS.qcow2"))),
            types.SimpleNamespace(attrs=self._attrs("/elsewhere/a.qcow2")),
        ]
        client = types.SimpleNamespace(
            containers=types.SimpleNamespace(list=lambda: containers))
        found = host.vericax_vm_containers(self.images, client=client)
        self.assertTrue(found["ok"])
        self.assertEqual([item["name"] for item in found["containers"]], ["vm"])

    def test_an_unreachable_daemon_is_reported(self):
        client = types.SimpleNamespace(containers=types.SimpleNamespace(
            list=mock.Mock(side_effect=_APIError("connection refused"))))
        found = host.vericax_vm_containers(self.images, client=client)
        self.assertFalse(found["ok"])
        self.assertIn("connection refused", found["error"])

    def test_evidence_never_records_argv(self):
        record = host.sandbox_loss_record(
            episode_id="ep", task_id="t", adapter="dsh", stage="run", detail="x",
            proxy=None, agent={"aborted": True}, vm_state=None)
        self.assertNotIn("argv", json.dumps(record))
        for row in record["host"]["top_processes"]:
            self.assertLessEqual(set(row), {"pid", "name", "rss_mb"})
        self.assertEqual(record["vm_processes"], [])

    def test_process_tree_starts_at_the_root_and_carries_the_peak(self):
        rows = host.process_tree(os.getpid())
        self.assertEqual(rows[0]["pid"], os.getpid())
        for row in rows:
            self.assertLessEqual(set(row), {
                "pid", "name", "state", "rss_mb", "peak_mb", "threads", "cpu_seconds"})
        # A process that cannot be read yields nothing, never an exception.
        self.assertEqual(host.process_tree(2 ** 22 + 12345), [])

    def test_cgroup_memory_is_read_or_absent(self):
        value = host.cgroup_memory(os.getpid())
        self.assertTrue(value is None or "memory.events" in value or "memory.current" in value)


class MemoryGateTests(unittest.TestCase):
    def test_a_launch_waits_until_memory_frees_up(self):
        readings = iter([1000, 1000, 20000])
        with mock.patch.object(host, "mem_available_mb", side_effect=lambda: next(readings)), \
                redirect_stdout(io.StringIO()):
            self.assertTrue(batch._wait_for_memory(6144, wait_seconds=5, poll=0.05))

    def test_a_launch_gives_up_after_the_wait(self):
        with mock.patch.object(host, "mem_available_mb", return_value=1000), \
                redirect_stdout(io.StringIO()):
            self.assertFalse(batch._wait_for_memory(6144, wait_seconds=0.1, poll=0.05))

    def test_the_gate_can_be_disabled(self):
        with mock.patch.object(host, "mem_available_mb", return_value=1):
            self.assertTrue(batch._wait_for_memory(0, wait_seconds=0))


def _native(score=1.0):
    return {"episode_id": "ep", "score": score,
            "scoring_basis": summary_mod.SCORING_BASIS_NATIVE,
            "error_category": None, "error": None, "result_dir": "/tmp/ep"}


_INFRA = {"episode_id": "ep", "score": 0.0, "scoring_basis": summary_mod.SCORING_BASIS_INFRA,
          "error_category": "infra_incomplete", "error": "sandbox lost",
          "result_dir": "/tmp/ep"}


class BatchReliabilityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.outcomes: dict[tuple[int, int], object] = {}
        self.default = _native()
        self.calls: list[tuple[int, int]] = []
        no_vms = {"ok": True, "containers": [], "error": None}
        patches = [
            mock.patch.object(batch.lifecycle, "run_episode", self._run_episode),
            mock.patch.object(batch, "preflight", return_value={"adapter": "fake", "images": {}}),
            mock.patch.object(batch, "_snapshot_for", return_value="CalculiX-2.21"),
            mock.patch.object(batch.host, "vericax_vm_containers", return_value=no_vms),
            mock.patch.object(batch.config, "REPO", self.root),
        ]
        self._patches = patches
        for item in patches:
            item.start()

    def tearDown(self):
        for item in reversed(self._patches):
            item.stop()
        self._tmp.cleanup()

    def _run_episode(self, *, task_id, run_index, **kwargs):
        # Every attempt is a new episode; the scheduler does not pass a number.
        attempt = 1 + sum(1 for index, _ in self.calls if index == run_index)
        self.calls.append((run_index, attempt))
        outcome = self.outcomes.get((run_index, attempt), self.default)
        if isinstance(outcome, BaseException):
            raise outcome
        summary = dict(outcome)
        summary["episode_id"] = f"ep-{run_index}-{attempt}"
        return summary, self.root / summary["episode_id"]

    def _batch(self, runs=3, **kwargs):
        kwargs.setdefault("retry_cooldown", 0)
        kwargs.setdefault("min_free_mb", 0)
        with redirect_stdout(io.StringIO()):
            return batch.run_batch([TASK_ID], "fake", runs=runs, parallel=1, **kwargs)

    def test_an_infra_job_is_retried_with_a_new_episode(self):
        self.outcomes[(2, 1)] = _INFRA
        payload = self._batch()
        self.assertEqual(payload["verdict"], "pass_after_retry")
        self.assertEqual(payload["attempts"], 4)
        self.assertEqual(payload["retried_jobs"], 1)
        self.assertEqual(payload["infra_attempts"], 1)
        attempts = {row["attempt"]: row for row in payload["episodes"] if row["run_index"] == 2}
        self.assertEqual(attempts[1]["scoring_basis"], "infra")
        self.assertEqual(attempts[2]["scoring_basis"], "native_evaluator")
        self.assertNotEqual(attempts[1]["episode_id"], attempts[2]["episode_id"])

    def test_a_native_zero_is_never_retried(self):
        for index in (1, 2, 3):
            self.outcomes[(index, 1)] = _native(0.0)
        payload = self._batch()
        self.assertEqual(payload["verdict"], "pass")
        self.assertEqual(payload["attempts"], 3)
        self.assertEqual(payload["retried_jobs"], 0)

    def test_retries_are_capped_per_job(self):
        for attempt in (1, 2, 3):
            self.outcomes[(1, attempt)] = _INFRA
        payload = self._batch()
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["attempts"], 5)
        self.assertEqual(payload["infra_failures"], 1)

    def test_retries_can_be_disabled(self):
        self.outcomes[(1, 1)] = _INFRA
        payload = self._batch(infra_retries=0)
        self.assertEqual(payload["attempts"], 3)
        self.assertEqual(payload["verdict"], "FAIL")

    def test_three_infra_results_in_a_row_stop_the_batch(self):
        self.default = _INFRA
        payload = self._batch(runs=6)
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["stopped"], "infra_breaker")
        self.assertEqual(len(self.calls), 3)
        skipped = [row for row in payload["episodes"] if row.get("skipped")]
        self.assertEqual([row["run_index"] for row in skipped], [4, 5, 6])
        self.assertTrue(all(row["skipped"] == "infra_breaker" for row in skipped))

    def test_the_breaker_can_be_disabled(self):
        self.default = _INFRA
        payload = self._batch(runs=4, infra_breaker=0, infra_retries=0)
        self.assertIsNone(payload["stopped"])
        self.assertEqual(len(self.calls), 4)

    def test_a_configuration_error_is_not_retried_as_infra(self):
        self.outcomes[(1, 1)] = SystemExit("package manifest STALE")
        payload = self._batch()
        self.assertEqual(payload["stopped"], "error: package manifest STALE")
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(any(batch.is_infra(row) for row in payload["episodes"]))
        self.assertTrue(all(row["attempt"] == 1 for row in payload["episodes"]))

    def test_leftover_and_leaked_vms_are_reported(self):
        leftover = {"name": "old", "image": "osworld-docker", "created": "2026-11-23"}
        leaked = {"name": "new", "image": "osworld-docker", "created": "2026-11-26"}
        with mock.patch.object(batch.host, "vericax_vm_containers", side_effect=[
                {"ok": True, "containers": [leftover], "error": None},
                {"ok": True, "containers": [leftover, leaked], "error": None}]):
            payload = self._batch()
        self.assertEqual(payload["preflight"]["leftover_vms"], [leftover])
        self.assertEqual(payload["leaked_vms"], [leaked])

    def test_the_memory_gate_stops_the_batch_instead_of_launching(self):
        with mock.patch.object(host, "mem_available_mb", return_value=1000):
            payload = self._batch(min_free_mb=6144, memory_wait=0)
        self.assertEqual(payload["stopped"], "memory_gate")
        self.assertEqual(self.calls, [])
        self.assertEqual(payload["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
