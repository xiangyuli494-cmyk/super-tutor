"""Token consumption tracking, budget enforcement, and cost estimation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from super_tutor.core.database import Database
from super_tutor.core.exceptions import VALID_ROLES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DeepSeek pricing per 1M tokens (USD).
# All three tiers use "deepseek-chat" so the unit prices are identical today;
# per-tier entries exist for future model-differentiated pricing.
# ---------------------------------------------------------------------------
_PRICE_PER_MILLION: dict[str, dict[str, float]] = {
    "heavy":  {"prompt": 0.14, "completion": 0.28},
    "medium": {"prompt": 0.14, "completion": 0.28},
    "light":  {"prompt": 0.14, "completion": 0.28},
}

_VALID_TIERS: frozenset[str] = frozenset({"heavy", "medium", "light"})


class TokenTracker:
    """Tracks token consumption per project with budget enforcement.

    Persists every API call to the Database layer and maintains in-memory
    counters so budget queries are fast and do not require a round-trip.

    Attributes:
        budget: Current default token budget applied to all projects.
    """

    def __init__(self, database: Database, budget: int = 50000) -> None:
        """Initialise the tracker.

        Args:
            database: Database instance used to persist ``token_usage`` rows.
            budget: Default token budget per project (can be changed later via
                ``update_budget``).
        """
        self._database: Database = database
        self.budget: int = budget

        # In-memory aggregated counters keyed by project_id.
        # Each inner dict holds ``role:<name>``, ``tier:<name>``, and ``total``.
        self._usage: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record(
        self,
        project_id: str,
        role: str,
        task_id: str,
        model_tier: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Record a single API call's token consumption.

        The record is persisted via ``Database.log_token_usage`` and also
        aggregated in memory for fast retrieval.

        Args:
            project_id: The project that incurred the cost.
            role: AI role that made the call (``"tutor"``, ``"assistant"``,
                ``"evaluator"``).
            task_id: Workflow task identifier for traceability.
            model_tier: Computation tier used (``"heavy"``, ``"medium"``,
                ``"light"``).
            prompt_tokens: Number of input / prompt tokens consumed.
            completion_tokens: Number of output / completion tokens consumed.
        """
        total = prompt_tokens + completion_tokens
        cost = self.estimate_cost(prompt_tokens, completion_tokens, model_tier)
        now = datetime.now(timezone.utc).isoformat()

        await self._database.log_token_usage({
            "project_id": project_id,
            "role": role,
            "task_id": task_id,
            "model": "deepseek-chat",
            "tier": model_tier,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total,
            "cost_estimate": cost,
            "created_at": now,
        })

        # Update in-memory counters.
        counters = self._usage.setdefault(project_id, {})
        counters[f"role:{role}"] = counters.get(f"role:{role}", 0) + total
        counters[f"tier:{model_tier}"] = counters.get(f"tier:{model_tier}", 0) + total
        counters["total"] = counters.get("total", 0) + total

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_stats(self, project_id: str) -> dict[str, Any]:
        """Return aggregated token statistics for a project.

        Uses the database as the source of truth for total consumption and
        per-role breakdown; supplements with in-memory tier counters.

        Args:
            project_id: The project to query.

        Returns:
            A dict with keys:

            * **budget** (*int*) – allocated token budget.
            * **used** (*int*) – total tokens consumed so far.
            * **remaining** (*int*) – budget minus used (never negative).
            * **by_role** (*dict*) – tokens consumed by each AI role.
            * **by_tier** (*dict*) – tokens consumed by each computation tier.
        """
        db_stats = await self._database.get_token_stats(project_id)
        used: int = db_stats.get("total_tokens", 0)  # type: ignore[assignment]

        # Per-role breakdown from the database (authoritative),
        # dynamically derived from VALID_ROLES — no hardcoded role names.
        db_by_role: dict[str, int] = db_stats.get("by_role", {})
        by_role = {role: db_by_role.get(role, 0) for role in sorted(VALID_ROLES)}

        # Per-tier breakdown from in-memory counters (the database does not
        # yet expose a tier-aggregation query).
        mem = self._usage.get(project_id, {})
        by_tier = {
            "heavy": mem.get("tier:heavy", 0),
            "medium": mem.get("tier:medium", 0),
            "light": mem.get("tier:light", 0),
        }

        return {
            "budget": self.budget,
            "used": used,
            "remaining": max(0, self.budget - used),
            "by_role": by_role,
            "by_tier": by_tier,
        }

    async def check_budget(self, project_id: str) -> dict[str, Any]:
        """Check whether the project is within its token budget.

        Args:
            project_id: The project to check.

        Returns:
            A dict with keys:

            * **within_budget** (*bool*) – ``True`` when usage < 100%.
            * **warning** (*bool*) – ``True`` when usage >= 80% (amber alert).
            * **exhausted** (*bool*) – ``True`` when usage >= 100% (red alert).
            * **remaining** (*int*) – tokens still available.
        """
        stats = await self.get_stats(project_id)
        used = stats["used"]
        budget = stats["budget"]

        if budget == 0:
            # Zero budget means no tokens are available; treat as exhausted.
            return {
                "within_budget": False,
                "warning": True,
                "exhausted": True,
                "remaining": 0,
            }

        ratio = used / budget

        return {
            "within_budget": ratio < 1.0,
            "warning": ratio >= 0.8,
            "exhausted": ratio >= 1.0,
            "remaining": stats["remaining"],
        }

    # ------------------------------------------------------------------
    # Budget management
    # ------------------------------------------------------------------

    def update_budget(self, new_budget: int) -> None:
        """Replace the default token budget for all projects.

        Args:
            new_budget: The new token cap (non-negative integer).
        """
        if new_budget < 0:
            raise ValueError("Budget must be a non-negative integer")
        self.budget = new_budget
        logger.info("Token budget updated to %d", new_budget)

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_cost(
        prompt_tokens: int,
        completion_tokens: int,
        tier: str,
    ) -> float:
        """Estimate the USD cost of an API call based on DeepSeek pricing.

        Args:
            prompt_tokens: Number of prompt / input tokens.
            completion_tokens: Number of completion / output tokens.
            tier: Computation tier (``"heavy"``, ``"medium"``, ``"light"``).

        Returns:
            Estimated cost in USD, rounded to 6 decimal places.

        Raises:
            ValueError: If *tier* is not a recognised tier.
        """
        if tier not in _VALID_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}'. Expected one of: {sorted(_VALID_TIERS)}"
            )
        prices = _PRICE_PER_MILLION[tier]
        prompt_cost = (prompt_tokens / 1_000_000) * prices["prompt"]
        completion_cost = (completion_tokens / 1_000_000) * prices["completion"]
        return round(prompt_cost + completion_cost, 6)
