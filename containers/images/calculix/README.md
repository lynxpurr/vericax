# Self-built CalculiX image (D5 / P3a)

Build a CalculiX 2.21 qcow2 from a pinned Ubuntu 24.04 cloud image instead of
reusing the EngiWorld image. This is the P3a deliverable; FEniCS 0.10 and the
merged cross-solver image are P3b/P3c.

## Status (2026-11-20)

The recipe and builder are in place, and a first image was built: Ubuntu
24.04, `ccx` 2.21-1, Xvfb, OSWorld server with `/health` and `/screenshot`
returning 200. **End-to-end `vericax audit` on the self-built image is not yet
green.** The debugging round identified four CLI-only guest requirements that
are now in `provision.sh` but still need a clean full `build.sh` run:

1. generic DHCP netplan (`99-vericax.yaml`) because the runner NIC name differs
   from the build NIC;
2. `x11-xserver-utils` (the desktop preparation calls `xrandr`);
3. a `gnome-screenshot` -> `scrot` shim for pyautogui under Xvfb;
4. `server/main.py` `/run_python` must use `/home/user/venv/bin/python` (the
   action scripts need the venv deps; installing them system-wide conflicted
   with Debian packages).

Do not switch the suite to this image or rebake pins until a clean build passes
`vericax audit --task cae--cli--calculix--task-0001 --group reference` and a
fake-agent run.

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
- The OSWorld server bundle. Default:
  `$HOME/projects/engiworld-playground/engiworld-repo/runtime/engine/desktop_env/server`;
  override with `VERICAX_OSWORLD_SERVER`.

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