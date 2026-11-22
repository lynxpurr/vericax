# Setup

VeriCAx stores specifications, task packages and tooling. Two **external
assets** are needed to run anything: an evaluation runtime and VM images. Both
are large and are *not* part of this repository.

## 1. Host prerequisites

| Requirement | Notes |
|---|---|
| Linux x86_64 with Docker | the runtime launches VMs through `happysixd/osworld-docker` |
| `/dev/kvm` accessible | without it QEMU falls back to slow emulation |
| netfilter legacy modules | `ip_tables`, `iptable_nat`, `iptable_filter`, `iptable_mangle` must be loaded on the host; otherwise QEMU silently degrades to user-mode networking and the VM never becomes reachable. Persist with e.g. `/etc/modules-load.d/vericax-netfilter.conf` |
| `zstd` | to decompress image archives |
| Python 3.10+ | 3.12 recommended; the runtime venv is separate |

Deployment pitfalls observed in practice are listed in
[`docs/spec/04-environment-spec.md`](spec/04-environment-spec.md) section 3.

## 2. Evaluation runtime (external)

The runtime provides `engine/desktop_env` (a fork of the OSWorld desktop
environment). Any checkout providing that layout works. The reference runtime is
the one released with EngiWorld (MIT):

```bash
git clone https://github.com/Hongcheng-Gao/EngiWorld.git
cd EngiWorld/runtime
python3 -m venv .venv
.venv/bin/pip install -e ".[worker-api,download]"
```

`pip install -e` matters: several entry points resolve the engine relative to the
source tree, and a non-editable install points them into `site-packages`.

## 3. VM images (external)

The suite default since 2026-11-22 is the three **self-built** images produced
by `containers/images/*/build.sh`:

| snapshot name | build output |
|---|---|
| `CalculiX-2.21.qcow2` | `~/vericax-image-build/calculix/out/` |
| `FEniCS.qcow2` | `~/vericax-image-build/fenics/out/` |
| `VeriCAx-merged.qcow2` | `~/vericax-image-build/merged/out/` |

The build recipes pin every package; see the per-image `README.md`. Pinned
verifier references are bound to the image they were measured on, so switching
images requires a full re-audit (`scripts/audit_suite.py`).

The older EngiWorld images are still supported for reference. They are
published as `qcow2.zst` archives with a manifest and checksums. For the
CalculiX pilot tasks:

```bash
# from the runtime/ directory, with its venv
.venv/bin/python -m engiworld.prepare_images \
  --source modelscope --image CalculiX-2.21 --image-root /path/to/environment-images
zstd -d /path/to/environment-images/images/CalculiX-2.21.qcow2.zst
```

`--source hf` works too; the ModelScope mirror is usually faster from mainland
China. The downloader verifies the archive against the published SHA-256.

## 4. Point VeriCAx at the assets

```bash
cp vericax.toml.example vericax.toml   # gitignored
```

```toml
[runtime]
path = "/path/to/EngiWorld/runtime"

[images]
# One directory holding all three self-built qcow2 files by snapshot name.
dir = "/path/to/vericax-image-build/suite"
```

The build outputs live in separate directories; link them under one suite
directory (or copy them):

```bash
mkdir -p /path/to/vericax-image-build/suite
cd /path/to/vericax-image-build/suite
ln -s ../calculix/out/CalculiX-2.21.qcow2 CalculiX-2.21.qcow2
ln -s ../fenics/out/FEniCS.qcow2           FEniCS.qcow2
ln -s ../merged/out/VeriCAx-merged.qcow2   VeriCAx-merged.qcow2
```

Environment variables win over the file: `VERICAX_RUNTIME`,
`VERICAX_IMAGE_DIR` (or `VERICAX_IMAGE` for a single file).

Check the resolution:

```bash
python scripts/check_setup.py
```

## 5. Run a task audit

```bash
<runtime-venv>/bin/python scripts/audit_task.py \
  --task cae--cli--calculix--task-0001
```

One boot: it generates the ground truth from the task's gold case, runs every
audit case, and writes `ground_truth/audit.md`. Task packages are valid only
when that record has no `MISS`.

## 6. Packaging

```bash
python scripts/pack_task.py --task cae--cli--calculix--task-0001          # write manifest
python scripts/pack_task.py --task cae--cli--calculix--task-0001 --check  # CI mode
```

The full local CI gate (the same steps as `.github/workflows/ci.yml` plus the
offline tests) is:

```bash
scripts/ci_local.sh
```

GitHub Actions is currently blocked at the account level — every run fails
before step 1 with a billing notice. See [ci.md](ci.md) for the exact status
and the two human options.
