"""Adapter profiles must declare the same limits for the same model.

A stack cuts a model reply at the output limit its profile declares, or at the
stack's own default when the profile declares none. B2 ran dsh with a declared
32,768-token output limit and openclaw with its 8,192 default, so openclaw lost
replies that dsh could finish. These tests read every adapter profile in the
repository and require one set of limits per model id across the stacks.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADAPTERS = REPO / "adapters"


def _dsh_limits() -> dict[str, dict[str, int]]:
    """``adapters/dsh-profile/**/cordis*.yml``: model entries of the llm route."""
    declared: dict[str, dict[str, int]] = {}
    for path in sorted((ADAPTERS / "dsh-profile").rglob("cordis*.yml")):
        model = None
        for line in path.read_text().splitlines():
            entry = re.match(r"^\s*- id:\s*(\S+)\s*$", line)
            field = re.match(r"^\s+(contextWindow|maxTokens):\s*(\d+)\s*$", line)
            if entry:
                model = entry.group(1)
            elif field and model:
                declared.setdefault(model, {})[field.group(1)] = int(field.group(2))
    return declared


def _openclaw_limits() -> dict[str, dict[str, int]]:
    """``adapters/openclaw*-profile/openclaw.json``: providers.<id>.models[]."""
    declared: dict[str, dict[str, int]] = {}
    for path in sorted(ADAPTERS.glob("openclaw*-profile/openclaw.json")):
        providers = json.loads(path.read_text()).get("models", {}).get("providers", {})
        for provider in providers.values():
            for model in provider.get("models", []):
                limits = {k: model[k] for k in ("contextWindow", "maxTokens") if k in model}
                if limits:
                    declared.setdefault(model["id"], {}).update(limits)
    return declared


def _opencode_limits() -> dict[str, dict[str, int]]:
    """``adapters/opencode*-profile/opencode.json``: provider.<id>.models.<id>.limit."""
    declared: dict[str, dict[str, int]] = {}
    for path in sorted(ADAPTERS.glob("opencode*-profile/opencode.json")):
        for provider in json.loads(path.read_text()).get("provider", {}).values():
            for model_id, model in (provider.get("models") or {}).items():
                limit = model.get("limit") or {}
                limits = {"contextWindow": limit["context"], "maxTokens": limit["output"]} if limit else {}
                if limits:
                    declared.setdefault(model_id, {}).update(limits)
    return declared


def declared_limits() -> dict[str, dict[str, dict[str, int]]]:
    """model id -> stack -> limits the stack's profile declares for it."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for stack, limits in (("dsh", _dsh_limits()), ("openclaw", _openclaw_limits()),
                          ("opencode", _opencode_limits())):
        for model_id, fields in limits.items():
            out.setdefault(model_id, {})[stack] = fields
    return out


class AdapterProfileLimitTests(unittest.TestCase):
    def test_one_set_of_limits_per_model(self):
        for model_id, by_stack in sorted(declared_limits().items()):
            distinct = {tuple(sorted(fields.items())) for fields in by_stack.values()}
            self.assertEqual(len(distinct), 1, f"{model_id}: {by_stack}")

    def test_the_b2_model_is_declared_by_all_three_stacks(self):
        by_stack = declared_limits().get("deepseek-v4.1-flash-1017", {})
        self.assertEqual(set(by_stack), {"dsh", "openclaw", "opencode"}, by_stack)
        for stack, fields in by_stack.items():
            self.assertEqual(set(fields), {"contextWindow", "maxTokens"}, (stack, fields))

    def test_dsh_profile_is_read(self):
        # Guards the parser: the dsh profile declares its model with both fields.
        self.assertIn("deepseek-v4.1-flash-1017", _dsh_limits())


if __name__ == "__main__":
    unittest.main()
