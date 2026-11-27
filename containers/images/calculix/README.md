# Self-built CalculiX image (D5 / P3a)

Build a CalculiX 2.21 qcow2 from a pinned Ubuntu 24.04 cloud image instead of
reusing the EngiWorld image. This is the P3a deliverable; FEniCS 0.10 and the
merged cross-solver image are P3b/P3c.

## Status (2026-11-20): P3a accepted

A **fresh clean build from this recipe** produced an Ubuntu 24.04 image with
`ccx` 2.21-1 and the OSWorld server, and passed both gates on 2026-11-20:

- `vericax audit --task cae--cli--calculix--task-0001 --group reference`:
  passed (`summary_matched=true`, verifier `True`);
- fake-agent run: score 1.0, `image_sha256` matching the image, sandbox and
  scoring network isolation true.

Image under test: `CalculiX-2.21.qcow2`, SHA-256
`91b1d6c843f5f9c6222ba5f56b0c87f5a84f0b29b2d54a6d04db4ddd228547cd`,
1.57 GB. The local `out/` directory also keeps `image-build.json`,
`l0-selfbuilt-task-0001.json` and `smoke-selfbuilt-task-0001.json`; these are
evidence, not committed.

Four CLI-only requirements are captured in `provision.sh` (all were needed to
make the clean build pass): generic DHCP netplan (`99-vericax.yaml`) because
the runner NIC differs from the build NIC; `x11-xserver-utils` for `xrandr`;
a `gnome-screenshot` -> `scrot` shim for pyautogui under Xvfb; and
`/usr/local/bin/python3` -> the venv, because the OSWorld controller runs
action scripts as `python3` and the venv is where pyautogui lives. The
scoring/verifier commands also resolve through that shim; the CalculiX
verifiers only need the standard library, and `ccx` is at `/usr/bin/ccx`.

This validates the **CalculiX-only** image. The suite still runs on the
EngiWorld image; switching `vericax.toml`/`snapshot` to this image requires
re-baking pins and re-running audit/L0 on every task (spec/04 §6). FEniCS
(P3b) and the merged cross-solver image (P3c) are not built yet.

## What is pinned

- Base: `https://cloud-images.ubuntu.com/noble/20261017/noble-server-cloudimg-amd64.img`
  (the build verifies the SHA-256 from the same directory's `SHA256SUMS`).
- Guest packages: `calculix-ccx=2.21-1` (records the actual `ccx` version and
  `dpkg-query` versions in `image-build.json`), Python 3, Xvfb, and the
  OSWorld guest server from the local EngiWorld runtime tree.
- The guest contract: user `user` / password `password`, sudo, Xvfb at
  1920x1080, OSWorld server on port 5000, `ccx` at `/usr/bin/ccx`.

## Prerequisites

- Docker with `/dev/kvm` access; the builder image installs QEMU,
  `cloud-image-utils`, `genisoimage`, `openssh-client`, `python3`, `curl`.
- The OSWorld server bundle from an EngiWorld runtime clone (see
  `docs/setup.md` section 2). Set `VERICAX_OSWORLD_SERVER` to its
  `runtime/engine/desktop_env/server` directory; the build refuses to guess a
  path when the variable is unset.

## Build

```bash
./containers/images/calculix/build.sh
```

Optional overrides:

```bash
VERICAX_IMAGE_BUILD_DIR=/data/vericax-image-build \
VERICAX_OSWORLD_SERVER=/path/to/desktop_env/server \
./containers/images/calculix/build.sh
```

The host downloads the base image, prepares a NoCloud seed, builds the
`vericax-image-builder:24.04` Docker image, and runs the provisioning inside
QEMU. The guest installs packages over SSH, enables `xvfb.service` and
`osworld.service`, checks `/health`, and powers off. The final image is
compressed with `qemu-img convert -O qcow2 -c`.

Output (not committed):

```
$HOME/vericax-image-build/calculix/out/CalculiX-2.21.qcow2
$HOME/vericax-image-build/calculix/out/CalculiX-2.21.qcow2.sha256
$HOME/vericax-image-build/calculix/out/image-build.json
$HOME/vericax-image-build/calculix/out/provision-info.txt
```

## Kernel command line (2026-11-27)

`provision.sh` writes `/etc/default/grub.d/99-vericax-cmdline.cfg`, which
appends `clearcpuid=519` to the kernel command line, and fails the build if
`update-grub` does not carry it into `/boot/grub/grub.cfg`. The parameter
hides `X86_FEATURE_SHSTK` (word 16, bit 7; the feature has no name, so the
number is the only spelling) from the guest kernel. Without it the kernel
arms CET, and PID 1 dies on a shadow-stack state that nothing in the guest
set: the guest panics a few minutes after boot
(`docs/lessons-2026-11-27-sandbox-loss.md`). The guest cannot use shadow
stacks anyway. A VM booted from this image prints `Clearing CPUID bits: 16:7`
on its console, and `/proc/cpuinfo` does not list `user_shstk`. The parameter
takes effect at the next boot after provisioning, so the build VM itself runs
without it.

## Validate

Point VeriCAx at the build directory; the file name must be
`CalculiX-2.21.qcow2`:

```bash
VERICAX_IMAGE_DIR="$HOME/vericax-image-build/calculix/out" \
  ./bin/vericax audit --task cae--cli--calculix--task-0001 --group reference
```

A passing L0 plus a fake-agent run is the P3a acceptance evidence. The task
pins were measured on the EngiWorld image; the self-built image must reproduce
`ccx` 2.21 outputs before the pins are considered valid on it. If the exact
`calculix-ccx` package version differs, stop and rebake the pins / re-audit
rather than mixing images.

## Reproducibility

Bit-identical qcow2 files are not expected (UUIDs, timestamps, apt logs).
Reproducibility here means:

1. the base image URL and SHA-256 are pinned and verified;
2. the guest package versions and `ccx -v` output are recorded in
   `image-build.json`;
3. the same audit/L0 results are obtained on the built image;
4. the image SHA-256 is recorded in every run's `summary.json` and L0 record.

## Not in this recipe

- FEniCS/dolfinx 0.10 (`P3b`): Ubuntu 24.04 ships 0.7.3 and the current PPA
  publishes 0.11; matching the EngiWorld 0.10.0.post2 requires archived debs
  or conda-forge, and all pins must be rebaked.
- The merged CalculiX+FEniCS image (`P3c`): depends on the P2 provenance
  sandbox-shape decision (merged image) and a larger build.
- GUI/desktop profile (XFCE, VNC): CLI tasks only need Xvfb and the OSWorld
  server; the v1 GUI channel will need the full desktop profile.

## Licensing

The image contains Ubuntu (various free licenses), CalculiX (GPL-2.0) and the
OSWorld guest server. Distribution of a self-built image is a new artifact;
`docs/spec/06-naming-and-legal.md` applies before publishing it.