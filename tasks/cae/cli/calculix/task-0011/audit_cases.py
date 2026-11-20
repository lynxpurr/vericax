"""Audit cases for cae--cli--calculix--task-0011 (drawing reconstruction).

The first case is the ground-truth source. The drawing dimensions are
120 / 70 / 12 / 8 / 80 N. The verifier checks the reconstructed stepped beam
and re-solves it.
"""

BASE = r"""
set -e
cd /home/user/Desktop
export N=__N__
export LEN=__LEN__
export ROOT=__ROOT__
export TIP=__TIP__
export LOAD=__LOAD__
export REVERSE=__REVERSE__
export ELSETS=__ELSETS__
python3 - <<'PYEOF'
import os
from pathlib import Path

n = int(os.environ["N"])
length = float(os.environ["LEN"])
root = float(os.environ["ROOT"])
tip = float(os.environ["TIP"])
load = float(os.environ["LOAD"])
reverse = os.environ["REVERSE"] == "1"
elset_cards = os.environ["ELSETS"] == "1"
split_elem = 7 if n == 12 else n // 2

lines = ["*Heading", "VeriCAX task-0011 reconstructed stepped beam", "*Node"]
order = range(n + 1, 0, -1) if reverse else range(1, n + 2)
for i in order:
    x = length * (i - 1) / n
    lines.append(f"{i}, {x:.6f}, 0.0, 0.0")

if elset_cards:
    lines.append("*Element, type=B31")
    for e in range(1, n + 1):
        lines.append(f"{e}, {e}, {e + 1}")
    lines += ["*Elset, elset=RootElems", ", ".join(str(e) for e in range(1, split_elem + 1)),
              "*Elset, elset=TipElems", ", ".join(str(e) for e in range(split_elem + 1, n + 1))]
else:
    if reverse:
        lines.append("*Element, type=B31, elset=TipElems")
        for e in range(n, split_elem, -1):
            lines.append(f"{e}, {e}, {e + 1}")
        lines.append("*Element, type=B31, elset=RootElems")
        for e in range(split_elem, 0, -1):
            lines.append(f"{e}, {e}, {e + 1}")
    else:
        lines.append("*Element, type=B31, elset=RootElems")
        for e in range(1, split_elem + 1):
            lines.append(f"{e}, {e}, {e + 1}")
        lines.append("*Element, type=B31, elset=TipElems")
        for e in range(split_elem + 1, n + 1):
            lines.append(f"{e}, {e}, {e + 1}")

lines += ["*Nset, nset=All_Nodes", ", ".join(str(i) for i in range(1, n + 2)),
          "*Material, name=Steel", "*Elastic", "210000.0, 0.3",
          "*Beam Section, elset=RootElems, material=Steel, section=RECT", f"{root!r}, {root!r}",
          "*Beam Section, elset=TipElems, material=Steel, section=RECT", f"{tip!r}, {tip!r}",
          "*Boundary", "1, 1, 6, 0.0",
          "*Step", "*Static", "*Cload", f"{n + 1}, 2, {load!r}",
          "*Node Print, NSET=All_Nodes", "U", "*End Step", ""]
Path("solution.inp").write_text("\n".join(lines))
PYEOF
/usr/bin/ccx solution > /tmp/ccx-run.log 2>&1 || { tail -25 /tmp/ccx-run.log; exit 1; }
python3 - <<'PYEOF'
import os, re
from pathlib import Path
n = int(os.environ["N"])
dat = Path("solution.dat").read_text(errors="ignore")
uy, head = {}, None
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
assert n + 1 in uy, "parse failed"
Path("summary.txt").write_text(f"{uy[n + 1]}\n")
PYEOF
"""


def make(n=12, length=120.0, root=12.0, tip=8.0, load=-80.0, reverse=0, elsets=0) -> str:
    return (BASE.replace("__N__", str(n))
                .replace("__LEN__", repr(length))
                .replace("__ROOT__", repr(root))
                .replace("__TIP__", repr(tip))
                .replace("__LOAD__", repr(load))
                .replace("__REVERSE__", str(reverse))
                .replace("__ELSETS__", str(elsets)))


GOLD = make()
ALT = make(reverse=1, elsets=1)
ALT2 = make(elsets=1)
WRONG_LENGTH = make(n=10, length=100.0)
WRONG_ROOT = make(root=10.0)
WRONG_TIP = make(tip=10.0)
WRONG_LOAD = make(load=-100.0)
COARSE = make(n=6, length=120.0)

FABRICATE = GOLD + r"""
python3 - <<'PYEOF'
from pathlib import Path
v = float(Path("/home/user/Desktop/summary.txt").read_text())
Path("/home/user/Desktop/summary.txt").write_text(f"{v * 1.10!r}\n")
PYEOF
"""

ZERO_DAT = GOLD + "\n: > /home/user/Desktop/solution.dat\n"

METRICS_ONLY = r"""
set -e
cd /home/user/Desktop
printf '%s\n' '-0.164' > summary.txt
"""

ENCODE_SUMMARY = GOLD + r"""
python3 - <<'PYEOF'
import base64
from pathlib import Path
raw = Path("/home/user/Desktop/summary.txt").read_text().strip().encode()
Path("/home/user/Desktop/summary.txt").write_text(base64.b64encode(raw).decode() + "\n")
PYEOF
"""

NEGATIVE_KINDS = {
    "N1 empty delivery": "empty",
    "N2 tip load tampered": "tampered_input",
    "N5 fabricated summary (+10%)": "fabricated_field",
    "N6 zero-byte solver output": "skipped_steps",
    "N7 metrics only": "metrics_only",
    "N8 encoded payload": "encoded_payload",
}

CASES = [
    ("P1 positive (gold)", GOLD, ("true",)),
    ("P2 robust (gold re-run)", GOLD, ("true",)),
    ("A1 alternative legal (reversed ids, elset cards)", ALT, ("true",)),
    ("A2 alternative legal (elset cards)", ALT2, ("true",)),
    ("N1 empty delivery", "", ("false",)),
    ("N2 tip load tampered", WRONG_LOAD, ("false",)),
    ("N3 wrong length", WRONG_LENGTH, ("false",)),
    ("N4 wrong root section", WRONG_ROOT, ("false",)),
    ("N5 fabricated summary (+10%)", FABRICATE, ("false",)),
    ("N6 zero-byte solver output", ZERO_DAT, ("false",)),
    ("N7 metrics only", METRICS_ONLY, ("false",)),
    ("N8 encoded payload", ENCODE_SUMMARY, ("false",)),
    ("N9 wrong tip section", WRONG_TIP, ("false",)),
    ("N10 coarse mesh", COARSE, ("false",)),
]