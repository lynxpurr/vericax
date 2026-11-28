"""Episode lifecycle: prepare -> run -> freeze -> score -> record (spec/08 section 3).

Everything here is stack-agnostic (rule A1): per-stack behavior comes from the
adapter TOML only. Failure semantics follow spec/09 section 9 - infra failures
are recorded with ``scoring_basis="infra"`` and never presented as capability
results; capability failures go through the tier-1 verifier.
"""
from __future__ import annotations

import importlib.util
import json
import secrets
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import adapters as adapters_mod
from . import config, freeze, host, scoring, summary as summary_mod, validity
from .agent_runner import run_agent, cleanup_container
from .errors import (
    EpisodeError,
    CAT_ENVIRONMENT_ERROR,
    CAT_INFRA_INCOMPLETE,
    CAT_TIME_BUDGET,
    CAT_AGENT_ERROR,
)
from .proxy import ProxyServer, temp_socket_path
from .sandbox_vm import SandboxBootError, SandboxUnavailable, SandboxVM

REPO = config.REPO
BOOT_TIMEOUT = 900  # spec/04: readiness window; observed boot ~177s


# ---------------------------------------------------------------- instruction
def instruction_text(task_json: dict, artifact_paths: list[str], deadline_epoch: float,
                     challenge: str | None = None) -> str:
    """Task instruction plus the stack-independent sandbox contract footer.

    The footer is contract-level content (identical for every task and stack);
    it exists because no agent stack can know the vericax-sh interface without
    being told (spec/08 sections 4 and 6.4).

    L6 tasks put ``{challenge}`` where the episode-specific set/group name
    belongs (spec/02 L6.3). The token is rendered here so every run of the
    same package binds its own label; the audit/L0 path passes no token and
    keeps the task's fixed ``provenance.challenge`` value.
    """
    if "{challenge}" in task_json["instruction"]:
        if not challenge:
            raise SystemExit("task instruction needs {challenge} but no episode token was generated")
        instruction = task_json["instruction"].replace("{challenge}", challenge)
    else:
        instruction = task_json["instruction"]
        if challenge:
            # Backward-compatible fallback for a package that predates the
            # placeholder: append an explicit binding paragraph. New L6
            # packages use the placeholder and do not hit this branch.
            instruction = instruction.rstrip() + (
                f"\n\nEpisode challenge token: use `{challenge}` wherever this task "
                "names a challenge set/group.")
    lines = [
        instruction.rstrip(),
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
        # Bootstrap: a brand-new task has neither manifest nor L0 record, and
        # the pack gate refuses to write a manifest without a passing L0
        # record, so the first `vericax audit` must be allowed through without
        # a manifest. Publishing stays gated at pack time. A record that did
        # not pass is no evidence either: it is what a failed first run
        # leaves behind, and it must not block the next attempt. Only a
        # passing record without a manifest is a contradiction.
        if validity.reference_selfcheck_state(
                validity.load_reference_selfcheck(task_dir)) == "pass":
            raise SystemExit(f"package has no manifest: {task_dir}")
        return
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
    result["tree_version"] = validity.tree_version(task_dir)
    l0 = validity.load_reference_selfcheck(task_dir)
    result["reference_selfcheck"] = validity.reference_selfcheck_state(l0)
    if l0 is None:
        print("check: WARNING - no L0 reference self-check "
              "(`vericax audit --task ...` before publishing)")
    elif not l0.get("passed"):
        print("check: WARNING - L0 reference self-check did not pass")
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
    # Milliseconds + 3 random bytes keep parallel episodes from colliding even
    # when two threads enter the same second (P4).
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    short = task_id.rsplit("--", 1)[-1]
    episode_id = f"ep-{short}-{adapter_name}-{run_index:02d}-{stamp}-{secrets.token_hex(3)}"
    return REPO / "runs" / episode_id


def episode_challenge(task_json: dict, override: str | None = None) -> str | None:
    """Per-episode L6 token (spec/02 L6.3), or None for non-L6 tasks.

    ``provenance.challenge`` is the task's fixed audit token: it is what L0
    and ``audit_task.py`` use. A real episode gets a fresh label so a replayed
    artifact from an older episode no longer carries the required set/group.
    """
    if override:
        return override
    provenance = task_json.get("provenance") or {}
    if "{challenge}" in task_json.get("instruction", "") or provenance.get("challenge"):
        return "VCAX_EP_" + secrets.token_hex(8).upper()
    return None


def _record_sandbox_loss(logs_dir: Path, *, task_id: str, adapter: str, episode_id: str,
                         stage: str, vm: SandboxVM, proxy: dict | None, agent,
                         detail: str) -> None:
    """Capture why a sandbox was lost, before its container is removed."""
    try:
        record = host.sandbox_loss_record(
            episode_id=episode_id, task_id=task_id, adapter=adapter, stage=stage,
            detail=detail, proxy=proxy,
            agent={"exit_code": agent.exit_code,
                   "killed_by_deadline": agent.killed_by_deadline,
                   "aborted": agent.aborted,
                   "duration_seconds": agent.duration_seconds},
            vm_state=vm.container_state(log_tail=60))
        path = host.write_loss_record(logs_dir, record)
        print(f"run: sandbox lost at {stage}; evidence -> {path}")
    except Exception as exc:  # noqa: BLE001 - forensics only, never fatal
        print(f"run: WARNING - could not capture sandbox-loss evidence: {exc!r}")


GUEST_PROFILE_SCRIPT = (
    "echo '== os =='; head -4 /etc/os-release; uname -r; "
    "echo '== init =='; ps -p 1 -o args=; systemctl --version 2>/dev/null | head -1; "
    "echo '== resources =='; free -m | sed -n '1,3p'; nproc; cat /proc/uptime; "
    "echo '== timers =='; systemctl list-timers --all --no-pager --no-legend 2>&1 | head -40"
)


def _save_guest_profile(logs_dir: Path, vm: SandboxVM) -> None:
    """Record the guest baseline before the agent starts.

    The timer list is there on purpose: two B2-era guests crashed in PID 1
    about 35 minutes after boot while idle, and nothing else said what the
    guest had scheduled. Forensics only, never fatal.
    """
    try:
        text = vm.bash(GUEST_PROFILE_SCRIPT, timeout=60).get("output", "")
    except Exception as exc:  # noqa: BLE001
        text = f"<profile unavailable: {type(exc).__name__}>"
    (logs_dir / "guest-profile.txt").write_text(text)


def _save_console(logs_dir: Path, vm: SandboxVM) -> None:
    """Keep the guest console before the VM container is removed."""
    try:
        (logs_dir / "vm-console.log").write_text(vm.console_log())
    except Exception as exc:  # noqa: BLE001 - forensics only, never fatal
        print(f"run: WARNING - could not save the VM console log: {exc!r}")


def _extract_cost(adapter: adapters_mod.Adapter, stdout: str) -> dict | None:
    """Data-driven cost extraction; returns spec/03 cost fields or None.

    Reads adapter.output.cost_path (a dotted path into each JSON event) and
    sums token usage across events. No stack branching happens here. Two
    shapes are accepted: NDJSON events (dsh/pi/opencode), and one JSON envelope
    that is not a line of its own, pretty-printed and possibly behind plain log
    lines on the same stream (openclaw --json). The envelope is only searched
    for when no line parsed as an event carrying usage. ``prompt_tokens`` and
    ``completion_tokens`` are the uncached ones, the same basis for every
    stack: a stack's own ``total`` usually adds cache reads on top. Cache reads
    and writes that a stack reports separately go into their own fields, so
    the cached part stays visible without changing token/task.
    """
    if not adapter.cost_path:
        return None
    keys = adapter.cost_path.split(".")
    totals = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
              "reasoning_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
              # per reply: the largest output, and the replies the provider cut at the
              # output limit. None when one event describes the whole session.
              "max_output_tokens": None, "truncated_replies": None}
    per_reply = adapter.cost_granularity != "session"
    usd = 0.0
    seen = False

    def consume(event: object) -> None:
        nonlocal seen, usd
        if not isinstance(event, dict):
            return
        node: object = event
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                node = None
                break
        if not isinstance(node, dict):
            return
        if adapter.cost_event_types and event.get("type") not in adapter.cost_event_types:
            return
        seen = True
        totals["llm_calls"] += 1
        reply: dict[str, int] = {}
        aliases = {
            "prompt_tokens": ("input", "input_tokens", "inputTokens", "prompt_tokens"),
            "completion_tokens": ("output", "output_tokens", "outputTokens", "completion_tokens"),
            "reasoning_tokens": ("reasoning", "reasoning_tokens", "reasoningTokens"),
            # dsh: cacheReadTokens; openclaw: cacheRead / cacheWrite
            "cache_read_tokens": ("cacheRead", "cacheReadTokens", "cache_read",
                                  "cache_read_tokens", "cached_tokens"),
            "cache_write_tokens": ("cacheWrite", "cacheWriteTokens", "cache_write",
                                   "cache_write_tokens", "cache_creation_tokens"),
        }
        for field_name, candidates in aliases.items():
            for candidate in candidates:
                value = node.get(candidate)
                if isinstance(value, (int, float)):
                    totals[field_name] += int(value)
                    reply[field_name] = int(value)
                    break
        if per_reply:
            largest = reply.get("completion_tokens")
            if largest is not None and (totals["max_output_tokens"] is None
                                       or largest > totals["max_output_tokens"]):
                totals["max_output_tokens"] = largest
            for source in (event, node):
                stop = next((source[key] for key in ("stopReason", "finish_reason", "stop_reason")
                             if isinstance(source, dict) and isinstance(source.get(key), str)), None)
                if stop is not None:
                    totals["truncated_replies"] = (totals["truncated_replies"] or 0) + (
                        1 if stop.lower() in ("length", "max_tokens", "max_output_tokens") else 0)
                    break
        cost_node = node.get("cost")
        if isinstance(cost_node, dict) and isinstance(cost_node.get("total"), (int, float)):
            usd += float(cost_node["total"])

    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        consume(event)
    if not seen:
        decoder = json.JSONDecoder()
        offset = 0
        for line in stdout.splitlines(keepends=True):
            stripped = line.lstrip()
            if not seen and stripped.startswith("{"):
                try:
                    consume(decoder.raw_decode(stdout, offset + len(line) - len(stripped))[0])
                except ValueError:
                    pass
            offset += len(line)
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
        vm.wait_healthy()
        isolated, isolation_detail = vm.isolate_network()
        vm.wait_healthy()
        report["network_isolated"] = isolated
        report["network_isolation_detail"] = isolation_detail
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


