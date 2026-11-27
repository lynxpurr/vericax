# Self-built FEniCS image (D5 / P3b)

Build a FEniCS (dolfinx 0.10.0.post2) qcow2 from a pinned Ubuntu 24.04 cloud
image instead of reusing the EngiWorld image. This is the P3b deliverable,
sibling of `containers/images/calculix/` (P3a); the merged cross-solver image
is P3c.

## Route: why rebuild from upstream tags

The EngiWorld reference `FEniCS.qcow2` (probed read-only on 2026-11-21 via a
throwaway overlay) pins dolfinx **0.10.0.post2** installed from
`ppa:fenics-packages/fenics` into the Debian petsc layout
(`/usr/lib/petsc/lib/python3/dist-packages/dolfinx`). Its inventory:

| package | reference version | source |
|---|---|---|
| fenics-dolfinx (module `dolfinx.__version__`) | 0.10.0.post2 | PPA deb `1:0.10.0.post3-2~ppa2~noble7` |
| fenics-basix | 0.10.0.post0 | PPA deb `0.10.0.post0-2~ppa2~noble1` |
| fenics-ffcx | 0.10.1.post0 | PPA deb `1:0.10.1.post0-1~ppa1~noble1` |
| fenics-ufl | 2025.2.1 | PPA deb `2025.2.1-2~ppa1~noble2` |
| petsc4py / petsc | 3.19.6 / 3.19.6+dfsg1 | noble archive |
| slepc4py / slepc | 3.19.2 / 3.19.2+dfsg1 | noble archive |
| gmsh / python3-gmsh | 4.12.1 | noble archive |
| meshio | 5.3.5 (`7.0.0-really-5.3.5-1`) | noble archive |
| adios2 | 2.10.2+dfsg1 | PPA (still published) |
| numpy / mpi4py | 1.26.4 / 3.1.5 | noble archive |
| OS | Ubuntu 24.04, kernel 6.8.0-55 | — |

The PPA's 0.10 **python-binding** debs (`python3-dolfinx*`, `python3-basix`,
`python3-ufl`, `python3-ffcx`, `*-dev`) are superseded by 0.11 and **deleted
from the Launchpad pool** — not recoverable. Only the soname-versioned C++
libs (`libdolfinx-real0.10`, `libbasix0.10`, docs) survive there, and Debian
never shipped 0.10.0.post3 (trixie has 0.9.0-7, sid 0.11.0.post0-8).

The reproducible route (chosen 2026-11-21, recorded in `image-build.json`):

1. apt pins at the exact reference library versions: petsc 3.19.6, slepc
   3.19.2, gmsh 4.12.1, meshio 5.3.5, openmpi 4.1.6, h5py 3.10.0, numpy
   1.26.4 (all noble archive) + adios2 2.10.2 (PPA, key pinned by sha256,
   fingerprint `6C1DA1C0EC4B649179C1C7437C3297BD11D01687`).
2. ufl/ffcx/basix/dolfinx built from pinned upstream git tags:

| project | tag | sha256 of codeload tarball |
|---|---|---|
| ufl | `2025.2.1` (`902582a2…`) | `259812d3…914893` |
| ffcx | `v0.10.1.post0` (`009c0e75…`) | `ea9b22b6…8413b7` |
| basix | `v0.10.0.post0` (`433fb7f6…`) | `94cbc8bb…7026` |
| dolfinx | `v0.10.0.post2` (`fbc8e779…`) | `5993bc85…22352` |

dolfinx uses **v0.10.0.post2** (not post3): `dolfinx.__version__` comes from
`importlib.metadata` (`version("fenics-dolfinx")`), and the tag's
`python/pyproject.toml` bakes `0.10.0.post2` — exactly the string the
reference image reports. The reference deb's changelog string
(`0.10.0.post3-2~ppa2~noble7`) is a Debian-revision naming artifact.

3. The pip build stack (`scikit-build-core`, `nanobind`) versions are
   build-only (binding marshalling, no numerics); the actual installed
   versions are recorded in `image-build.txt` inside the image and
   `image-build.json` on the build host.

## Guest contract

