"""Tests for quiz session lifecycle endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI


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

    # ==================================================================
    # Phase 2: 状态恢复端点测试
    # ==================================================================

    async def test_restore_session_in_memory(self, client: TestClient):
        """POST /restore — 会话已在内存中，返回无需恢复。"""
        material_id = await self._upload_material(client)
        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id, "title": "恢复测试",
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        resp = client.post(f"/api/v1/sessions/{session_id}/restore")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["data"]["state"] == "idle"
        assert "已在内存" in data["message"]

    async def test_restore_nonexistent_session(self, client: TestClient):
        """POST /restore — 不存在的会话 → 404。"""
        resp = client.post("/api/v1/sessions/nonexistent-id/restore")
        assert resp.status_code == 404, resp.text

    async def test_resume_not_paused(self, client: TestClient):
        """POST /resume — 未暂停的会话应返回 409。"""
        material_id = await self._upload_material(client)
        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id, "title": "恢复测试",
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        resp = client.post(f"/api/v1/sessions/{session_id}/resume")
        # 未暂停时 resume 应报错
        assert resp.status_code == 409, resp.text

    async def test_retry_not_in_error(self, client: TestClient):
        """POST /retry — 未处于错误状态的会话应返回 409。"""
        material_id = await self._upload_material(client)
        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id, "title": "重试测试",
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        resp = client.post(f"/api/v1/sessions/{session_id}/retry")
        # 未处于错误状态时 retry 应报错
        assert resp.status_code == 409, resp.text

    async def test_session_persistence_across_restart(
        self, client: TestClient, test_app: "FastAPI",
    ):
        """模拟服务重启：清除注册表后，访问会话应自动从 DB 恢复。

        验证流程：
        1. 创建会话 → DB 持久化
        2. 清除内存注册表（模拟重启）
        3. 访问同一 session_id → 自动从 DB 恢复
        """
        material_id = await self._upload_material(client)

        # 1. 创建会话
        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id, "title": "持久化测试",
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        # 2. 触发流水线（生成题目，写入 DB）
        questions_resp = client.get(f"/api/v1/sessions/{session_id}/questions")
        assert questions_resp.status_code == 200
        state_before = questions_resp.json()["data"]["state"]

        # 3. 模拟服务重启：清空内存注册表
        registry = test_app.state.tutor_orchestrator_registry
        registry.clear()

        # 4. 再次访问 → 应从 DB 自动恢复
        resp = client.get(f"/api/v1/sessions/{session_id}/questions")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # 题目应从 DB 返回（不是重新生成）
        assert data["data"]["question_count"] >= 1
        # 状态应保持一致
        assert data["data"]["state"] == state_before

    async def test_restore_from_db_after_clear(
        self, client: TestClient, test_app: "FastAPI",
    ):
        """POST /restore — 注册表清空后手动恢复，应从 DB 加载。"""
        material_id = await self._upload_material(client)

        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id, "title": "DB 恢复测试",
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        # 清空注册表
        test_app.state.tutor_orchestrator_registry.clear()

        # 手动恢复
        resp = client.post(f"/api/v1/sessions/{session_id}/restore")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["data"]["state"] == "idle"
        assert "已从数据库" in data["message"]

    async def test_create_session_persists_immediately(
        self, client: TestClient, test_app: "FastAPI",
    ):
        """创建会话后立即清空注册表，验证 DB 中有数据。"""
        material_id = await self._upload_material(client)

        create_resp = client.post("/api/v1/sessions", json={
            "material_id": material_id, "title": "立即持久化测试",
            "student_id": "student-1",
        })
        session_id = create_resp.json()["data"]["session_id"]

        # 立即清空注册表（会话只创建了，还没做任何操作）
        test_app.state.tutor_orchestrator_registry.clear()

        # 访问会话 → 应从 DB 自动恢复（IDLE 状态）
        resp = client.get(f"/api/v1/sessions/{session_id}/questions")
        assert resp.status_code == 200, resp.text
        # IDLE 状态应触发流水线启动
        assert resp.json()["data"]["question_count"] >= 1
