#!/usr/bin/env python3
"""Generic VeriCAx audit harness (spec/02 section 4) for any task package.

Boot ONE evaluation VM, produce ground truth from the task's gold case, then run
every case declared in the task's own `audit_cases.py` and check the verdict
against its expectation.

Task package contract (`audit_cases.py` next to the task json):

    GOLD = r\"\"\"<bash script that builds the reference submission>\"\"\"

    CASES = [
        ("P1 positive (gold)",        GOLD,                  ("true",)),
        ("A1 alternative legal deck", ALT,                   ("true",)),
        ("N1 empty delivery",         "",                    ("false",)),
        ("N2 fabricated summary",     GOLD + FABRICATE,      ("false",)),
        # quantified_score tasks assert on the numeric verdict instead:
        ("P2 optimal",                GOLD,                  ("ge", 0.30)),
        ("N5 baseline copied",        BASELINE,              ("le", 0.001)),
    ]

Each script runs inside the VM with the task's init resources already uploaded.
Before every case the harness restores the Desktop from its post-reset snapshot
and removes temporary files created by the previous case, so a case only sees
the init resources and what its own script produces. The audit record also
carries the numeric rejection margin (lowest accepted score minus highest
rejected score), so "rejected" is a reviewable quantity, not a boolean.

Pinned references: if the verifier declares `EXPECTED_<NAME> = ...` lines and the
gold summary is numeric with the same arity, the harness bakes the measured
values into the verifier copy used for evaluation (the packaged file keeps its
placeholders for authoring, and re-running the audit refreshes the pins).

Usage:
    <runtime-venv>/bin/python scripts/audit_task.py \
        --task cae--cli--calculix--task-0002
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import _config  # noqa: E402  (external dependency resolution)

DESK = "/home/user/Desktop"
EVAL_VM_PATH = "/home/user/vericax/eval.py"
BASE_TAR = "/home/user/vericax/desktop-baseline.tar"
TMP_BASELINE = "/home/user/vericax/tmp-baseline.txt"
TMP_NOW = "/home/user/vericax/tmp-now.txt"
SCRATCH = "/tmp/vericax-audit-scratch"


def task_dir_for(task_id: str) -> Path:
    domain, iface, software, task = task_id.split("--")
    return REPO / "tasks" / domain / iface / software / task


def load_cases(task_dir: Path):
    spec = importlib.util.spec_from_file_location("audit_cases", task_dir / "audit_cases.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"no audit_cases.py in {task_dir}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workspace_setup_script() -> str:
    """Snapshot the pristine Desktop and the /tmp file listing after VM reset."""
    return (
        f"mkdir -p /home/user/vericax && "
        f"tar -C {DESK} -cf {BASE_TAR} . && "
        f"mkdir -p {SCRATCH} && "
        f"find /tmp -mindepth 1 -maxdepth 1 -type f -printf '%f\\n' | sort > {TMP_BASELINE}"
    )


def workspace_clean_script() -> str:
    """Restore the case workspace between audit cases.

    The whole Desktop is restored from the post-reset tarball, so declared
    artifacts, solver side files (``.frd``/``.sta``/...) and undeclared scratch
    all disappear. The harness scratch directory is recreated empty, and regular
    files created in /tmp by the previous case are removed. Directories and
    sockets in /tmp are left alone: the live desktop session owns them.
    """
    return (
        f"find {DESK} -mindepth 1 -maxdepth 1 -exec rm -rf {{}} +; "
        f"tar -C {DESK} -xf {BASE_TAR}; "
        f"rm -rf {SCRATCH}; mkdir -p {SCRATCH}; "
        f"find /tmp -mindepth 1 -maxdepth 1 -type f -printf '%f\\n' | sort > {TMP_NOW}; "
        f"comm -13 {TMP_BASELINE} {TMP_NOW} | while IFS= read -r f; do rm -f \"/tmp/$f\"; done"
    )


def check_expectation(expect: tuple, verdict: str) -> tuple[bool, str, float | None]:
    """Check one verdict. The third element is the numeric score, if any."""
    kind = expect[0]
    if kind in ("true", "false"):
        want = "True" if kind == "true" else "False"
        first = verdict.splitlines()[0].strip() if verdict else "<no output>"
        return first == want, f"want={want} got={first}", None
    try:
        value = float(verdict.splitlines()[0])
    except (ValueError, IndexError):
        return False, f"want={expect} got=<unparseable {verdict[:40]!r}>", None
    if kind == "ge":
        return value >= expect[1], f"want>={expect[1]} got={value:.6f}", value
    if kind == "le":
        return value <= expect[1], f"want<={expect[1]} got={value:.6f}", value
    raise SystemExit(f"unknown expectation kind: {kind}")


def rejection_margin(observed: list[tuple[tuple, float | None]]) -> dict | None:
    """Separation between the lowest accepted and the highest rejected score.

    Only numeric expectations participate. ``None`` means the task has no
    numeric positive/negative pair (an exact-match task), so there is no margin
    to record.
    """
    positive = [v for expect, v in observed if expect[0] == "ge" and v is not None]
    negative = [v for expect, v in observed if expect[0] == "le" and v is not None]
    if not positive or not negative:
        return None
    low, high = min(positive), max(negative)
    return {"margin": low - high, "min_positive": low, "max_negative": high}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True)
    ap.add_argument("--keep-vm", action="store_true")
    ap.add_argument("--repeat", type=int, default=1,
                    help="robustness group: replay the gold submission N times "
                         "and require identical verdicts (release: >=10)")
    args = ap.parse_args()

    task_dir = task_dir_for(args.task)
    task_json = json.loads((task_dir / f"{task_dir.name}.json").read_text())
    cases = load_cases(task_dir).CASES
    artifacts = [Path(p).name for p in task_json.get("artifact_paths", [])]
    if not artifacts:
        raise SystemExit("task declares no artifact_paths")
    gt_dir = task_dir / "ground_truth"

    runtime = _config.runtime_path()
    image = _config.image_path(task_json.get("snapshot", "CalculiX-2.21"))
    sys.path.insert(0, str(runtime / "engine"))
    from desktop_env.desktop_env import DesktopEnv  # noqa: E402

    # mirror the runtime's path resolution: local_path is relative to the
    # software directory (the task dir's parent)
    software_dir = task_dir.parent
    for item in task_json.get("config", []):
        if item.get("type") != "upload_file":
            continue
        for res in item.get("parameters", {}).get("files", []):
            res["local_path"] = str((software_dir / res["local_path"]).resolve())

    env = DesktopEnv(
        provider_name="docker", path_to_vm=str(image), os_type="Ubuntu",
        action_space="pyautogui", require_a11y_tree=False,
        screen_size=(1920, 1080), headless=True, client_password="",
        cache_dir=str(REPO / "cache" / "audit" / args.task),
    )

    def sh(script: str, timeout: int = 600) -> None:
        env.step(("bash", script), bash_timeout=timeout)

    def put(remote: str, data: bytes) -> None:
        b64 = base64.b64encode(data).decode()
        sh(f"mkdir -p $(dirname {remote}) && echo '{b64}' | base64 -d > {remote}")

    def get(remote: str) -> bytes | None:
        try:
            return env.controller.get_file(remote)
        except Exception:  # noqa: BLE001
            return None

    def clean() -> None:
        sh(workspace_clean_script())

    def verdict() -> tuple[str, str]:
        sh(f"cd {DESK} && python3 {EVAL_VM_PATH} > _verdict.txt 2> _verdict.err; "
           f"echo \"rc=$?\" >> _verdict.txt")
        out = (get(f"{DESK}/_verdict.txt") or b"").decode(errors="ignore").strip()
        err = (get(f"{DESK}/_verdict.err") or b"").decode(errors="ignore").strip()
        return out, err

    results = []
    gold_summary = ""
    try:
        print("[boot] starting VM ...")
        env.reset(task_config=task_json)
        sh(workspace_setup_script())
        print("[boot] VM ready (desktop baseline captured)")

        # ---------------- ground truth from the gold case
        gold_script = cases[0][1]
        print("[gt] running gold case ...")
        clean()
        sh(gold_script)
        for name in artifacts:
            data = get(f"{DESK}/{name}")
            if not data:
                print(f"[gt] FAILED to fetch {name}", file=sys.stderr)
                return 3
            gt_dir.mkdir(parents=True, exist_ok=True)
            (gt_dir / name).write_bytes(data)
            print(f"[gt] {name}: {len(data)} bytes")
        if "summary.txt" in artifacts:
            gold_summary = (gt_dir / "summary.txt").read_text().strip()
            print(f"[gt] reference summary: {gold_summary}")

        # ---------------- verifier copy (fill pinned references if declared)
        eval_text = (task_dir / "eval.py").read_text()
        baked = eval_text
        pin_names = re.findall(r"(?m)^EXPECTED_([A-Z0-9_]+) = ", eval_text)
        if pin_names and gold_summary:
            values = []
            for part in gold_summary.split(","):
                try:
                    values.append(float(part.strip()))
                except ValueError:
                    values = []
                    break
            if values and len(values) == len(pin_names):
                for name, value in zip(pin_names, values):
                    baked = re.sub(rf"(?m)^EXPECTED_{name} = .*$",
                                   f"EXPECTED_{name} = {value!r}", baked)
                print(f"[gt] baked pins: {dict(zip(pin_names, values))}")
            elif pin_names:
                print(f"[gt] note: {len(pin_names)} pins vs summary {gold_summary!r}; not baking")
        put(EVAL_VM_PATH, baked.encode())

        # ---------------- cases
        observed = []
        for label, script, expect in cases:
            clean()
            if script.strip():
                sh(script)
            out, err = verdict()
            ok, detail, value = check_expectation(expect, out)
            observed.append((expect, value))
            results.append((label, detail, ok, err[-300:]))
            print(f"[{'PASS' if ok else 'MISS'}] {label}: {detail}")

        # ---------------- rejection margin (spec/02 section 4.1)
        margin = rejection_margin(observed)

        # ---------------- robustness group (spec/02 section 4.1)
        robust = None
        if args.repeat > 1:
            print(f"[robust] replaying gold {args.repeat} times ...")
            verdicts = []
            for _index in range(args.repeat):
                clean()
                if gold_script.strip():
                    sh(gold_script)
                out, _err = verdict()
                first = out.splitlines()[0].strip() if out else "<no output>"
                ok, _detail, _value = check_expectation(cases[0][2], out)
                verdicts.append((first, ok))
            first_verdict = verdicts[0][0]
            agreeing = sum(1 for v, ok in verdicts if ok and v == first_verdict)
            consistent = (all(v == first_verdict for v, _ in verdicts)
                          and all(ok for _, ok in verdicts))
            robust = {"runs": args.repeat, "agreeing": agreeing,
                      "consistent": consistent,
                      "verdicts": [v for v, _ in verdicts]}
            print(f"[robust] {agreeing}/{args.repeat} consistent"
                  f"{'' if consistent else ' (INCONSISTENT)'}")

        # leave the gold submission staged for inspection
        clean()
        if gold_script.strip():
            sh(gold_script)
    finally:
        if not args.keep_vm:
            env.close()

    print("\n===== AUDIT SUMMARY =====")
    passed = sum(1 for r in results if r[2])
    for label, detail, ok, err in results:
        line = f"{'PASS' if ok else 'MISS'}  {label:38s} {detail}"
        if not ok and err.strip():
            line += f"  err={err.strip().splitlines()[0][:140]}"
        print(line)
    print(f"{passed}/{len(results)} expectations matched")
    if margin is None:
        print("rejection margin: n/a (no numeric expectations)")
    else:
        print(f"rejection margin: {margin['margin']:.6f} "
              f"(min positive {margin['min_positive']:.6f}, "
              f"max negative {margin['max_negative']:.6f})")

    (gt_dir / "audit.md").write_text(
        render_audit_md(task_json, results, gold_summary, robust=robust,
                        snapshot=task_json.get("snapshot"), margin=margin))
    print(f"audit record -> {gt_dir / 'audit.md'}")
    margin_ok = margin is None or margin["margin"] > 0
    ok = passed == len(results) and (robust is None or robust["consistent"]) and margin_ok
    return 0 if ok else 1


def render_audit_md(task_json: dict, results, gold_summary: str,
                    robust: dict | None = None, snapshot: str | None = None,
                    margin: dict | None = None) -> str:
    import datetime
    lines = [
        "# Verifier audit record",
        "",
        f"- date: {datetime.date.today().isoformat()}",
        f"- task: {task_json.get('id')} (evaluator func: "
        f"{task_json.get('evaluator', {}).get('func')})",
        f"- image: {snapshot or task_json.get('snapshot')}",
        f"- reference submission summary: `{gold_summary}`",
    ]
    if robust is not None:
        sample = ", ".join(robust["verdicts"][:5])
        if len(robust["verdicts"]) > 5:
            sample += ", ..."
        lines.append(f"- robust: {robust['agreeing']}/{robust['runs']} consistent "
                     f"(verdicts: {sample})")
    if margin is not None:
        lines.append(f"- rejection margin: {margin['margin']:.6f} "
                     f"(min positive {margin['min_positive']:.6f} - "
                     f"max negative {margin['max_negative']:.6f})")
    else:
        lines.append("- rejection margin: n/a (no numeric expectations)")
    lines += [
        "",
        "| case | expectation | actual | verdict |",
        "|---|---|---|---|",
    ]
    for label, detail, ok, _err in results:
        want, _, got = detail.partition(" got=")
        lines.append(f"| {label} | {want} | {got} | {'PASS' if ok else 'MISS'} |")
    lines += ["", "Generated by scripts/audit_task.py from the task's audit_cases.py.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
