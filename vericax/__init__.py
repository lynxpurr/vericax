"""VeriCAx eval harness (spec/08-09, Phase 1).

The package implements the episode lifecycle prepare -> run -> freeze -> score
-> record on top of the external EngiWorld-compatible runtime. Per-stack
behavior lives exclusively in ``adapters/<stack>.toml``; the lifecycle modules
must stay stack-agnostic (A1, spec/08).
"""

__version__ = "0.2.1-alpha"
