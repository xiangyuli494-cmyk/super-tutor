"""Super Tutor — 测验会话路由。

核心路由文件，覆盖测验全生命周期：
创建 → 获取题目 → 提交作答 → 查看结果 → 生成复习计划。
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from super_tutor.core.database import Database
from super_tutor.core.exceptions import TutorError
from super_tutor.core.llm_client import LLMClient
from super_tutor.core.orchestrator import Orchestrator
from super_tutor.core.role_manager import RoleManager
from super_tutor.core.token_tracker import TokenTracker
from super_tutor.routes.dependencies import (
    build_orchestrator,
    use_db,
    use_llm_client,
    use_orchestrator_registry,
    use_role_manager,
    use_token_tracker,
)
from super_tutor.routes.schemas import (
    APIResponse,
    CreateSessionRequest,
    PlanResponse,
    QuestionResponse,
    ResultResponse,
    SessionResponse,
    SubmitAnswersRequest,
    SubmitAnswersResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["quizzes"])


# ===================================================================
# Helper
# ===================================================================


def _get_orch(
    session_id: str,
    registry: dict[str, Orchestrator],
) -> Orchestrator:
    """从注册表中查找 Orchestrator，找不到则 404。"""
    orch = registry.get(session_id)
    if orch is None:
        raise HTTPException(
            status_code=404,
            detail=f"会话不存在或已过期：{session_id}",
        )
    return orch


# ===================================================================
# Endpoints
# ===================================================================


@router.post("", response_model=APIResponse, status_code=201)
async def create_session(
    req: CreateSessionRequest,
    db: Database = Depends(use_db),
    llm: LLMClient = Depends(use_llm_client),
    roles: RoleManager = Depends(use_role_manager),
    registry: dict[str, Orchestrator] = Depends(use_orchestrator_registry),
    tracker: TokenTracker = Depends(use_token_tracker),
) -> APIResponse:
    """创建测验会话。

    初始化一个新的 Orchestrator 实例，关联到指定的学习材料，
    并注册到会话注册表中。后续通过 ``session_id`` 访问该会话。
    """
    # 验证材料存在
    material = await db.get_material(req.material_id)
    if material is None:
        raise HTTPException(
            status_code=404,
            detail=f"学习材料不存在：{req.material_id}",
        )

    session_id = str(uuid4())

    orch = build_orchestrator(
        db=db, llm_client=llm, role_manager=roles, token_tracker=tracker,
    )
    await orch.initialize(
        session_context={
            "material_id": req.material_id,
            "session_id": session_id,
            "student_id": req.student_id,
        }
    )

    registry[session_id] = orch
    logger.info(
        "Session created: id=%s material=%s title=%r",
        session_id,
        req.material_id,
        req.title,
    )

    return APIResponse(
        data=SessionResponse(
            session_id=session_id,
            material_id=req.material_id,
            title=req.title,
            state=orch.state.value,
            question_count=0,
        ).model_dump()
    )


@router.get("/{session_id}/questions", response_model=APIResponse)
async def get_questions(
    session_id: str,
    registry: dict[str, Orchestrator] = Depends(use_orchestrator_registry),
) -> APIResponse:
    """获取测验题目列表。

    首次调用时自动触发 PDF 解析与题目生成（IDLE → PARSING → QUIZ_GEN）。
    后续调用直接返回已缓存的题目。

    返回的题目**不含正确答案**，确保前端无法通过抓包作弊。
    """
    orch = _get_orch(session_id, registry)

    try:
        # 根据当前状态决定需要推进几步
        from super_tutor.models.enums import PipelinePhase

        if orch.state == PipelinePhase.IDLE:
            await orch.start()  # IDLE → PARSING
            await orch.proceed()  # PARSING → QUIZ_GEN
        elif orch.state == PipelinePhase.PARSING:
            await orch.proceed()  # PARSING → QUIZ_GEN
        elif orch.state not in (
            PipelinePhase.QUIZ_GEN,
            PipelinePhase.EVALUATING,
            PipelinePhase.PLANNING,
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"当前状态 '{orch.state.value}' 不支持获取题目。"
                    "请等待解析完成或创建新会话。"
                ),
            )
    except TutorError as exc:
        logger.exception("Quiz generation failed for session=%s", session_id)
        raise HTTPException(
            status_code=500,
            detail=f"题目生成失败：{exc}",
        ) from exc

    # 提取题目（去掉正确答案）
    raw_questions: list[dict] = orch._artifacts.get("questions", [])
    safe_questions: list[dict] = []
    for q in raw_questions:
        safe_questions.append(
            QuestionResponse(
                question_id=q.get("question_id", ""),
                stem=q.get("stem", ""),
                type=q.get("type", "multiple_choice"),
                difficulty=q.get("difficulty", "medium"),
                topic=q.get("topic", ""),
                options=q.get("options", []),
                hints=q.get("hints", []),
                points=q.get("points", 1.0),
                estimated_seconds=q.get("estimated_seconds", 120),
            ).model_dump()
        )

    return APIResponse(
        data={
            "session_id": session_id,
            "state": orch.state.value,
            "question_count": len(safe_questions),
            "questions": safe_questions,
        }
    )


@router.post("/{session_id}/answers", response_model=APIResponse)
async def submit_answers(
    session_id: str,
    req: SubmitAnswersRequest,
    registry: dict[str, Orchestrator] = Depends(use_orchestrator_registry),
) -> APIResponse:
    """提交学生作答并自动触发批改。

    将作答注入 Orchestrator，推进至 EVALUATING 阶段。
    LLM 会逐题判定对错、打分，并诊断错题背后的迷思概念。
    """
    orch = _get_orch(session_id, registry)

    from super_tutor.models.enums import PipelinePhase

    if orch.state != PipelinePhase.QUIZ_GEN:
        raise HTTPException(
            status_code=409,
            detail=(
                f"当前状态 '{orch.state.value}' 不允许提交作答。"
                f"需要 '{PipelinePhase.QUIZ_GEN.value}' 状态。"
            ),
        )

    # 从 session context 获取 student_id
    student_id = orch._session_context.get("student_id", "")

    # 反序列化作答并注入 student_id
    answers = [
        {
            "question_id": a.question_id,
            "student_answer": a.student_answer,
            "student_id": student_id,
            "time_spent_seconds": a.time_spent_seconds,
            "hints_used": a.hints_used,
            "attempt_number": a.attempt_number,
            "confidence": a.confidence,
        }
        for a in req.answers
    ]

    try:
        accepted = await orch.submit_answers(answers, quiz_session_id=session_id)
        await orch.proceed()  # QUIZ_GEN → EVALUATING
    except TutorError as exc:
        logger.exception("Answer submission failed for session=%s", session_id)
        raise HTTPException(
            status_code=500,
            detail=f"作答提交或批改失败：{exc}",
        ) from exc

    logger.info(
        "Answers submitted: session=%s accepted=%d/%d",
        session_id,
        accepted,
        len(req.answers),
    )

    return APIResponse(
        data=SubmitAnswersResponse(
            session_id=session_id,
            accepted_count=accepted,
            state=orch.state.value,
        ).model_dump()
    )


@router.get("/{session_id}/results", response_model=APIResponse)
async def get_results(
    session_id: str,
    registry: dict[str, Orchestrator] = Depends(use_orchestrator_registry),
) -> APIResponse:
    """获取批改结果与迷思概念诊断。

    需在提交作答后调用。返回逐题判定、得分、迷思概念标签及总体评估。
    """
    orch = _get_orch(session_id, registry)

    from super_tutor.models.enums import PipelinePhase

    if orch.state not in (PipelinePhase.EVALUATING, PipelinePhase.PLANNING):
        raise HTTPException(
            status_code=409,
            detail=(
                f"当前状态 '{orch.state.value}' 尚无批改结果。"
                "请先提交作答（POST /sessions/{id}/answers）。"
            ),
        )

    attempts = orch._artifacts.get("attempts", [])
    misconceptions = orch._artifacts.get("misconceptions", [])

    # 从原始 LLM 输出中提取 summary（如果存在）
    evaluating_output = orch._artifacts.get("evaluating_output", "")
    summary: dict = {}
    if isinstance(evaluating_output, dict):
        summary = evaluating_output.get("summary", {})

    return APIResponse(
        data=ResultResponse(
            session_id=session_id,
            state=orch.state.value,
            attempts=attempts,
            misconceptions=misconceptions,
            summary=summary,
        ).model_dump()
    )


@router.post("/{session_id}/plan", response_model=APIResponse)
async def generate_plan(
    session_id: str,
    registry: dict[str, Orchestrator] = Depends(use_orchestrator_registry),
) -> APIResponse:
    """生成 SM-2 间隔重复复习计划。

    基于批改结果和迷思概念诊断，由 Tutor 角色生成个性化排期。
    每天学习量不超过 2 小时，薄弱知识点排在高优先级。
    """
    orch = _get_orch(session_id, registry)

    from super_tutor.models.enums import PipelinePhase

    if orch.state == PipelinePhase.EVALUATING:
        try:
            await orch.proceed()  # EVALUATING → PLANNING
        except TutorError as exc:
            logger.exception("Plan generation failed for session=%s", session_id)
            raise HTTPException(
                status_code=500,
                detail=f"排期计划生成失败：{exc}",
            ) from exc
    elif orch.state == PipelinePhase.PLANNING:
        # 已经生成，直接返回
        pass
    else:
        raise HTTPException(
            status_code=409,
            detail=(
                f"当前状态 '{orch.state.value}' 不支持生成排期。"
                "需要先完成批改（EVALUATING 状态）。"
            ),
        )

    plan_items = orch._artifacts.get("plan_items", [])
    planning_output = orch._artifacts.get("planning_output", "")
    plan_summary = ""
    if isinstance(planning_output, dict):
        plan_summary = planning_output.get("summary", "")

    return APIResponse(
        data=PlanResponse(
            session_id=session_id,
            state=orch.state.value,
            plan_items=plan_items,
            summary=plan_summary,
        ).model_dump()
    )
