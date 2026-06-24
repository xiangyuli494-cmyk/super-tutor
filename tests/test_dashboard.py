"""Tests for student dashboard endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient


class TestDashboard:
    """Dashboard API tests."""

    async def test_dashboard_empty(self, client: TestClient):
        """GET /students/{id}/dashboard — should return empty for new student."""
        resp = client.get("/api/v1/students/unknown-student/dashboard")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["student_id"] == "unknown-student"
        assert data["data"]["total_questions_attempted"] == 0

    async def test_mastery_empty(self, client: TestClient):
        """GET /students/{id}/mastery — should return empty list."""
        resp = client.get("/api/v1/students/unknown-student/mastery")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["items"] == []

    async def test_wrong_questions_empty(self, client: TestClient):
        """GET /students/{id}/wrong-questions — should return empty list."""
        resp = client.get("/api/v1/students/unknown-student/wrong-questions")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["items"] == []

    async def test_today_plan_empty(self, client: TestClient):
        """GET /students/{id}/plan/today — should return empty for new student."""
        resp = client.get("/api/v1/students/unknown-student/plan/today")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["items"] == []
        # Date should be today
        today = datetime.now(timezone.utc).date().isoformat()
        assert data["data"]["date"] == today

    async def test_mastery_with_data(self, client: TestClient, test_db):
        """GET /students/{id}/mastery — should return mastery records."""
        import json
        from uuid import uuid4

        now = datetime.now(timezone.utc).isoformat()
        await test_db.upsert_mastery_record({
            "record_id": str(uuid4()),
            "student_id": "student-1",
            "knowledge_node_id": "node-newton-1",
            "mastery_level": 0.75,
            "confidence": 0.8,
            "total_attempts": 4,
            "correct_attempts": 3,
            "last_attempt_at": now,
            "last_score": 0.75,
            "streak": 1,
            "time_spent_total_seconds": 120,
            "hints_used_total": 1,
            "misconception_ids": "[]",
            "state": "learning",
            "sm2_repetitions": 2,
            "sm2_ease_factor": 2.5,
            "sm2_interval_days": 3,
            "sm2_next_review": now,
            "sm2_last_quality": 4,
            "metadata": "{}",
            "created_at": now,
            "updated_at": now,
        })

        resp = client.get("/api/v1/students/student-1/mastery")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        items = data["data"]["items"]
        assert len(items) >= 1
        assert items[0]["knowledge_node_id"] == "node-newton-1"
        assert items[0]["state"] == "learning"
        assert items[0]["sm2_interval_days"] == 3
