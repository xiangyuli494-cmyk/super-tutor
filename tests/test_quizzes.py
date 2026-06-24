"""Tests for quiz session lifecycle endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestQuizSessions:
    """Quiz session API tests."""

    async def _upload_material(self, client: TestClient) -> str:
        """Helper: upload a material and return its material_id."""
        resp = client.post("/api/v1/materials/upload", json={
            "title": "物理测验材料",
            "content": "牛顿第一定律：物体在不受外力作用时，保持静止或匀速直线运动状态。\n牛顿第二定律：F=ma。\n牛顿第三定律：作用力与反作用力大小相等、方向相反。",
            "subject": "物理",
        })
        assert resp.status_code == 201
        return resp.json()["data"]["material_id"]

    async def test_create_session(self, client: TestClient):
        """POST /api/v1/sessions — should create a new quiz session."""
        material_id = await self._upload_material(client)

        resp = client.post("/api/v1/sessions", json={
            "material_id": material_id,
            "title": "牛顿定律测验",
            "question_count": 2,
            "difficulty": "medium",
            "student_id": "student-1",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["session_id"] != ""
        assert data["data"]["material_id"] == material_id
        assert data["data"]["state"] == "idle"

    async def test_create_session_missing_material(self, client: TestClient):
        """POST /api/v1/sessions with nonexistent material_id → 404."""
        resp = client.post("/api/v1/sessions", json={
            "material_id": "nonexistent-material",
            "title": "测试",
        })
        assert resp.status_code == 404, resp.text

    async def test_get_questions(self, client: TestClient):
        """GET /api/v1/sessions/{id}/questions — should return questions."""
        material_id = await self._upload_material(client)
        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id,
            "title": "测验",
            "question_count": 2,
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        resp = client.get(f"/api/v1/sessions/{session_id}/questions")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        questions = data["data"]["questions"]
        assert len(questions) >= 1
        # Questions must not expose correct_answer
        for q in questions:
            assert "correct_answer" not in q
            assert "question_id" in q
            assert "stem" in q

    async def test_submit_answers(self, client: TestClient):
        """POST /api/v1/sessions/{id}/answers — should accept answers."""
        material_id = await self._upload_material(client)
        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id,
            "title": "测验",
            "question_count": 2,
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        # Get questions first
        questions_resp = client.get(f"/api/v1/sessions/{session_id}/questions")
        questions = questions_resp.json()["data"]["questions"]

        # Submit answers
        answers = [
            {
                "question_id": q["question_id"],
                "student_answer": "B",
                "time_spent_seconds": 30,
                "hints_used": 0,
                "attempt_number": 1,
            }
            for q in questions
        ]

        resp = client.post(
            f"/api/v1/sessions/{session_id}/answers",
            json={"answers": answers},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["accepted_count"] == len(answers)

    async def test_get_results(self, client: TestClient):
        """GET /api/v1/sessions/{id}/results — should return graded results."""
        material_id = await self._upload_material(client)
        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id,
            "title": "测验",
            "question_count": 2,
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        # Get questions
        questions_resp = client.get(f"/api/v1/sessions/{session_id}/questions")
        questions = questions_resp.json()["data"]["questions"]

        # Submit answers
        answers = [
            {
                "question_id": q["question_id"],
                "student_answer": "B",
                "time_spent_seconds": 30,
                "hints_used": 0,
                "attempt_number": 1,
            }
            for q in questions
        ]
        client.post(
            f"/api/v1/sessions/{session_id}/answers",
            json={"answers": answers},
        )

        # Get results
        resp = client.get(f"/api/v1/sessions/{session_id}/results")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert "attempts" in data["data"]
        assert len(data["data"]["attempts"]) >= 1

    async def test_generate_plan(self, client: TestClient):
        """POST /api/v1/sessions/{id}/plan — should generate a study plan."""
        material_id = await self._upload_material(client)
        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id,
            "title": "测验",
            "question_count": 2,
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        # Get questions
        questions_resp = client.get(f"/api/v1/sessions/{session_id}/questions")
        questions = questions_resp.json()["data"]["questions"]

        # Submit answers
        answers = [
            {
                "question_id": q["question_id"],
                "student_answer": "B",
                "time_spent_seconds": 30,
                "hints_used": 0,
                "attempt_number": 1,
            }
            for q in questions
        ]
        client.post(
            f"/api/v1/sessions/{session_id}/answers",
            json={"answers": answers},
        )

        # Generate plan
        resp = client.post(f"/api/v1/sessions/{session_id}/plan")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert "plan_items" in data["data"]
        assert len(data["data"]["plan_items"]) >= 1

    async def test_nonexistent_session(self, client: TestClient):
        """GET questions for nonexistent session → 404."""
        resp = client.get("/api/v1/sessions/nonexistent-session/questions")
        assert resp.status_code == 404, resp.text
