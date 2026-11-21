# Merged cross-solver image (D5 / P3c)

Build one qcow2 that carries **both** solvers — CalculiX 2.21 and dolfinx
0.10.0.post2 — on a single Ubuntu 24.04 base. This is the P3c deliverable and
the sandbox for the four `software-selection` tasks
(`cae--cli--cross-solver--task-0002…0005`). The single `snapshot` / single
sandbox / single proxy contract makes one merged image the only viable shape
(P2 decision, spec/02 §1).

## Route

The image is the union of the two validated recipes:

- `containers/images/calculix/` (P3a): apt `calculix-ccx=2.21-1`, the CLI-only
  OSWorld guest fixes, Xvfb + osworld services.
- `containers/images/fenics/` (P3b): the dolfinx 0.10.0.post2 stack rebuilt
  from pinned upstream tags against apt-pinned noble libraries (see that
  recipe's README for the full rationale — the fenics PPA's 0.10
  python-binding debs are superseded and deleted from the pool).

`provision.sh` here is the P3b provision with the CalculiX package added and
both inventories asserted: the dolfinx version table must match the EngiWorld
reference exactly, and `ccx -v` must report 2.21. Two quirks captured in the
script:

1. `ccx -v` prints its version and exits 201, and through a pipe its stdout
   is lost (the exit path skips the stdio flush). Capture it through a file
   and `grep -m1 Version`.
2. A CalculiX static step needs an explicit `*STATIC` card; the provision
   smoke job exercises a real `ccx` solve before powering off.

## Build

```bash
./containers/images/merged/build.sh
```

Prerequisites are the same as the other recipes (Docker with `/dev/kvm`, the
OSWorld server bundle). Output (not committed):

```
$HOME/vericax-image-build/merged/out/VeriCAx-merged.qcow2
$HOME/vericax-image-build/merged/out/VeriCAx-merged.qcow2.sha256
$HOME/vericax-image-build/merged/out/image-build.json
$HOME/vericax-image-build/merged/out/provision-info.txt
```

## Status (2026-11-21): P3c accepted

Image under test: `VeriCAx-merged.qcow2`, SHA-256
`e6514410ac15646954cb1d4cf4cb86f5ae0b2491f9b5cc43fc13e4af3c81a262`
(2.30 GB). Validation evidence:

- L0 on all three families against the merged image:
  `cae--cli--calculix--task-0001` (observed `-0.05981791, -0.3463916` = pins),
  `cae--cli--fenics--task-0001` (observed `308.464544, 0.050083` = pins,
  `solver_version 0.10.0.post2`), and the L6 prototype
  `cae--cli--cross-solver--task-0001` (observed `-0.191155` = pin).
- The four `software-selection` tasks (cross-solver task-0002…0005) were
  authored and audited on this image: each audit 15/15 (4 positives,
  including two legal alternative submissions) with robust 10/10, L0 pass,
  and fake-agent smoke 1.0.
- Evidence kept outside the repo under `~/vericax-image-build/merged/out/`.

The suite's existing tasks still run the EngiWorld images; the merged image
is used by the `v0.2-cae-cli-merged` split. Switching any default image still
requires re-baking pins and re-auditing every task on it (spec/04 §6).

## Not in this recipe

- P4 multi-VM-per-task scheduling and the per-episode challenge-token
  plumbing (`VERICAX_CHALLENGE`/`VERICAX_TOOL`, spec/09); the SS tasks use
  fixed audit tokens like the L6 prototype.
- GUI/desktop profile: CLI-only, as P3a/P3b.