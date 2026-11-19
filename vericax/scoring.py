"""Tier-1 scoring instance (spec/09 section 7).

A separate VM from the same image, booted after the agent is dead and the
artifacts are frozen. It receives only: the task package's verifier and
ground-truth pins, and the frozen artifact copies. No agent, no sandbox
network, no internet. The verdict it prints is the only scoring evidence.

Determinism rules: one scoring pass per episode; the same image must have
produced the pinned references; any verifier crash is ``infra_incomplete``
and never a capability zero.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox_vm import SandboxVM

SCORE_VM_ROOT = "/home/user/vericax"
AGENT_ROOT = f"{SCORE_VM_ROOT}/agent"
EVAL_VM_PATH = f"{SCORE_VM_ROOT}/eval.py"
DEFAULT_EVAL_TIMEOUT = 600


@dataclass
class ScoreResult:
    verdict_text: str = ""
    score: float | None = None
    basis: str = "native_evaluator"
    native_executed: bool = False
    infra: bool = False
    detail: str = ""
    pins_baked: dict[str, float] = field(default_factory=dict)
    network_isolated: bool | None = None
    solver_version: str | None = None
    verifier_sha256: str | None = None
    logs: dict[str, str] = field(default_factory=dict)


def bake_pins(eval_text: str, gold_summary: str | None) -> tuple[str, dict[str, float]]:
    """Fill ``EXPECTED_<NAME> = None`` placeholders from the audited gold summary.

    Mirrors scripts/audit_task.py: pins bind verifier references to the image
    they were measured on. The packaged verifier keeps placeholders for
    authoring; only the scoring copy receives measured values.
    """
    pin_names = re.findall(r"(?m)^EXPECTED_([A-Z0-9_]+) = None\s*(?:#.*)?$", eval_text)
    if not pin_names:
        return eval_text, {}
    if not gold_summary:
        raise SystemExit(
            "verifier declares EXPECTED_* placeholders but ground_truth has no "
            "gold summary; run scripts/audit_task.py first")
    values: list[float] = []
    for part in gold_summary.split(","):
        try:
            values.append(float(part.strip()))
        except ValueError:
            values = []
            break
    if not values or len(values) != len(pin_names):
        raise SystemExit(
            f"cannot bake {len(pin_names)} pins from gold summary {gold_summary!r}")
    baked = eval_text
    for name, value in zip(pin_names, values):
        baked = re.sub(rf"(?m)^EXPECTED_{name} = None.*$", f"EXPECTED_{name} = {value!r}", baked)
    return baked, dict(zip(pin_names, values))


def run_scoring(
    task_dir: Path,
    evaluator_func: str,
    frozen_artifacts_dir: Path,
    snapshot: str,
    cache_dir: Path,
    eval_timeout: int = DEFAULT_EVAL_TIMEOUT,
    solver_probe: str | None = None,
) -> ScoreResult:
    """Boot the scoring VM, inject verifier + frozen artifacts, run the verifier."""
    result = ScoreResult()
    task_dir = Path(task_dir)
    frozen_artifacts_dir = Path(frozen_artifacts_dir)

    eval_text = (task_dir / "eval.py").read_text()
    gold_summary_path = task_dir / "ground_truth" / "summary.txt"
    gold_summary = gold_summary_path.read_text().strip() if gold_summary_path.is_file() else None
    eval_text, result.pins_baked = bake_pins(eval_text, gold_summary)
    result.verifier_sha256 = hashlib.sha256(eval_text.encode()).hexdigest()

    vm = SandboxVM(snapshot, cache_dir=cache_dir)
    try:
        vm.boot(None)  # clean VM: no task setup, no init files, no verifier yet
        vm.wait_healthy()
        result.network_isolated, isolation_detail = vm.isolate_network()
        vm.wait_healthy()
        result.logs["network_isolation"] = isolation_detail
        result.solver_version = _solver_version(vm, solver_probe)

        vm.upload(EVAL_VM_PATH, eval_text.encode())
        gt_dir = task_dir / "ground_truth"
        if gt_dir.is_dir():
            for gt_file in sorted(gt_dir.iterdir()):
                if gt_file.is_file():
                    vm.upload(f"{SCORE_VM_ROOT}/ground_truth/{gt_file.name}", gt_file.read_bytes())
        for artifact in sorted(frozen_artifacts_dir.iterdir()):
            if artifact.is_file() and artifact.name != "artifacts.json":
                vm.upload(f"{AGENT_ROOT}/{artifact.name}", artifact.read_bytes())

        run = vm.bash(
            f"VERICAX_AGENT_ROOT={AGENT_ROOT} VERICAX_CCX=/usr/bin/ccx "
            f"python3 {EVAL_VM_PATH} > {SCORE_VM_ROOT}/_out.txt 2> {SCORE_VM_ROOT}/_err.txt; "
            f'echo "rc=$?"',
            timeout=eval_timeout + 60,
            cwd=SCORE_VM_ROOT,
        )
        out = vm.get(f"{SCORE_VM_ROOT}/_out.txt") or b""
        err = vm.get(f"{SCORE_VM_ROOT}/_err.txt") or b""
        result.logs = {
            "evaluator_stdout": out.decode(errors="ignore"),
            "evaluator_stderr": err.decode(errors="ignore"),
            "bash_returncode": str(run.get("returncode")),
        }
        result.native_executed = True

        rc_line = run["output"].strip()
        rc = int(rc_line.split("rc=")[-1]) if rc_line.startswith("rc=") else -1
        verdict = out.decode(errors="ignore").strip().splitlines()
        first = verdict[0].strip() if verdict else ""

        if rc != 0:
            result.infra = True
            result.basis = "infra"
            result.detail = f"verifier exited rc={rc}"
            return result

        if evaluator_func == "exact_match":
            if first in ("True", "False"):
                result.verdict_text = first
                result.score = 1.0 if first == "True" else 0.0
            else:
                result.infra = True
                result.basis = "infra"
                result.detail = f"verifier produced no True/False verdict: {first!r}"
        elif evaluator_func == "quantified_score":
            try:
                result.score = float(first)
                result.verdict_text = first
            except ValueError:
                result.infra = True
                result.basis = "infra"
                result.detail = f"verifier produced no numeric verdict: {first!r}"
        else:
            result.infra = True
            result.basis = "infra"
            result.detail = f"unsupported evaluator func: {evaluator_func}"
        return result
    finally:
        vm.close()


DEFAULT_SOLVER_PROBE = "ccx -v 2>&1 | head -2"


def _solver_version(vm: SandboxVM, probe_command: str | None = None) -> str | None:
    """Record the solver version via the task-declared probe command.

    The probe is task-owned metadata (``solver_probe`` in the task JSON):
    different images carry different solvers, and the harness must not guess.
    """
    try:
        probe = vm.bash(probe_command or DEFAULT_SOLVER_PROBE, timeout=60)
        text = probe.get("output", "").strip()
        return text.splitlines()[0] if text and probe.get("returncode") == 0 else None
    except Exception:  # noqa: BLE001 - metadata only
        return None
