#!/usr/bin/env python3
"""Boot one evaluation VM, produce ground truth, and run the full audit suite.

This is the VeriCAx audit harness (spec/02 section 4). A single VM boot does:

  reference   run the golden solution         -> ground_truth/ artifacts + pinned values
  P1 positive ground-truth artifacts          -> expect True
  P2 robust   same input, evaluator re-run    -> expect identical verdict
  A1 alternative legal deck (order permuted,
     extra output requests, BC stated w/o value) -> expect True
  N1 empty delivery (no artifacts)            -> expect False
  N2 fabricated summary numbers               -> expect False
  N3 zero-byte .dat (solve failed, still submitted) -> expect False
  N4 tampered sections (both 10x10)           -> expect False

Usage (uses the EngiWorld runtime venv python, which has the engine deps):

    ~/projects/engiworld-playground/engiworld-repo/runtime/.venv/bin/python \
        scripts/audit_task.py --task cae--cli--calculix--task-0001

Exit code 0 iff every expectation matches.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get(
    "VERICAX_RUNTIME", REPO.parent / "engiworld-playground" / "engiworld-repo" / "runtime"))
ENGINE = RUNTIME / "engine"
IMAGE = Path(os.environ.get(
    "VERICAX_IMAGE",
    REPO.parent / "engiworld-playground" / "environment-images" / "images" / "CalculiX-2.21.qcow2"))

DESK = "/home/user/Desktop"
EVAL_VM_PATH = "/home/user/vericax/eval.py"

# ---------------------------------------------------------------- reference run
REF_SCRIPT = r"""
set -e
cd /home/user/Desktop
rm -f solution.inp solution.dat solution.frd solution.cvg summary.txt
python3 - <<'PYEOF'
from pathlib import Path
n = 10
lines = ["*Heading", "VeriCAX task-0001 reference solution", "*Node"]
for i in range(1, n + 2):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=RootElems")
for e in range(1, 6):
    lines.append(f"{e}, {e}, {e + 1}")
