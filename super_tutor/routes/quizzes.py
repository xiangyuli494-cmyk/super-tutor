"""Super Tutor — 测验路由。

直接调用 QuizEngine 完成题目生成、自动批改与错题收录。
不再依赖 Orchestrator 状态机。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from super_tutor.core.database import Database
from super_tutor.core.llm_client import LLMClient
from super_tutor.engine.knowledge_engine import KnowledgeEngine
from super_tutor.engine.quiz_engine import QuizEngine
from super_tutor.routes.deps import use_db, use_llm_client
from super_tutor.models.enums import DifficultyLevel, QuestionType
from super_tutor.models.quiz import Question
from super_tutor.routes.schemas import (
    APIResponse,
    AttemptResponse,
    CreateQuizRequest,
    QuestionResponse,
    QuizResultResponse,
    SubmitAnswersRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/quizzes", tags=["quizzes"])


# ===================================================================
# Helpers
# ===================================================================


def _build_quiz_engine(db: Database, llm: LLMClient) -> QuizEngine:
    """Construct a QuizEngine with a KnowledgeEngine wired in."""
    knowledge_engine = KnowledgeEngine(db=db, llm_client=llm)
    return QuizEngine(db=db, llm_client=llm, knowledge_engine=knowledge_engine)


def _strip_correct_answer(q: Question) -> dict:
    """Convert a Question to a safe dict (no correct answer)."""
    return QuestionResponse(
        question_id=q.question_id,
        stem=q.stem,
        type=q.type.value,
        difficulty=q.difficulty.value,
        topic=q.topic,
        kp_id=q.kp_id,
        options=q.options,
        hints=q.hints,
        points=q.points,
        estimated_seconds=q.estimated_seconds,
    ).model_dump()


# ===================================================================
# POST /generate — 生成题目
# ===================================================================


@router.post("/generate", response_model=APIResponse, status_code=201)
async def generate_quiz(
    req: CreateQuizRequest,
    db: Database = Depends(use_db),
    llm: LLMClient = Depends(use_llm_client),
) -> APIResponse:
    """生成测验题目。

    根据指定的知识点、数量、难度和题型生成题目。
    返回不含正确答案的题目列表（防止前端抓包作弊）。
    """
    quiz_engine = _build_quiz_engine(db, llm)

    try:
        questions = await quiz_engine.generate_questions(
            kp_ids=req.kp_ids,
            count=req.count,
            difficulty=req.difficulty,
            types=req.types,
        )
    except Exception as exc:
        logger.exception("Question generation failed")
        raise HTTPException(status_code=500, detail=f"题目生成失败: {exc}") from exc

    safe_questions = [_strip_correct_answer(q) for q in questions]

    return APIResponse(
        data={
            "count": len(safe_questions),
            "questions": safe_questions,
        }
    )


# ===================================================================
# POST /grade — 提交作答并批改
# ===================================================================


@router.post("/grade", response_model=APIResponse)
async def grade_answers(
    req: SubmitAnswersRequest,
    db: Database = Depends(use_db),
    llm: LLMClient = Depends(use_llm_client),
) -> APIResponse:
    """提交作答并自动批改。

    对选择题/判断题进行程序批改，其余题型送 LLM 批改。
    错题自动录入错题本。
    """
    quiz_engine = _build_quiz_engine(db, llm)

    # -- Fetch question objects by IDs ------------------------------------
    question_ids = [a.question_id for a in req.answers]
    question_map = await db.get_questions_batch(question_ids)

    if not question_map:
        raise HTTPException(status_code=404, detail="未找到对应题目。")

    questions: list[Question] = []
    for row in question_map.values():
        options_raw = row.get("options", "[]")
        if isinstance(options_raw, str):
            import json as _json

            try:
                options = _json.loads(options_raw)
            except (_json.JSONDecodeError, TypeError):
                options = []
        else:
            options = options_raw

        questions.append(
            Question(
                question_id=row["question_id"],
                type=QuestionType(row.get("type", "multiple_choice")),
                difficulty=DifficultyLevel(row.get("difficulty", "medium")),
                subject=row.get("subject", ""),
                topic=row.get("topic", ""),
                stem=row.get("stem", ""),
                options=options,
                correct_answer=row.get("correct_answer", ""),
                explanation=row.get("explanation", ""),
                kp_id=row.get("kp_id", ""),
                estimated_seconds=row.get("estimated_seconds", 120),
                points=row.get("points", 1.0),
                tags=[],
            )
        )

    # -- Grade ------------------------------------------------------------
    student_answers = [
        {
            "question_id": a.question_id,
            "student_answer": a.student_answer,
            "time_spent_seconds": a.time_spent_seconds,
        }
        for a in req.answers
    ]

    try:
        attempts = await quiz_engine.grade_answers(
            questions=questions,
            student_answers=student_answers,
            student_id=req.student_id,
        )
    except Exception as exc:
        logger.exception("Grading failed")
        raise HTTPException(status_code=500, detail=f"批改失败: {exc}") from exc

    # -- Add wrong answers to wrong book ----------------------------------
    q_map = {q.question_id: q for q in questions}
    wrong_count = 0
    for attempt in attempts:
        if attempt.is_correct is False:
            try:
                await quiz_engine.add_to_wrong_book(
                    attempt, q_map.get(attempt.question_id)
                )
                wrong_count += 1
            except Exception as exc:
                logger.warning(
                    "Failed to add wrong-book entry for %s: %s",
                    attempt.attempt_id,
                    exc,
                )

    # -- Build response ---------------------------------------------------
    correct_count = sum(1 for a in attempts if a.is_correct)
    total = len(attempts)

    attempt_dicts = [
        AttemptResponse(
            attempt_id=a.attempt_id,
            question_id=a.question_id,
            kp_id=a.kp_id,
            student_answer=a.student_answer,
            is_correct=a.is_correct,
            time_spent_seconds=a.time_spent_seconds,
        ).model_dump()
        for a in attempts
    ]

    return APIResponse(
        data=QuizResultResponse(
            attempts=attempt_dicts,
            correct_count=correct_count,
            total_count=total,
            accuracy=round(correct_count / total, 3) if total > 0 else 0.0,
        ).model_dump()
    )


# ===================================================================
# GET /questions — 按 ID 批量查询题目（不含正确答案）
# ===================================================================


@router.get("/questions", response_model=APIResponse)
async def get_questions(
    ids: str = "",
    db: Database = Depends(use_db),
) -> APIResponse:
    """按 ID 批量获取题目（不含正确答案）。

    Query params:
        ids: 逗号分隔的 question_id 列表
    """
    if not ids:
        raise HTTPException(status_code=400, detail="请提供 ids 参数（逗号分隔的 question_id）。")

    qids = [qid.strip() for qid in ids.split(",") if qid.strip()]
    if not qids:
        raise HTTPException(status_code=400, detail="ids 参数不能为空。")

    q_map = await db.get_questions_batch(qids)

    safe_questions: list[dict] = []
    for row in q_map.values():
        options_raw = row.get("options", "[]")
        if isinstance(options_raw, str):
            import json as _json

            try:
                options = _json.loads(options_raw)
            except (_json.JSONDecodeError, TypeError):
                options = []
        else:
            options = options_raw

        safe_questions.append(
            QuestionResponse(
                question_id=row["question_id"],
                stem=row.get("stem", ""),
                type=row.get("type", "multiple_choice"),
                difficulty=row.get("difficulty", "medium"),
                topic=row.get("topic", ""),
                kp_id=row.get("kp_id", ""),
                options=options,
                hints=[],
                points=row.get("points", 1.0),
                estimated_seconds=row.get("estimated_seconds", 120),
            ).model_dump()
        )

    return APIResponse(
        data={
            "count": len(safe_questions),
            "questions": safe_questions,
        }
    )
