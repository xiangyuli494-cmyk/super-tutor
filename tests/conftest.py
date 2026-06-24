"""Pytest fixtures and test doubles for the Super Tutor test suite."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from super_tutor.config import TutorConfig
from super_tutor.core.database import Database
from super_tutor.core.token_tracker import TokenTracker
from super_tutor.routes.dashboard import router as dashboard_router
from super_tutor.routes.dependencies import (
    build_orchestrator,
    use_db,
    use_llm_client,
    use_orchestrator_registry,
    use_role_manager,
    use_token_tracker,
)
from super_tutor.routes.materials import router as materials_router
from super_tutor.routes.quizzes import router as quizzes_router
from super_tutor.routes.tokens import router as tokens_router

logger = logging.getLogger(__name__)


# ======================================================================
# Fake LLM Client
# ======================================================================


class FakeLLMClient:
    """A test double that returns canned JSON responses.

    Each method mimics ``LLMClient.chat_with_file_context`` but returns
    pre-defined JSON strings that match the expected Pydantic schemas.
    The response is selected based on keywords in the user message.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat_with_file_context(
        self,
        *,
        role: str = "",
        user_message: str = "",
        files: Optional[list[str]] = None,
        tier: str = "medium",
        system_prompt: Optional[str] = None,
    ) -> str:
        """Return canned JSON based on call sequence (role + call count).

        The orchestrator always follows a fixed call order:
        1. tutor → chunks   (PARSING)
        2. assistant → questions (QUIZ_GEN)
        3. evaluator → attempts + misconceptions (EVALUATING)
        4. tutor → plan_items (PLANNING)
        """
        self.calls.append({
            "role": role,
            "user_message": user_message[:200],
            "tier": tier,
        })
        call_index = len(self.calls)  # 1-based

        # ── Call 1: tutor (PARSING) → knowledge chunks ─────────────────
        if call_index == 1 or (role == "tutor" and call_index <= 2):
            return json.dumps({
                "chunks": [
                    {
                        "chunk_id": "chunk-001",
                        "content": "牛顿第一定律：物体在不受外力作用时，保持静止或匀速直线运动状态。",
                        "topic": "牛顿运动定律",
                        "difficulty": "medium",
                        "keywords": ["牛顿第一定律", "惯性"],
                        "knowledge_node_ids": ["node-newton-1"],
                    },
                    {
                        "chunk_id": "chunk-002",
                        "content": "牛顿第二定律：F=ma，物体的加速度与合外力成正比，与质量成反比。",
                        "topic": "牛顿运动定律",
                        "difficulty": "medium",
                        "keywords": ["牛顿第二定律", "力", "加速度", "质量"],
                        "knowledge_node_ids": ["node-newton-2"],
                    },
                    {
                        "chunk_id": "chunk-003",
                        "content": "牛顿第三定律：作用力与反作用力大小相等、方向相反、作用在同一直线上。",
                        "topic": "牛顿运动定律",
                        "difficulty": "easy",
                        "keywords": ["牛顿第三定律", "作用力", "反作用力"],
                        "knowledge_node_ids": ["node-newton-3"],
                    },
                ]
            }, ensure_ascii=False)

        # ── Call 2: assistant (QUIZ_GEN) → questions ───────────────────
        if role == "assistant" or call_index == 2:
            return json.dumps({
                "questions": [
                    {
                        "question_id": "q-001",
                        "stem": "一个物体在光滑水平面上以恒定速度运动，这说明什么？",
                        "type": "multiple_choice",
                        "difficulty": "medium",
                        "topic": "牛顿运动定律",
                        "knowledge_node_ids": ["node-newton-1"],
                        "options": [
                            {"key": "A", "text": "物体受到平衡力"},
                            {"key": "B", "text": "物体不受任何外力"},
                            {"key": "C", "text": "物体受到恒定的外力"},
                            {"key": "D", "text": "无法判断"},
                        ],
                        "correct_answer": "B",
                        "explanation": "根据牛顿第一定律，光滑水平面意味着没有摩擦力，匀速运动说明不受外力。",
                        "hints": ["想想牛顿第一定律的内容", "光滑意味着什么？"],
                        "points": 5.0,
                        "estimated_seconds": 60,
                    },
                    {
                        "question_id": "q-002",
                        "stem": "一个质量为2kg的物体，受到10N的合外力，其加速度是多少？",
                        "type": "short_answer",
                        "difficulty": "medium",
                        "topic": "牛顿运动定律",
                        "knowledge_node_ids": ["node-newton-2"],
                        "options": [],
                        "correct_answer": "5 m/s²",
                        "explanation": "根据F=ma，a=F/m=10/2=5 m/s²。",
                        "hints": ["回想牛顿第二定律的公式", "F=ma"],
                        "points": 5.0,
                        "estimated_seconds": 45,
                    },
                ]
            }, ensure_ascii=False)

        # ── Call 3: evaluator (EVALUATING) → attempts + misconceptions ─
        if role == "evaluator" or call_index == 3:
            return json.dumps({
                "attempts": [
                    {
                        "attempt_id": "att-001",
                        "question_id": "q-001",
                        "student_answer": "B",
                        "is_correct": True,
                        "score": 5.0,
                        "correct_answer": "B",
                        "explanation": "正确！牛顿第一定律说明匀速运动不需要力的维持。",
                    },
                    {
                        "attempt_id": "att-002",
                        "question_id": "q-002",
                        "student_answer": "10",
                        "is_correct": False,
                        "score": 0.0,
                        "correct_answer": "5 m/s²",
                        "explanation": "公式F=ma中，需要做除法运算，你用乘法得出的结果是错误的。",
                    },
                ],
                "misconceptions": [
                    {
                        "tag_id": "misc-001",
                        "knowledge_node_id": "node-newton-2",
                        "label": "力与加速度混淆",
                        "description": "学生混淆了力与加速度的概念，直接将力当作加速度。",
                        "severity": "medium",
                    },
                ],
            }, ensure_ascii=False)

        # ── Call 4+: tutor again (PLANNING) → plan items ───────────────
        return json.dumps({
            "plan_items": [
                {
                    "item_id": "plan-item-001",
                    "knowledge_node_id": "node-newton-2",
                    "activity_type": "review",
                    "estimated_minutes": 15,
                    "notes": "复习牛顿第二定律 F=ma，重点练习除法运算",
                },
                {
                    "item_id": "plan-item-002",
                    "knowledge_node_id": "node-newton-1",
                    "activity_type": "practice",
                    "estimated_minutes": 20,
                    "notes": "做3道牛顿第一定律相关选择题",
                },
            ],
            "summary": "本周重点复习牛顿第二定律，强化公式运用。",
        }, ensure_ascii=False)