Identical to the calculix recipe (user `user` / `password`, sudo, Xvfb
1920x1080, OSWorld server on port 5000, the same netplan/xrandr/scrot/
python3-shim fixes). The `python3` shim routes to
`venv --system-site-packages`, which sees both pip pyautogui and the
apt/pip dolfinx stack — the same interpreter chain the OSWorld controller
and the verifiers use. Provision asserts the reference inventory and runs a
small Poisson solve (PETSc assembly) before finishing.

## Build

```bash
./containers/images/fenics/build.sh
```

Prerequisites are the same as the calculix recipe (Docker with /dev/kvm, the
OSWorld server bundle via `VERICAX_OSWORLD_SERVER`, see `docs/setup.md`
section 2). The host downloads/verifies the pinned tarballs
(sha256 above), the PPA key, and the base image, then provisions in QEMU.
Output (not committed):

```
$HOME/vericax-image-build/fenics/out/FEniCS.qcow2
$HOME/vericax-image-build/fenics/out/FEniCS.qcow2.sha256
$HOME/vericax-image-build/fenics/out/image-build.json
$HOME/vericax-image-build/fenics/out/provision-info.txt
```

## Status (2026-11-21): P3b accepted

**Rebuilt on 2026-11-27** from this recipe with `clearcpuid=519` on the kernel
command line (see below): `FEniCS.qcow2`, SHA-256
`ff6d3b5ef7bf7be00fec4c483bc000256412bb35f1049a9657886e6f9780dad0`, 2.21 GB. The recorded package versions are identical to the
2026-11-21 build; the suite's 26 packages were re-audited on the rebuilt images.

A **fresh clean build from this recipe** produced a CLI-only Ubuntu 24.04
image with dolfinx 0.10.0.post2 (2.19 GB qcow2, vs the 17 GB desktop-profile
reference) and passed both gates on 2026-11-21:

- `vericax audit --task cae--cli--fenics--task-0001 --group reference`:
  passed — `summary_matched=true`, observed summary
  `308.464544, 0.050083` **exactly equals** the baked pins (the self-built
  image reproduces the reference numerics to the last digit);
- fake-agent run (`tests/run_acceptance.py` payload, mode=solve): score 1.0,
  `native_evaluator`, `reference_selfcheck=pass`, sandbox+scoring network
  isolation true, `image_sha256` matching the image.

Image under test: `FEniCS.qcow2`, SHA-256
`b0e2f239f4bc3fa5b20f09d53c8761128a11cf2e26bab2506f295157a00cebc4`.
Evidence in `~/vericax-image-build/fenics/out/` (`image-build.json`,
`provision-info.txt`, `l0-selfbuilt-task-0001.json`,
`smoke-selfbuilt-task-0001.json`); not committed.

Three recipe lessons from the first builds (all fixed in `provision.sh`):

1. `cmake --install` into `/usr/local/lib` does not refresh the loader cache
   in the guest: `import basix` failed with
   `libbasix.so: cannot open shared object file` until an explicit
   `sudo ldconfig` was added after the installs.
2. The task artifact contract and the episode agent `working_dir` are
   `/home/user/Desktop`; the desktop-profile reference image ships it, the
   CLI-only cloud image does not. `provision.sh` creates it explicitly.
3. nanobind must be pinned to 2.9.x: the reference deb was built against
   nanobind 2.9.2, and nanobind 2.15 type-casters reject the
   `Form_float64(form_ints, ...)` call shape the dolfinx python layer uses.

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

```bash
VERICAX_IMAGE="$HOME/vericax-image-build/fenics/out/FEniCS.qcow2" \
  ./bin/vericax audit --task cae--cli--fenics--task-0001 --group reference
```

A passing L0 plus a fake-agent run on the built image is the P3b acceptance
evidence, recorded separately (never overwriting the EngiWorld evidence).

## Not in this recipe

- The merged CalculiX+FEniCS image (`P3c`) and the four
  `software-selection` tasks that need it.
- Switching the suite default to this image = re-bake pins + re-audit every
  FEniCS task on the new image (spec/04; not done here — the suite still
  runs on EngiWorld images).
- GUI/desktop profile: CLI-only, as P3a.