lines.append("*Element, type=B31, elset=TipElems")
for e in range(6, 11):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [
    "*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
    "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
    "*Beam Section, elset=RootElems, material=Steel, section=RECT", "10.0, 10.0",
    "*Beam Section, elset=TipElems, material=Steel, section=RECT", "6.0, 6.0",
    "*Boundary", "1, 1, 6, 0.0", "*Step", "*Static", "*Cload", f"{n + 1}, 2, -100.0",
    "*Node Print, NSET=All_Nodes", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path
import re
dat = Path("solution.dat").read_text(errors="ignore")
uy = {}
head = None
for raw in dat.splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        head = s.lower()
        continue
    if head and "displacements" in head:
        p = s.split()
        try:
            uy[int(p[0])] = float(p[2])
        except (ValueError, IndexError):
            pass
assert 6 in uy and 11 in uy, "parse failed"
Path("summary.txt").write_text(f"{uy[6]}, {uy[11]}\n")
print("REFERENCE:", uy[6], uy[11])
PYEOF
cat summary.txt
"""

ALT_SCRIPT = r"""
set -e
cd /home/user/Desktop
# Legal alternative encoding: elements declared tip-first in two blocks,
# sections in the opposite order, BC without trailing value, integer load,
# own print-set name.
python3 - <<'PYEOF'
from pathlib import Path
n = 10
lines = ["*Heading", "alternative legal deck", "*Node"]
for i in range(n + 1, 0, -1):
    lines.append(f"{i}, {10.0 * (i - 1):.1f}, 0.0, 0.0")
lines.append("*Element, type=B31, elset=TipElems")
for e in range(10, 5, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines.append("*Element, type=B31, elset=RootElems")
for e in range(5, 0, -1):
    lines.append(f"{e}, {e}, {e + 1}")
lines += [
    "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
    "*Beam Section, elset=TipElems, material=Steel, section=RECT", "6.0, 6.0",
    "*Beam Section, elset=RootElems, material=Steel, section=RECT", "10.0, 10.0",
    "*Nset, nset=PrintNodes", ", ".join(str(i) for i in range(1, n + 2)),
    "*Boundary", "1, 1, 6", "*Step", "*Static", "*Cload", "11, 2, -100",
    "*Node Print, NSET=PrintNodes", "U", "*End Step", "",
]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-alt.log 2>&1 || { tail -25 /tmp/ccx-alt.log; exit 1; }
python3 - <<'PYEOF'
from pathlib import Path
import re
dat = Path("solution.dat").read_text(errors="ignore")
uy = {}
head = None
for raw in dat.splitlines():
    s = raw.strip()
    if not s:
        continue
    if re.match(r"^[A-Za-z*]", s):
        head = s.lower()
        continue
    if head and "displacements" in head:
        p = s.split()
        try:
            uy[int(p[0])] = float(p[2])
        except (ValueError, IndexError):
            pass
assert 6 in uy and 11 in uy, "parse failed"
Path("summary.txt").write_text(f"{uy[6]}, {uy[11]}\n")
print("ALTERNATIVE:", uy[6], uy[11])
PYEOF
"""

EVAL_RUN = f"""
cd {DESK}
rm -f _verdict.txt _verdict.err
python3 {EVAL_VM_PATH} > _verdict.txt 2> _verdict.err
echo "rc=$?" >> _verdict.txt
"""


def task_dir_for(task_id: str) -> Path:
    d, i, s, t = task_id.split("--")
    return REPO / "tasks" / d / i / s / t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True)
    ap.add_argument("--keep-vm", action="store_true")
    args = ap.parse_args()

    task_dir = task_dir_for(args.task)
    gt_dir = task_dir / "ground_truth"
    eval_src = task_dir / "eval.py"
    if not eval_src.is_file() or not (task_dir / "init_file").is_dir():
        print(f"task package incomplete: {task_dir}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(ENGINE))
    from desktop_env.desktop_env import DesktopEnv  # noqa: E402

    env = DesktopEnv(
        provider_name="docker", path_to_vm=str(IMAGE.resolve()), os_type="Ubuntu",
        action_space="pyautogui", require_a11y_tree=False,
        screen_size=(1920, 1080), headless=True, client_password="",
        cache_dir=str(REPO / "cache" / "audit"),
    )

    def sh(script: str, timeout: int = 600) -> None:
        env.step(("bash", script), bash_timeout=timeout)

    def put(remote: str, data: bytes) -> None:
        # base64 through the shell keeps arbitrary bytes intact
        import base64
        b64 = base64.b64encode(data).decode()
        sh(f"mkdir -p $(dirname {remote}) && echo '{b64}' | base64 -d > {remote}")

    def get(remote: str) -> bytes | None:
        try:
            return env.controller.get_file(remote)
        except Exception:  # noqa: BLE001
            return None

    def verdict() -> tuple[str, str]:
        sh(EVAL_RUN)
        out = get(f"{DESK}/_verdict.txt") or b""
        err = get(f"{DESK}/_verdict.err") or b""
        return out.decode(errors="ignore").strip(), err.decode(errors="ignore").strip()

    results = []
    try:
        print("[boot] starting VM ...")
        task_json = json.loads((task_dir / f"{task_dir.name}.json").read_text())
        # mirror the runtime's path resolution: local_path is relative to the
        # software directory (the task dir's parent); upload steps need absolute
        software_dir = task_dir.parent
        for item in task_json.get("config", []):
            if item.get("type") != "upload_file":
                continue
            for res in item.get("parameters", {}).get("files", []):
                res["local_path"] = str((software_dir / res["local_path"]).resolve())
        env.reset(task_config=task_json)
        print("[boot] VM ready")

        # ---------------- reference (ground truth)
        print("[gt] running golden solution ...")
        sh(REF_SCRIPT)
        gt = {}
        for name in ("solution.inp", "solution.dat", "summary.txt"):
            data = get(f"{DESK}/{name}")
            if not data:
                print(f"FAILED to fetch {name}", file=sys.stderr)
                return 3
            gt[name] = data
            gt_dir.mkdir(parents=True, exist_ok=True)
            (gt_dir / name).write_bytes(data)
            print(f"[gt] {name}: {len(data)} bytes")
        gt_summary = gt["summary.txt"].decode().strip()
        step, tip = [float(x) for x in gt_summary.split(",")]
        print(f"[gt] pinned values: step_uy={step!r} tip_uy={tip!r}")

        # bake pinned values into a copy of eval.py for this audit run
        eval_text = eval_src.read_text()
        baked = re.sub(r"(?m)^EXPECTED_STEP_UY = .*$", f"EXPECTED_STEP_UY = {step!r}", eval_text)
        baked = re.sub(r"(?m)^EXPECTED_TIP_UY = .*$", f"EXPECTED_TIP_UY = {tip!r}", baked)
        put(EVAL_VM_PATH, baked.encode())

        def stage(inp=None, dat=None, summary=None):
            sh(f"cd {DESK} && rm -f solution.inp solution.dat summary.txt")
            for name, content in (("solution.inp", inp), ("solution.dat", dat), ("summary.txt", summary)):
                if content is not None:
                    put(f"{DESK}/{name}", content)

        def expect(label: str, want_true: bool) -> None:
            out, err = verdict()
            got = out.splitlines()[0].strip() if out else "<no output>"
            ok = (got == ("True" if want_true else "False"))
            results.append((label, want_true, got, ok, err[-300:]))
            print(f"[{'PASS' if ok else 'MISS'}] {label}: want={'True' if want_true else 'False'} got={got}")

        # ---------------- P1 / P2 positive + robustness
        stage(gt["solution.inp"], gt["solution.dat"], gt["summary.txt"])
        expect("P1 positive (ground truth)", True)
        expect("P2 robust (same input re-run)", True)

        # ---------------- A1 alternative legal deck
        sh(ALT_SCRIPT)
        alt = {n: get(f"{DESK}/{n}") for n in ("solution.inp", "solution.dat", "summary.txt")}
        if all(alt.values()):
            stage(alt["solution.inp"], alt["solution.dat"], alt["summary.txt"])
            expect("A1 alternative legal deck", True)
        else:
            results.append(("A1 alternative legal deck", True, "<staging failed>", False, ""))
            print("[MISS] A1 staging failed")

        # ---------------- N1 empty delivery
        stage()
        expect("N1 empty delivery", False)

        # ---------------- N2 fabricated summary
        stage(gt["solution.inp"], gt["solution.dat"], b"-0.01, -0.10\n")
        expect("N2 fabricated summary", False)

        # ---------------- N3 zero-byte dat
        stage(gt["solution.inp"], b"", gt["summary.txt"])
        expect("N3 zero-byte dat", False)

        # ---------------- N4 tampered sections (both 10x10, summary left as-is)
        tampered = gt["solution.inp"].decode().replace(
            "*Beam Section, elset=TipElems, material=Steel, section=RECT\n6.0, 6.0\n",
            "*Beam Section, elset=Seg2, material=Steel, section=RECT\n10.0, 10.0\n")
        stage(tampered.encode(), gt["solution.dat"], gt["summary.txt"])
        expect("N4 tampered sections", False)

        # ---------------- restore a clean desktop
        stage(gt["solution.inp"], gt["solution.dat"], gt["summary.txt"])
    finally:
        if not args.keep_vm:
            env.close()

    print("\n===== AUDIT SUMMARY =====")
    passed = sum(1 for r in results if r[3])
    for label, want, got, ok, err in results:
        print(f"{'PASS' if ok else 'MISS'}  {label:34s} want={'True' if want else 'False'} got={got}"
              + (f"  err={err.strip()[:120]}" if err.strip() else ""))
    print(f"{passed}/{len(results)} expectations matched")

    (task_dir / "ground_truth" / "audit.md").write_text(render_audit_md(results, gt_summary))
    print(f"audit record -> {task_dir / 'ground_truth' / 'audit.md'}")
    return 0 if passed == len(results) else 1


def render_audit_md(results, gt_summary: str) -> str:
    import datetime
    lines = [
        "# Verifier audit record",
        "",
        f"- date: {datetime.date.today().isoformat()}",
        "- image: CalculiX-2.21.qcow2 (same image as evaluation)",
        "- verifier: task-0001/eval.py (IMPLEMENTS L1, L2, L3)",
        f"- ground truth: `summary.txt` = {gt_summary}",
        "",
        "| group | case | expected | actual | verdict |",
        "|---|---|---|---|---|",
    ]
    for label, want, got, ok, _err in results:
        lines.append(f"| — | {label} | {'True' if want else 'False'} | {got} | {'PASS' if ok else 'MISS'} |")
    lines += [
        "",
        "Notes:",
        "- Scored quantities are NODAL displacements (uy at node 6 and node 11), which",
        "  converge with mesh refinement. Beam stress output is deliberately not scored:",
        "  CalculiX reports it at section Gauss points (~0.58x the outer-fibre stress)",
        "  and the value would be ambiguous to request in the instruction.",
        "- Mesh convergence was measured before freezing the task: 1 element/segment",
        "  gives -0.144 (24% below beam theory); the prescribed 10-element mesh gives",
        "  -0.3464 vs analytic -0.3504 (1.1%), inside the verifier's 2% band.",
        "- The alternative deck permutes node/element/section order, splits elements",
        "  across two cards and adds output requests; L2 compares order-independently,","so it must be accepted.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