# ======================================================================
# Pytest fixtures
# ======================================================================


@pytest.fixture
def test_db_path(tmp_path: Path) -> str:
    """Create a temporary database file path.

    Uses pytest's ``tmp_path`` fixture so the parent directory always
    exists (required by ``Database._validate_db_path``).
    """
    return str(tmp_path / "test_super_tutor.db")


@pytest.fixture
async def test_db(test_db_path: str) -> Database:
    """Create and initialise an isolated test database."""
    config = TutorConfig()
    db = Database(db_path=test_db_path, config=config)
    await db.initialize()
    yield db
    await db.close()


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    """Create a FakeLLMClient for canned responses."""
    return FakeLLMClient()


@pytest.fixture
def test_app(test_db: Database, fake_llm: FakeLLMClient) -> FastAPI:
    """Build a FastAPI test application with dependency overrides.

    All routes are mounted and heavy dependencies (Database, LLMClient,
    TokenTracker, RoleManager) are replaced with test doubles.
    """
    from super_tutor.core.role_manager import RoleManager

    app = FastAPI()

    # Include all routers
    app.include_router(materials_router)
    app.include_router(quizzes_router)
    app.include_router(dashboard_router)
    app.include_router(tokens_router)

    # Shared test state
    app.state.tutor_database = test_db
    app.state.tutor_orchestrator_registry = {}
    app.state.tutor_token_tracker = TokenTracker(database=test_db, budget=100000)

    # Override LLM client → fake
    app.dependency_overrides[use_llm_client] = lambda: fake_llm

    # Override DB → test DB
    app.dependency_overrides[use_db] = lambda: test_db

    # Override token tracker
    def _get_tracker():
        return app.state.tutor_token_tracker

    app.dependency_overrides[use_token_tracker] = _get_tracker

    # RoleManager (real — prompts are on disk)
    prompts_dir = Path(__file__).resolve().parent.parent / "super_tutor" / "prompts"
    role_mgr = RoleManager(prompts_dir=str(prompts_dir))
    app.state.tutor_role_manager = role_mgr
    app.dependency_overrides[use_role_manager] = lambda: role_mgr

    # Registry
    app.dependency_overrides[use_orchestrator_registry] = (
        lambda: app.state.tutor_orchestrator_registry
    )

    return app


@pytest.fixture(autouse=True)
def reset_limiter() -> None:
    """Reset rate limiter storage before each test to avoid 429 errors.

    slowapi uses a global in-memory store shared across all tests.
    Without this reset, tests that call rate-limited endpoints
    (e.g. POST /api/v1/materials/upload) will fail after 10 calls.
    """
    from super_tutor.core.limiter import limiter

    limiter._storage.reset()


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create a synchronous TestClient for the test app."""
    return TestClient(test_app)