# ---------------------------------------------------------------- L0 audit
def _load_audit_cases(task_dir: Path):
    spec = importlib.util.spec_from_file_location("audit_cases", task_dir / "audit_cases.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"no audit_cases.py in {task_dir}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_reference_selfcheck(task_id: str, keep_vm: bool = False) -> dict:
    """L0 benchmark-validity gate (spec/02 section 1).

    Replay the shipped reference case, require the produced summary to match the
    shipped GT summary, and run the task's own verifier against the replay. The
    record is written to ``ground_truth/reference_selfcheck.json`` (a derived
    artifact excluded from the package manifest) and to a raw run directory.
    """
    task_dir = _task_dir(task_id)
    task_json = _load_task(task_dir, task_id)
    _verify_task_package(task_dir)
    artifact_paths = task_json.get("artifact_paths", [])
    freeze.check_basename_uniqueness(artifact_paths)
    if not artifact_paths:
        raise SystemExit("task declares no artifact_paths")

    snapshot = task_json.get("snapshot", "CalculiX-2.21")
    image = config.image_path(snapshot)
    image_sha = config.image_sha256(image)
    gold_script = _load_audit_cases(task_dir).CASES[0][1]
    expected_path = task_dir / "ground_truth" / "summary.txt"
    expected_summary = expected_path.read_text().strip() if expected_path.is_file() else None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_dir = REPO / "runs" / f"l0-{task_id.rsplit('--', 1)[-1]}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    vm = SandboxVM(snapshot, cache_dir=out_dir / "cache")
    observed: dict[str, bytes] = {}
    observed_summary: str | None = None
    solver_version: str | None = None
    verifier_verdict: str | None = None
    verifier_sha: str | None = None
    pins: dict[str, float] = {}
    detail = ""
    summary_matched = False
    verifier_ok = False
    try:
        vm.boot(_vm_task_config(task_dir, task_json))
        vm.wait_healthy()
        solver_version = scoring._solver_version(vm, task_json.get("solver_probe"))
        replay = vm.bash(gold_script, timeout=1800)
        if replay.get("returncode") != 0:
            detail = f"reference case exited rc={replay.get('returncode')}"
        for remote in artifact_paths:
            data = vm.get(remote)
            if data is None:
                detail = detail or f"reference case did not produce {remote}"
                continue
            name = Path(remote).name
            observed[name] = data
            (out_dir / name).write_bytes(data)
            if name == "summary.txt":
                observed_summary = data.decode(errors="ignore").strip()

        summary_matched = validity.compare_summaries(observed_summary, expected_summary)

        eval_text = (task_dir / "eval.py").read_text()
        try:
            eval_text, pins = scoring.bake_pins(eval_text, expected_summary)
        except SystemExit as exc:
            detail = detail or f"pin baking failed: {exc}"
        verifier_sha = validity.sha256_bytes(eval_text.encode())
        vm.upload(scoring.EVAL_VM_PATH, eval_text.encode())
        for gt_file in sorted((task_dir / "ground_truth").iterdir()):
            if gt_file.is_file() and gt_file.name not in (validity.L0_RECORD, "audit.md"):
                vm.upload(f"{scoring.SCORE_VM_ROOT}/ground_truth/{gt_file.name}",
                          gt_file.read_bytes())
        for name, data in observed.items():
            vm.upload(f"{scoring.AGENT_ROOT}/{name}", data)
        probe = vm.bash(
            f"VERICAX_AGENT_ROOT={scoring.AGENT_ROOT} VERICAX_CCX=/usr/bin/ccx "
            f"python3 {scoring.EVAL_VM_PATH} 2>/tmp/vericax_l0.err; echo rc=$?",
            timeout=900)
        (out_dir / "verifier.stdout").write_text(probe.get("output", ""))
        (out_dir / "verifier.stderr").write_bytes(vm.get("/tmp/vericax_l0.err") or b"")
        verifier_verdict = next(
            (line.strip() for line in probe.get("output", "").splitlines() if line.strip()),
            None)
        evaluator_func = task_json.get("evaluator", {}).get("func", "exact_match")
        if evaluator_func == "exact_match":
            verifier_ok = verifier_verdict == "True"
        else:
            try:
                verifier_ok = float(verifier_verdict) > 0
            except (TypeError, ValueError):
                verifier_ok = False
    finally:
        if keep_vm:
            print(f"l0: leaving the VM running (output: {out_dir})")
        else:
            vm.close()

    passed = bool(summary_matched and verifier_ok)
    manifest = task_dir / "resources.sha256"
    record = {
        "task_id": task_id,
        "performed": True,
        "passed": passed,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        # Bootstrap L0 (new task, no manifest yet) records a null tree
        # version; re-run the L0 after `pack_task.py` writes the manifest and
        # the record gains its final digest.
        "tree_version": (validity.tree_version(task_dir)
                         if manifest.is_file() else None),
        "image_sha256": image_sha,
        "solver_version": solver_version,
        "gt_deck": "audit_cases.CASES[0]",
        "gt_deck_sha256": validity.sha256_bytes(gold_script.encode()),
        "gt_summary_sha256": (validity.sha256_bytes(expected_summary.encode())
                              if expected_summary else None),
        "expected_summary": expected_summary,
        "observed_summary": observed_summary,
        "summary_matched": summary_matched,
        "verifier_verdict": verifier_verdict,
        "verifier_sha256": verifier_sha,
        "pins_baked": pins,
        "artifacts": {name: validity.sha256_bytes(data)
                      for name, data in sorted(observed.items())},
        "detail": detail or None,
        "output_dir": str(out_dir),
    }
    payload = json.dumps(record, indent=2) + "\n"
    validity.reference_selfcheck_path(task_dir).write_text(payload)
    (out_dir / validity.L0_RECORD).write_text(payload)
    print(f"l0: {'PASS' if passed else 'FAIL'} -> {validity.reference_selfcheck_path(task_dir)}")
    return record


# ---------------------------------------------------------------- episode
def run_episode(
    task_id: str,
    adapter_spec: str,
    run_index: int = 1,
    run_total: int = 1,
    time_limit: int | None = None,
    payload_dir: Path | None = None,
    do_score: bool = True,
    run_mode: str = summary_mod.RUN_MODE_RERUN,
    kind: str = "capability",
    tree_version: str | None = None,
    challenge: str | None = None,
    image_override: str | Path | None = None,
) -> tuple[dict, Path]:
    """One full episode. Returns (summary_dict, episode_dir).

    ``challenge`` overrides the generated L6 token (tests/audit only). Normal
    runs let ``episode_challenge`` mint a fresh one per episode.
    """
    if run_mode not in summary_mod.RUN_MODES:
        raise SystemExit(f"run_mode must be one of {summary_mod.RUN_MODES}")
    if kind not in summary_mod.EPISODE_KINDS:
        raise SystemExit(f"kind must be one of {summary_mod.EPISODE_KINDS}")
    task_dir = _task_dir(task_id)
    task_json = _load_task(task_dir, task_id)
    _verify_task_package(task_dir)
    adapter = adapters_mod.load_adapter(adapters_mod.resolve_adapter(adapter_spec))
    artifact_paths = task_json.get("artifact_paths", [])
    tree_version = tree_version or validity.tree_version(task_dir)
    reference_selfcheck = validity.reference_selfcheck_state(
        validity.load_reference_selfcheck(task_dir))
    freeze.check_basename_uniqueness(artifact_paths)

    snapshot = task_json.get("snapshot", "CalculiX-2.21")
    image_path = config.image_path(snapshot, override=image_override)
    image_sha = config.image_sha256(image_path)
    required_tool = (task_json.get("provenance") or {}).get("required_tool")
    challenge = episode_challenge(task_json, challenge)

    episode_dir = _episode_dir(task_id, adapter.name, run_index)
    episode_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = episode_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    container_name = f"vericax-agent-{episode_dir.name}"

    task_limit = task_json.get("limits", {}).get("active_time_seconds")
    effective_limit = time_limit or task_limit or 18000
    deadline_epoch = time.time() + effective_limit

    inst_path = episode_dir / "instruction.md"
    inst_path.write_text(instruction_text(
        task_json, artifact_paths, deadline_epoch, challenge=challenge))

    wall_started = time.monotonic()
    vm: SandboxVM | None = None
    proxy: ProxyServer | None = None
    proxy_dir: Path | None = None
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

    def stop_proxy() -> None:
        nonlocal proxy, proxy_dir
        if proxy is not None:
            proxy.stop()
            proxy = None
        if proxy_dir is not None:
            shutil.rmtree(proxy_dir, ignore_errors=True)
            proxy_dir = None

    try:
        # ---- prepare: sandbox boot (one retry, spec/09 section 8)
        while True:
            boot_attempts += 1
            vm = SandboxVM(snapshot, cache_dir=episode_dir / "cache",
                           image_override=image_override)
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
        # A sandbox that never answers again must fail here, before an agent
        # spends its whole budget on calls that cannot succeed.
        if not vm.wait_healthy():
            raise EpisodeError(CAT_ENVIRONMENT_ERROR,
                               "sandbox control plane not healthy after network isolation",
                               scored=False)
        _save_guest_profile(logs_dir, vm)
        (logs_dir / "network_isolation.json").write_text(json.dumps({
            "sandbox": {"isolated": sandbox_isolated, "detail": sandbox_isolation_detail},
        }, indent=2) + "\n")
        (logs_dir / "vm_processes_before.txt").write_text(vm.process_snapshot())

        # ---- proxy up (auth: Unix socket + per-episode token, T3)
        token = secrets.token_hex(24)
        proxy_socket = temp_socket_path()
        proxy_dir = proxy_socket.parent
        proxy = ProxyServer(
            vm, proxy_socket, token, episode_dir.name,
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
        mounts[str(proxy_socket)] = {
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
        if challenge:
            # The token is already in the instruction; exposing it as an env
            # var keeps scripted agents on the same contract without having to
            # parse markdown. VERICAX_TOOL is deliberately NOT injected here:
            # selecting the tool is part of the software-selection task.
            env["VERICAX_CHALLENGE"] = challenge
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
            abort_event=proxy.loss_event,
        )
        (logs_dir / "agent.stdout").write_text(agent_result.stdout)
        (logs_dir / "agent.stderr").write_text(agent_result.stderr)
        (logs_dir / "agent-container.json").write_text(json.dumps({
            "exit_code": agent_result.exit_code,
            "killed_by_deadline": agent_result.killed_by_deadline,
            "aborted_on_sandbox_loss": agent_result.aborted,
            "duration_seconds": agent_result.duration_seconds,
            "container": agent_result.container,
        }, indent=2) + "\n")

        # ---- sandbox lost mid-run: stop here. There is nothing to freeze, and
        # the evidence is captured before the container is removed.
        if proxy.sandbox_lost:
            loss = proxy.loss_info or {}
            trigger = (loss.get("first_error") or {}).get("verb", "?")
            _record_sandbox_loss(
                logs_dir, task_id=task_id, adapter=adapter.name,
                episode_id=episode_dir.name, stage="run", vm=vm,
                proxy=loss, agent=agent_result,
                detail=f"agent aborted {agent_result.duration_seconds:.0f}s in; "
                       f"first failing verb: {trigger}")
            raise EpisodeError(
                CAT_INFRA_INCOMPLETE,
                f"sandbox lost during the run (first failing verb: {trigger}); "
                f"agent aborted {agent_result.duration_seconds:.0f}s in",
                scored=False)

        # ---- freeze (agent already dead; proxy entry closes first, E5)
        loss_info = proxy.loss_info
        stop_proxy()
        try:
            manifest = freeze.freeze(
                vm, artifact_paths, episode_dir, image_sha, task_id, episode_dir.name)
        except SandboxUnavailable as exc:
            _record_sandbox_loss(
                logs_dir, task_id=task_id, adapter=adapter.name,
                episode_id=episode_dir.name, stage="freeze", vm=vm,
                proxy=loss_info, agent=agent_result, detail=str(exc))
            raise EpisodeError(
                CAT_INFRA_INCOMPLETE,
                f"freeze failed, sandbox unavailable: {exc}", scored=False) from exc

        # ---- close the sandbox before scoring (spec/09 E5 cleanup order:
        # kill agent -> close proxy -> freeze -> close sandbox -> scoring).
        # Keeping the sandbox alive during scoring would hold two VMs per
        # episode and make 2-episode parallelism a 4-VM load.
        (logs_dir / "vm_processes_after.txt").write_text(vm.process_snapshot())
        _save_console(logs_dir, vm)
        if not vm.close():
            # Same warning as in the cleanup path below.
            print(f"run: WARNING - sandbox VM container may still be running: "
                  f"{vm.surviving_container}")
        vm = None

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
                    solver_probe=task_json.get("solver_probe"),
                    challenge=challenge,
                    required_tool=required_tool,
                    image_override=image_override,
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
        stop_proxy()
        if vm is not None:
            try:
                (logs_dir / "vm_processes_after.txt").write_text(vm.process_snapshot())
            except Exception:  # noqa: BLE001 - forensics only
                pass
            _save_console(logs_dir, vm)
            if not vm.close():
                # Never silent: a surviving VM holds its RAM and cores until
                # someone removes it by hand, and shifts the next episodes
                # towards control-channel loss.
                (logs_dir / "leak.json").write_text(json.dumps({
                    "episode_id": episode_dir.name,
                    "container": vm.surviving_container,
                    "ts": time.time(),
                }, indent=2) + "\n")
                print(f"run: WARNING - sandbox VM container may still be running: "
                      f"{vm.surviving_container}")
        cleanup_container(container_name)

    wall = time.monotonic() - wall_started
    # stacks differ in which stream carries their JSON events (pi writes
    # --mode json events to stderr); scan both, extract nothing on silence
    cost = None
    if agent_result:
        for stream in (agent_result.stdout, agent_result.stderr):
            cost = _extract_cost(adapter, stream)
            if cost:
                break
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
        run_mode=run_mode,
        tree_version=tree_version,
        reference_selfcheck=reference_selfcheck,
        kind=kind,
        verifier_sha256=score_result.verifier_sha256 if score_result else None,
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        solver_version=score_result.solver_version if score_result else None,
        agent_exit_code=agent_result.exit_code if agent_result else None,
        killed_by_deadline=agent_result.killed_by_deadline if agent_result else False,
        deadline_epoch=int(deadline_epoch),
        sandbox_network_isolated=sandbox_isolated,
        scoring_network_isolated=score_result.network_isolated if score_result else None,
        challenge=challenge,
        required_tool=required_tool,
    )
    summary_path = summary_mod.write_summary(episode_dir, summary)
    print(f"run: episode {episode_dir.name} recorded -> {summary_path}")
    return summary, episode_dir


# ---------------------------------------------------------------- report
def _episode_kind(row: dict) -> str:
    kind = row.get("kind")
    if kind in summary_mod.EPISODE_KINDS:
        return kind
    # Pre-schema episodes carry no kind; the harness must not infer it from a
    # stack name (rule A1). Callers that run scripted/cheat episodes declare
    # kind=test at run time; older unlabelled records default to capability.
    return "capability"


def report(runs_dir: Path | None = None, include_tests: bool = False) -> str:
    """Aggregate episodes by task/stack/tree/mode (spec/03 section 4).

    Test and debug episodes are excluded by default: the Phase 1 cheat suite
    must never move a capability mean.
    """
    runs_dir = Path(runs_dir or REPO / "runs")
    all_rows = [json.loads(path.read_text())
                for path in sorted(runs_dir.glob("ep-*/summary.json"))]
    rows = [row for row in all_rows
            if include_tests or _episode_kind(row) == "capability"]
    excluded = len(all_rows) - len(rows)
    if not rows:
        return "report: no capability episodes recorded yet"
    lines = [
        "task | adapter | model | tree | mode | n | mean | min | max | errors | basis",
        "---|---|---|---|---|---|---|---|---|---|---",
    ]
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (
            row["task_id"],
            row["agent"]["name"],
            (row.get("model") or {}).get("name") or "-",
            row.get("tree_version") or "-",
            row.get("run_mode") or "-",
        )
        groups.setdefault(key, []).append(row)
    for (task, agent, model, tree, mode), items in sorted(groups.items()):
        scored = [it["score"] for it in items
                  if it["scoring_basis"] == summary_mod.SCORING_BASIS_NATIVE
                  and it.get("score") is not None]
        errors = sum(1 for it in items if it.get("error_category"))
        n_scored = len(scored)
        mean = sum(scored) / n_scored if n_scored else None
        lines.append(
            f"{task} | {agent} | {model} | {validity.short_tree_version(tree)} | {mode} | "
            f"{n_scored}/{len(items)} | {mean if mean is not None else '-'} | "
            f"{min(scored) if scored else '-'} | {max(scored) if scored else '-'} | "
            f"{errors} | {items[0]['scoring_basis']}")
    if excluded and not include_tests:
        lines.append(f"\n(excluded {excluded} test/debug episode(s); --include-tests to show)")
    text = "\n".join(lines) + "\n"
    print(text)
    return text
