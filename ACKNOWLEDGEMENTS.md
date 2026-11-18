# Acknowledgements and third-party notices

## EngiWorld

VeriCAx was designed after a hands-on study of
[EngiWorld](https://arxiv.org/abs/2609.37686) (arXiv:2609.37686), an agent
benchmark for professional engineering environments released under the MIT
license.

What this project takes from it, and how:

| Item | Use here |
|---|---|
| Three-asset layout (Tasks / Images / Runtime) | Structural inspiration for this repository |
| Task definition shape (`config`, `evaluator`, `artifact_paths`) | basis of `docs/spec/01`, extended with `interface`, `integrity_policy`, `limits` |
| Artifact-centric verification and its audit protocol | basis of `docs/spec/02` |
| Evaluation runtime (`engine/desktop_env`, osworld-docker based) | **external dependency**, not vendored — see `docs/setup.md` |
| Public VM images (CalculiX 2.21 among them) | **external dependency**, downloaded from the published dataset |

If you use VeriCAx, please also cite EngiWorld as the origin of several ideas:

```bibtex
@misc{engiworld2026,
  title  = {EngiWorld: What Can Frontier Agents Deliver in Professional Engineering Environments?},
  author = {Gao, Hongcheng and others},
  year   = {2026},
  eprint = {2609.37686},
  archivePrefix = {arXiv}
}
```

## Software used inside evaluation images

The task packages in this repository contain **task definitions and verifier
code only**. They do not redistribute the engineering applications. VM images
are obtained separately and remain subject to each application's own licence:

- CalculiX — GPL
- FEniCS / DOLFIN — LGPL
- OpenFOAM — GPL
- OpenFAST — Apache-2.0
- FLORIS — BSD-3-Clause

Proprietary applications (for example Abaqus or ANSYS) are never distributed
here; tasks that reference them ship with task definitions only.

## Data

Ground-truth artifacts under `tasks/**/ground_truth/` are produced inside the
same VM image used for scoring, and are released under this repository's MIT
licence together with their audit records.
