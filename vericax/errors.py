"""Error taxonomy shared by the episode lifecycle (spec/03 section 2, spec/09 section 9).

Principle: infra failures are never scored; capability failures are scored.
``agent_error`` was added on 2026-11-18 (spec/08 section 8, T1).
"""
from __future__ import annotations

CAT_ENVIRONMENT_ERROR = "environment_error"
CAT_INFRA_INCOMPLETE = "infra_incomplete"
CAT_TIME_BUDGET = "active_time_budget_exhausted"
CAT_API_INTERRUPTION = "api_interruption"
CAT_AGENT_STALLED = "agent_stalled"
CAT_AGENT_ERROR = "agent_error"

CATEGORIES = (
    CAT_ENVIRONMENT_ERROR,
    CAT_INFRA_INCOMPLETE,
    CAT_TIME_BUDGET,
    CAT_API_INTERRUPTION,
    CAT_AGENT_STALLED,
    CAT_AGENT_ERROR,
)


class EpisodeError(Exception):
    """A classified failure that aborts or shapes the episode.

    ``scored=False`` categories (environment_error, infra_incomplete,
    api_interruption) skip scoring entirely; the episode record then carries
    ``scoring_basis="infra"`` and no capability score.
    """

    def __init__(self, category: str, detail: str, scored: bool = False):
        if category not in CATEGORIES:
            raise ValueError(f"unknown error category: {category}")
        super().__init__(f"[{category}] {detail}")
        self.category = category
        self.detail = detail
        self.scored = scored
