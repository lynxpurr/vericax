"""Episode lifecycle: prepare -> run -> freeze -> score -> record (spec/08 section 3).

Everything here is stack-agnostic (rule A1): per-stack behavior comes from the
adapter TOML only. Failure semantics follow spec/09 section 9 - infra failures
are recorded with ``scoring_basis="infra"`` and never presented as capability
results; capability failures go through the tier-1 verifier.
"""
from __future__ import annotations

import json
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import adapters as adapters_mod
from . import config, freeze, scoring, summary as summary_mod
from .agent_runner import run_agent, cleanup_container
from .errors import (
    EpisodeError,
    CAT_ENVIRONMENT_ERROR,
    CAT_INFRA_INCOMPLETE,
    CAT_TIME_BUDGET,
    CAT_AGENT_ERROR,
)
from .proxy import ProxyServer
from .sandbox_vm import SandboxVM, SandboxBootError

REPO = config.REPO
BOOT_TIMEOUT = 900  # spec/04: readiness window; observed boot ~177s


# ---------------------------------------------------------------- instruction
def instruction_text(task_json: dict, artifact_paths: list[str], deadline_epoch: float) -> str:
    """Task instruction plus the stack-independent sandbox contract footer.

    The footer is contract-level content (identical for every task and stack);
    it exists because no agent stack can know the vericax-sh interface without
    being told (spec/08 sections 4 and 6.4).
    """
    lines = [
        task_json["instruction"].rstrip(),
        "",
        "--- VeriCAx sandbox contract (added by the eval harness) ---",
        "Your shell runs in your own container, NOT in the engineering VM.",
        "The engineering VM is reachable only through the provided `vericax-sh` CLI:",
        "",
        "  vericax-sh run [--cwd DIR] [--timeout SEC] -- <command...>   # run a command in the VM",
        "  vericax-sh put <local-file> <remote-path>                    # copy a file into the VM",
        "  vericax-sh get <remote-path> <local-file>                    # copy a file out of the VM",
        "  vericax-sh whoami                                            # episode metadata",
        "",
        "Notes:",
        "- Every `run` starts a new shell: `cd` persists between calls, exported",
        "  environment variables do not. Use absolute paths or `--cwd`.",
        "- Your deliverables must end up INSIDE the VM at exactly these paths:",
    ]
    for path in artifact_paths:
        lines.append(f"  - {path}")
    iso = datetime.fromtimestamp(deadline_epoch, tz=timezone.utc).isoformat()
    lines += [
        f"- Hard deadline: this episode is terminated at UTC epoch {int(deadline_epoch)} ({iso}).",
        "  Finish and exit before it; termination at the deadline scores 0.",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- offline
def _verify_task_package(task_dir: Path) -> None:
    """resources.sha256 verification, reusing the packager's own hashing."""
    sys.path.insert(0, str(REPO / "scripts"))
    import pack_task  # noqa: PLC0415 - local dependency on the packaging tool

    manifest = task_dir / "resources.sha256"
    if not manifest.is_file():
        raise SystemExit(f"package has no manifest: {task_dir}")
    files = pack_task.package_files(task_dir)
    expected = manifest.read_text().strip().splitlines()
    actual = [f"{pack_task.sha256(p)}  {p.relative_to(task_dir).as_posix()}" for p in files]
    if sorted(expected) != sorted(actual):
        raise SystemExit(
            f"package manifest STALE for {task_dir.name}; run scripts/pack_task.py --task ...")


def check_task(task_id: str, adapter_spec: str | None = None) -> dict:
    """`vericax check`: offline, no VM, no model (spec/03 section 3)."""
    task_dir = _task_dir(task_id)
    task_json = _load_task(task_dir, task_id)
    _verify_task_package(task_dir)
    freeze.check_basename_uniqueness(task_json.get("artifact_paths", []))
    result = {"task_id": task_id, "manifest": "ok", "artifact_paths": "unique"}
    split_version = (task_json.get("splits") or [None])[0]
    if not split_version:
        print("check: WARNING - task declares no split (spec/10: no split, no release)")
    result["split_version"] = split_version
    snapshot = task_json.get("snapshot", "CalculiX-2.21")
    image = config.image_path(snapshot)
    result["image"] = str(image)
    if adapter_spec:
        adapter = adapters_mod.load_adapter(adapters_mod.resolve_adapter(adapter_spec))
        result["adapter"] = adapter.name
        result["container_image"] = adapter.container_image
    return result


# ---------------------------------------------------------------- helpers
def _task_dir(task_id: str) -> Path:
    domain, iface, software, task = task_id.split("--")
    return REPO / "tasks" / domain / iface / software / task


def _load_task(task_dir: Path, task_id: str) -> dict:
    path = task_dir / f"{task_dir.name}.json"
    task_json = json.loads(path.read_text())
    if task_json.get("id") != task_id:
        raise SystemExit(f"task id mismatch: {task_json.get('id')} != {task_id}")
    return task_json


def _vm_task_config(task_dir: Path, task_json: dict) -> dict:
    """Deep-copy the task config with runtime-resolved upload paths.

    The runtime resolves ``local_path`` relative to the software directory
    (the task dir's parent); mirror scripts/audit_task.py before handing the
    config to DesktopEnv.
    """
    patched = json.loads(json.dumps(task_json))
    software_dir = task_dir.parent
    for item in patched.get("config", []):
        if item.get("type") != "upload_file":
            continue
        for res in item.get("parameters", {}).get("files", []):
            res["local_path"] = str((software_dir / res["local_path"]).resolve())
    return patched


def _episode_dir(task_id: str, adapter_name: str, run_index: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    short = task_id.rsplit("--", 1)[-1]
    episode_id = f"ep-{short}-{adapter_name}-{run_index:02d}-{stamp}-{secrets.token_hex(2)}"
    return REPO / "runs" / episode_id


def _extract_cost(adapter: adapters_mod.Adapter, stdout: str) -> dict | None:
    """Data-driven cost extraction; returns spec/03 cost fields or None.

    Reads adapter.output.cost_path (a dotted path into each JSON event) and
    sums token usage across events. No stack branching happens here.
    """
    if not adapter.cost_path:
        return None
    keys = adapter.cost_path.split(".")
    totals = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
              "reasoning_tokens": 0}
    usd = 0.0
    seen = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        node: object = event
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                node = None
                break
        if not isinstance(node, dict):
            continue
        seen = True
        totals["llm_calls"] += 1
        aliases = {
            "prompt_tokens": ("input", "input_tokens", "prompt_tokens"),
            "completion_tokens": ("output", "output_tokens", "completion_tokens"),
            "reasoning_tokens": ("reasoning", "reasoning_tokens"),
        }
        for field_name, candidates in aliases.items():
            for candidate in candidates:
                value = node.get(candidate)
                if isinstance(value, (int, float)):
                    totals[field_name] += int(value)
                    break
        cost_node = node.get("cost")
        if isinstance(cost_node, dict) and isinstance(cost_node.get("total"), (int, float)):
            usd += float(cost_node["total"])
    if not seen:
        return None
    totals["usd_estimate"] = round(usd, 6) if usd else None
    return totals


# ---------------------------------------------------------------- overlay
def verify_overlay(snapshot: str) -> dict:
    """Explicit per-episode isolation verification (spec/09 section 8).

    The docker provider mounts the base qcow2 read-only and throws the boot
    container away, but the spec forbids ASSUMING overlay semantics: write a
    marker in one boot, close it, boot a fresh VM and require the marker to be
    gone, then require the base image file to be untouched.
    """
    image = config.image_path(snapshot)
    stat_before = image.stat()
    cache = REPO / "cache" / "harness" / "overlay-verify"

    vm_a = SandboxVM(snapshot, cache_dir=cache / "a")
    vm_a.boot(None)
    vm_a.wait_healthy()
    vm_a.bash("echo vericax-overlay-marker > /home/user/Desktop/.vcax_marker", timeout=60)
    written = vm_a.bash("cat /home/user/Desktop/.vcax_marker", timeout=60)
    vm_a.close()

    vm_b = SandboxVM(snapshot, cache_dir=cache / "b")
    vm_b.boot(None)
    vm_b.wait_healthy()
    probe = vm_b.bash("cat /home/user/Desktop/.vcax_marker 2>/dev/null || echo ABSENT",
                      timeout=60)
    vm_b.close()

    stat_after = image.stat()
    marker_persisted = "vericax-overlay-marker" in probe.get("output", "")
    image_unchanged = (stat_before.st_size == stat_after.st_size
                       and stat_before.st_mtime_ns == stat_after.st_mtime_ns)
    return {
        "snapshot": snapshot,
        "marker_written": "vericax-overlay-marker" in written.get("output", ""),
        "marker_persisted_after_reboot": marker_persisted,   # must be False
        "base_image_unchanged": image_unchanged,             # must be True
        "verdict": "pass" if (not marker_persisted and image_unchanged) else "FAIL",
    }


# ---------------------------------------------------------------- smoke
def smoke(task_id: str) -> dict:
    """`vericax smoke`: boot the VM, inject init, screenshot, verify - no model."""
    task_dir = _task_dir(task_id)
    task_json = _load_task(task_dir, task_id)
    snapshot = task_json.get("snapshot", "CalculiX-2.21")
    out_dir = REPO / "runs" / f"smoke-{task_id.rsplit('--', 1)[-1]}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    vm = SandboxVM(snapshot, cache_dir=out_dir / "cache")
    report: dict = {"task_id": task_id, "output_dir": str(out_dir)}
    try:
        vm.boot(_vm_task_config(task_dir, task_json))
        isolated = vm.remove_default_route()
        report["network_isolated"] = isolated
        for item in task_json.get("config", []):
            if item.get("type") != "upload_file":
                continue
            for file_item in item.get("parameters", {}).get("files", []):
                remote = file_item["path"]
                probe = vm.bash(f"test -f {remote} && echo present || echo missing", timeout=60)
                report[remote] = probe["output"].strip()
        screenshot = vm._env.controller.get_screenshot()
        if screenshot:
            (out_dir / "screenshot.png").write_bytes(screenshot)
            report["screenshot"] = str(out_dir / "screenshot.png")
    finally:
        vm.close()
    return report


# ---------------------------------------------------------------- episode
def run_episode(
    task_id: str,
    adapter_spec: str,
    run_index: int = 1,
    run_total: int = 1,
    time_limit: int | None = None,
    payload_dir: Path | None = None,
    do_score: bool = True,
) -> tuple[dict, Path]:
    """One full episode. Returns (summary_dict, episode_dir)."""
    task_dir = _task_dir(task_id)
    task_json = _load_task(task_dir, task_id)
    _verify_task_package(task_dir)
    adapter = adapters_mod.load_adapter(adapters_mod.resolve_adapter(adapter_spec))
    artifact_paths = task_json.get("artifact_paths", [])
    freeze.check_basename_uniqueness(artifact_paths)

    snapshot = task_json.get("snapshot", "CalculiX-2.21")
    image_path = config.image_path(snapshot)
    image_sha = config.image_sha256(image_path)

    episode_dir = _episode_dir(task_id, adapter.name, run_index)
    episode_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = episode_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    container_name = f"vericax-agent-{episode_dir.name}"

    task_limit = task_json.get("limits", {}).get("active_time_seconds")
    effective_limit = time_limit or task_limit or 18000
    deadline_epoch = time.time() + effective_limit

    inst_path = episode_dir / "instruction.md"
    inst_path.write_text(instruction_text(task_json, artifact_paths, deadline_epoch))

    wall_started = time.monotonic()
    vm: SandboxVM | None = None
    proxy: ProxyServer | None = None
    error_category: str | None = None
    error_detail: str | None = None
    score: float | None = None
    basis = summary_mod.SCORING_BASIS_INFRA
    native_executed = False
    score_result: scoring.ScoreResult | None = None
    agent_result = None
    manifest: dict | None = None
    sandbox_isolated: bool | None = None
    boot_attempts = 0

    try:
        # ---- prepare: sandbox boot (one retry, spec/09 section 8)
        while True:
            boot_attempts += 1
            vm = SandboxVM(snapshot, cache_dir=episode_dir / "cache")
            try:
                vm.boot(_vm_task_config(task_dir, task_json))
                break
            except SandboxBootError as exc:
                vm.close()
                vm = None
                if boot_attempts >= 2:
                    raise EpisodeError(CAT_ENVIRONMENT_ERROR, f"VM boot failed twice: {exc}",
                                       scored=False) from exc
                print("run: VM boot failed; retrying once (spec/09 section 8)")
        sandbox_isolated, sandbox_isolation_detail = vm.isolate_network()
        vm.wait_healthy()
        (logs_dir / "network_isolation.json").write_text(json.dumps({
            "sandbox": {"isolated": sandbox_isolated, "detail": sandbox_isolation_detail},
        }, indent=2) + "\n")
        (logs_dir / "vm_processes_before.txt").write_text(vm.process_snapshot())

        # ---- proxy up (auth: Unix socket + per-episode token, T3)
        token = secrets.token_hex(24)
        proxy = ProxyServer(
            vm, episode_dir / "proxy" / "proxy.sock", token, episode_dir.name,
            workdir=adapter.working_dir, log_dir=logs_dir,
            default_timeout=120)
        try:
            proxy.start()
        except Exception as exc:  # noqa: BLE001
            raise EpisodeError(CAT_INFRA_INCOMPLETE, f"proxy start failed: {exc}",
                               scored=False) from exc

        # ---- agent container up
        command, needs_stdin = adapters_mod.build_command(adapter, inst_path.read_text())
        mounts = adapters_mod.prepare_state_seed(adapter, episode_dir)
        mounts[str(inst_path)] = {"bind": adapters_mod.CONTAINER_INSTRUCTION_PATH, "mode": "ro"}
        if payload_dir:
            mounts[str(payload_dir)] = {"bind": adapters_mod.CONTAINER_PAYLOAD_DIR, "mode": "ro"}
        mounts[str(episode_dir / "proxy" / "proxy.sock")] = {
            "bind": "/run/vericax/proxy.sock", "mode": "rw"}
        env = adapters_mod.container_env(adapter, {
            "VERICAX_TASK_ID": task_id,
            "VERICAX_EPISODE_ID": episode_dir.name,
            "VERICAX_RUN_INDEX": str(run_index),
            "VERICAX_INSTRUCTION": adapters_mod.CONTAINER_INSTRUCTION_PATH,
            "VERICAX_SANDBOX_TOKEN": token,
            "VERICAX_DEADLINE_EPOCH": str(int(deadline_epoch)),
            "VERICAX_WORKDIR": adapter.working_dir,
            "VERICAX_ARTIFACTS": json.dumps(artifact_paths),
        })
        (logs_dir / "launch.json").write_text(json.dumps({
            "adapter": adapter.name, "command": command, "image": adapter.container_image,
        }, indent=2) + "\n")

        agent_result = run_agent(
            image=adapter.container_image,
            command=command,
            env=env,
            mounts=mounts,
            container_name=container_name,
            deadline_epoch=deadline_epoch,
            grace_seconds=adapter.grace_seconds,
            stdin_bytes=inst_path.read_bytes() if needs_stdin else None,
        )
        (logs_dir / "agent.stdout").write_text(agent_result.stdout)
        (logs_dir / "agent.stderr").write_text(agent_result.stderr)
        (logs_dir / "agent-container.json").write_text(json.dumps({
            "exit_code": agent_result.exit_code,
            "killed_by_deadline": agent_result.killed_by_deadline,
            "duration_seconds": agent_result.duration_seconds,
            "container": agent_result.container,
        }, indent=2) + "\n")

        # ---- freeze (agent already dead; proxy entry closes first, E5)
        if proxy is not None:
            proxy.stop()
            proxy = None
        manifest = freeze.freeze(
            vm, artifact_paths, episode_dir, image_sha, task_id, episode_dir.name)

        # ---- termination semantics (spec/08 section 7)
        if agent_result.killed_by_deadline:
            error_category = CAT_TIME_BUDGET
            error_detail = f"deadline hit after {agent_result.duration_seconds:.0f}s"
            score = 0.0
            basis = summary_mod.SCORING_BASIS_TIME_BUDGET
        else:
            if agent_result.exit_code not in (0, None):
                error_category = CAT_AGENT_ERROR
                error_detail = f"exit_nonzero:{agent_result.exit_code}"
            if do_score:
                score_result = scoring.run_scoring(
                    task_dir=task_dir,
                    evaluator_func=task_json.get("evaluator", {}).get("func", "exact_match"),
                    frozen_artifacts_dir=episode_dir / "artifacts",
                    snapshot=snapshot,
                    cache_dir=episode_dir / "scoring-cache",
                )
                (logs_dir / "evaluator.stdout").write_text(
                    score_result.logs.get("evaluator_stdout", ""))
                (logs_dir / "evaluator.stderr").write_text(
                    score_result.logs.get("evaluator_stderr", ""))
                native_executed = score_result.native_executed and not score_result.infra
                if score_result.infra:
                    raise EpisodeError(CAT_INFRA_INCOMPLETE,
                                       f"tier-1 scoring failed: {score_result.detail}",
                                       scored=False)
                score = score_result.score
                basis = summary_mod.SCORING_BASIS_NATIVE

    except EpisodeError as exc:
        error_category = exc.category
        error_detail = exc.detail
        if not exc.scored:
            score, basis, native_executed = 0.0, summary_mod.SCORING_BASIS_INFRA, False
    except Exception as exc:  # noqa: BLE001 - an episode always leaves a record (spec/09 section 9)
        error_category = CAT_INFRA_INCOMPLETE
        error_detail = f"unexpected: {type(exc).__name__}: {exc}"
        score, basis, native_executed = 0.0, summary_mod.SCORING_BASIS_INFRA, False
    finally:
        if proxy is not None:
            proxy.stop()
        if vm is not None:
            (logs_dir / "vm_processes_after.txt").write_text(vm.process_snapshot())
            vm.close()
        cleanup_container(container_name)

    wall = time.monotonic() - wall_started
    cost = _extract_cost(adapter, agent_result.stdout) if agent_result else None
    split_version = (task_json.get("splits") or [None])[0]

    summary = summary_mod.build_summary(
        task_id=task_id,
        episode_id=episode_dir.name,
        run_index=run_index,
        run_total=run_total,
        agent={"name": adapter.name, "version": adapter.version},
        harness={"name": adapter.name, "version": adapter.version},
        model={"name": adapter.model_name, "endpoint": adapter.model_endpoint},
        score=score,
        scoring_basis=basis,
        native_evaluator_executed=native_executed,
        error=error_detail,
        error_category=error_category,
        result_dir=str(episode_dir),
        artifact_uri=str(episode_dir / "artifacts" / "artifacts.json") if manifest else None,
        cost=cost,
        wall_duration_seconds=wall,
        active_duration_seconds=agent_result.duration_seconds if agent_result else 0.0,
        active_time_limit_seconds=effective_limit,
        split_version=split_version,
        image_sha256=image_sha,
        verifier_sha256=score_result.verifier_sha256 if score_result else None,
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        solver_version=score_result.solver_version if score_result else None,
        agent_exit_code=agent_result.exit_code if agent_result else None,
        killed_by_deadline=agent_result.killed_by_deadline if agent_result else False,
        deadline_epoch=int(deadline_epoch),
        sandbox_network_isolated=sandbox_isolated,
        scoring_network_isolated=score_result.network_isolated if score_result else None,
    )
    summary_path = summary_mod.write_summary(episode_dir, summary)
    print(f"run: episode {episode_dir.name} recorded -> {summary_path}")
    return summary, episode_dir


# ---------------------------------------------------------------- report
def report(runs_dir: Path | None = None) -> str:
    """Aggregate all summary.json files into a capability matrix (Phase 1)."""
    runs_dir = Path(runs_dir or REPO / "runs")
    rows = []
    for path in sorted(runs_dir.glob("ep-*/summary.json")):
        data = json.loads(path.read_text())
        rows.append(data)
    if not rows:
        return "report: no episodes recorded yet"
    lines = [
        "task | adapter | model | n | mean | min | max | errors | basis",
        "---|---|---|---|---|---|---|---|---",
    ]
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["task_id"], row["agent"]["name"],
               (row.get("model") or {}).get("name") or "-")
        groups.setdefault(key, []).append(row)
    for (task, agent, model), items in sorted(groups.items()):
        scored = [it["score"] for it in items
                  if it["scoring_basis"] == summary_mod.SCORING_BASIS_NATIVE]
        errors = sum(1 for it in items if it["error_category"])
        n_scored = len(scored)
        mean = sum(scored) / n_scored if n_scored else None
        lines.append(
            f"{task} | {agent} | {model} | {n_scored}/{len(items)} | "
            f"{mean if mean is not None else '-'} | "
            f"{min(scored) if scored else '-'} | {max(scored) if scored else '-'} | "
            f"{errors} | {items[0]['scoring_basis']}")
    text = "\n".join(lines) + "\n"
    print(text)
    return text
