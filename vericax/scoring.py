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
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox_vm import SandboxVM

SCORE_VM_ROOT = "/home/user/vericax"
AGENT_ROOT = f"{SCORE_VM_ROOT}/agent"
EVAL_VM_PATH = f"{SCORE_VM_ROOT}/eval.py"
DEFAULT_EVAL_TIMEOUT = 600

# Guest RAM of the scoring VM. The agent sandbox keeps the provider default
# (4G); the verifier re-solves the submitted model and needs more than the
# agent did: two published B2 episodes lost a direct LU factorisation of a
# large, legal mesh to a 4G scoring VM and were scored as capability zeros.
# qemu allocates guest RAM lazily, so a larger limit costs nothing until used.
DEFAULT_SCORING_RAM = "16G"
SCORING_RAM_ENV = "VERICAX_SCORING_RAM"

# The verifier template catches every exception and prints "False" (or
# "0.000000") so that a malformed delivery is a verdict and never a crash.
# This is its signature for that path.
EXCEPTION_LINE = "debug: evaluator exception"
# ... and the part of it that means the verifier's own resources failed.
RESOURCE_ERROR = re.compile(r"Out of memory|MemoryError|Cannot allocate memory|Error error code \d+")


def scoring_ram() -> str:
    """Guest RAM of the scoring VM; ``VERICAX_SCORING_RAM`` overrides the default."""
    return os.environ.get(SCORING_RAM_ENV, DEFAULT_SCORING_RAM)


def is_resource_failure(stdout: str, stderr: str) -> bool:
    """True when the verifier's zero came from a failure of its own resources.

    A zero printed after ``debug: evaluator exception`` together with an
    out-of-memory report or a PETSc error code means the delivery was not
    evaluated (the scoring VM ran out of RAM on a large mesh). The scorer
    reports that as ``infra`` so the episode is retried, not counted as a
    capability zero. Any other exception stays a verdict: a delivery that
    cannot be read is a rejection.
    """
    lines = stdout.strip().splitlines()
    first = lines[0].strip() if lines else ""
    if first == "False":
        zero = True
    else:
        try:
            zero = float(first) == 0.0
        except ValueError:
            zero = False
    if not zero or EXCEPTION_LINE not in stderr:
        return False
    return bool(RESOURCE_ERROR.search(stderr.split(EXCEPTION_LINE, 1)[1]))


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
    challenge: str | None = None,
    required_tool: str | None = None,
    image_override: str | Path | None = None,
) -> ScoreResult:
    """Boot the scoring VM, inject verifier + frozen artifacts, run the verifier.

    ``challenge`` and ``required_tool`` are the per-episode L6 bindings
    (spec/02 L6.3, spec/09 section 7.1). They are injected into the scoring
    instance only; the agent never sees ``VERICAX_TOOL``.
    """
    result = ScoreResult()
    task_dir = Path(task_dir)
    frozen_artifacts_dir = Path(frozen_artifacts_dir)

    eval_text = (task_dir / "eval.py").read_text()
    gold_summary_path = task_dir / "ground_truth" / "summary.txt"
    gold_summary = gold_summary_path.read_text().strip() if gold_summary_path.is_file() else None
    eval_text, result.pins_baked = bake_pins(eval_text, gold_summary)
    result.verifier_sha256 = hashlib.sha256(eval_text.encode()).hexdigest()

    vm = SandboxVM(snapshot, cache_dir=cache_dir, image_override=image_override,
                   ram=scoring_ram())
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

        env_bits = [f"VERICAX_AGENT_ROOT={AGENT_ROOT}", "VERICAX_CCX=/usr/bin/ccx"]
        if challenge:
            env_bits.append(f"VERICAX_CHALLENGE={shlex.quote(challenge)}")
        if required_tool:
            env_bits.append(f"VERICAX_TOOL={shlex.quote(required_tool)}")
        run = vm.bash(
            f"{' '.join(env_bits)} "
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

        stdout_text, stderr_text = out.decode(errors="ignore"), err.decode(errors="ignore")
        if is_resource_failure(stdout_text, stderr_text):
            result.infra = True
            result.basis = "infra"
            reason = next((line.strip() for line in stderr_text.splitlines()
                           if EXCEPTION_LINE in line), "")
            result.detail = f"verifier resource failure, delivery not evaluated: {reason[:200]}"
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
        if not vm.close():
            print("score: WARNING - scoring VM container may still be running: "
                  f"{vm.surviving_container}")


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
