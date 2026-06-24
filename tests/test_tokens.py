"""Tests for token usage statistics endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestTokens:
    """Token stats API tests."""

    async def test_token_stats_empty(self, client: TestClient):
        """GET /tokens/stats — should return zero stats with budget fields."""
        resp = client.get("/api/v1/tokens/stats")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        d = data["data"]
        assert d["total_tokens"] == 0
        assert d["call_count"] == 0
        # P2-5 fields
        assert "budget" in d
        assert "used" in d
        assert "remaining" in d
        assert "by_tier" in d
        assert d["by_role"]["tutor"] == 0

    async def test_token_stats_with_data(self, client: TestClient, test_db):
        """GET /tokens/stats?project_id=test — should return usage stats."""
        from datetime import datetime, timezone

        # Insert some test token usage data
        now = datetime.now(timezone.utc).isoformat()
        await test_db.log_token_usage({
            "project_id": "test-project",
            "role": "tutor",
            "tier": "medium",
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
            "created_at": now,
        })
        await test_db.log_token_usage({
            "project_id": "test-project",
            "role": "evaluator",
            "tier": "heavy",
            "prompt_tokens": 2000,
            "completion_tokens": 800,
            "total_tokens": 2800,
            "created_at": now,
        })

        resp = client.get("/api/v1/tokens/stats?project_id=test-project")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        d = data["data"]
        assert d["total_tokens"] >= 1500
        assert d["call_count"] >= 1
        assert d["total_prompt_tokens"] >= 1000
        assert d["total_completion_tokens"] >= 500
