"""Super Tutor — 学生仪表盘路由。

提供学习概览、掌握度明细、错题本和今日复习清单。
直接从 knowledge_points / quiz_attempts / wrong_questions 表聚合。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from super_tutor.core.database import Database
from super_tutor.routes.deps import use_db
from super_tutor.routes.schemas import (
    APIResponse,
    DashboardResponse,
    MasteryItem,
    PlanTodayResponse,
    WrongQuestionItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/students", tags=["dashboard"])


# ===================================================================
# Dashboard — 学习概览
# ===================================================================


@router.get("/{student_id}/dashboard", response_model=APIResponse)
async def get_dashboard(
    student_id: str,
    db: Database = Depends(use_db),
) -> APIResponse:
    """获取学生学习仪表盘概览。

    聚合 quiz_attempts，计算总体正确率、统计薄弱/优势知识点。
    """
    all_attempts, _total = await db.list_attempts_by_student(
        student_id, limit=10000, offset=0
    )

    if not all_attempts:
        return APIResponse(
            data=DashboardResponse(
                student_id=student_id,
            ).model_dump(),
            message="暂无作答记录。完成一次测验后即可查看仪表盘。",
        )

    total_questions = len(all_attempts)
    correct_count = sum(1 for a in all_attempts if a.get("is_correct"))
    overall_accuracy = correct_count / total_questions if total_questions > 0 else 0.0

    recent = all_attempts[:10]

    # Aggregate by kp_id
    question_ids = list({
        a.get("question_id", "") for a in all_attempts if a.get("question_id")
    })
    question_map = await db.get_questions_batch(question_ids)

    kp_stats: dict[str, dict[str, int]] = {}
    for a in all_attempts:
        q = question_map.get(a.get("question_id", ""))
        kp_id = q.get("kp_id", "unknown") if q else "unknown"
        if kp_id not in kp_stats:
            kp_stats[kp_id] = {"total": 0, "correct": 0}
        kp_stats[kp_id]["total"] += 1
        if a.get("is_correct"):
            kp_stats[kp_id]["correct"] += 1

    # Resolve KP titles
    weak_topics: list[str] = []
    strong_topics: list[str] = []
    for kp_id, stats in kp_stats.items():
        acc = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
        label = kp_id[:8] + "…"
        kp_row = await db.get_knowledge_point(kp_id)
        if kp_row:
            label = kp_row.get("title", label)
        if acc < 0.6:
            weak_topics.append(label)
        elif acc >= 0.85 and stats["total"] >= 2:
            strong_topics.append(label)

    return APIResponse(
        data=DashboardResponse(
            student_id=student_id,
            total_questions_attempted=total_questions,
            correct_count=correct_count,
            overall_accuracy=round(overall_accuracy, 3),
            weak_topics=weak_topics,
            strong_topics=strong_topics,
            recent_attempts=recent,
        ).model_dump(),
    )


# ===================================================================
# Mastery — 掌握度明细（从 knowledge_points 读取）
# ===================================================================


@router.get("/{student_id}/mastery", response_model=APIResponse)
async def get_mastery(
    student_id: str,
    db: Database = Depends(use_db),
) -> APIResponse:
    """获取学生各知识点的掌握度明细。

    从 knowledge_points 表读取 mastery_level，并结合 quiz_attempts
    计算作答统计。
    """
    kps = await db.list_knowledge_points_with_mastery()

    # Get per-KP attempt stats
    all_attempts, _ = await db.list_attempts_by_student(
        student_id, limit=10000, offset=0
    )

    # Aggregate per kp_id
    kp_attempts: dict[str, dict[str, int]] = {}
    question_ids = list({a.get("question_id", "") for a in all_attempts if a.get("question_id")})
    question_map = await db.get_questions_batch(question_ids)

    for a in all_attempts:
        q = question_map.get(a.get("question_id", ""))
        kp_id = q.get("kp_id", "") if q else ""
        if not kp_id:
            continue
        if kp_id not in kp_attempts:
            kp_attempts[kp_id] = {"total": 0, "correct": 0}
        kp_attempts[kp_id]["total"] += 1
        if a.get("is_correct"):
            kp_attempts[kp_id]["correct"] += 1

    items: list[dict] = []
    for kp in kps:
        kp_id = kp.get("kp_id", "")
        stats = kp_attempts.get(kp_id, {"total": 0, "correct": 0})
        total_a = stats["total"]
        correct_a = stats["correct"]
        accuracy = correct_a / total_a if total_a > 0 else 0.0

        items.append(
            MasteryItem(
                kp_id=kp_id,
                title=kp.get("title", ""),
                mastery_level=kp.get("mastery_level", 0.0),
                total_attempts=total_a,
                correct_attempts=correct_a,
                accuracy=round(accuracy, 3),
            ).model_dump()
        )

    if not items:
        return APIResponse(
            data={"student_id": student_id, "items": []},
            message="暂无知识点数据。请先上传教材并完成解析。",
        )

    return APIResponse(
        data={
            "student_id": student_id,
            "items": items,
        }
    )


# ===================================================================
# Wrong Questions — 错题本
# ===================================================================


@router.get("/{student_id}/wrong-questions", response_model=APIResponse)
async def get_wrong_questions(
    student_id: str,
    limit: int = Query(default=20, ge=1, le=100, description="返回条数上限"),
    offset: int = Query(default=0, ge=0, description="分页偏移"),
    db: Database = Depends(use_db),
) -> APIResponse:
    """获取学生错题本。

    从 wrong_questions 表直接查询，按收录时间倒序排列。
    """
    rows, total = await db.list_wrong_questions_by_student(
        student_id, limit=limit, offset=offset
    )

    items: list[dict] = []
    for row in rows:
        items.append(
            WrongQuestionItem(
                wrong_id=row["wrong_id"],
                question_id=row["question_id"],
                kp_id=row.get("kp_id", ""),
                wrong_answer=row.get("wrong_answer"),
                correct_answer=row.get("correct_answer", ""),
                attempt_count=row.get("attempt_count", 1),
                resolution_status=row.get("resolution_status", "unresolved"),
                last_wrong_at=row.get("updated_at"),
            ).model_dump()
        )

    return APIResponse(
        data={
            "student_id": student_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }
    )


# ===================================================================
# Today's Plan — 今日复习清单
# ===================================================================


@router.get("/{student_id}/plan/today", response_model=APIResponse)
async def get_today_plan(
    student_id: str,
    db: Database = Depends(use_db),
) -> APIResponse:
    """获取学生今日复习清单。

    从 study_plans 表的 kp_sequence JSON 中筛选当天条目。
    """
    today = date.today().isoformat()
    items = await db.get_today_items(student_id, today)

    if not items:
        return APIResponse(
            data=PlanTodayResponse(
                date=today,
                items=[],
            ).model_dump(),
            message="今日暂无排期。完成测验并生成学习计划后即可查看。",
        )

    return APIResponse(
        data=PlanTodayResponse(
            date=today,
            items=[
                {
                    "item_id": it.get("item_id", ""),
                    "knowledge_node_id": it.get("knowledge_node_id", ""),
                    "activity_type": it.get("activity_type", ""),
                    "scheduled_date": it.get("scheduled_date", ""),
                    "estimated_minutes": it.get("estimated_minutes", 0),
                    "completed": bool(it.get("completed", False)),
                    "notes": it.get("notes", ""),
                }
                for it in items
            ],
        ).model_dump(),
    )


@router.post(
    "/{student_id}/plan/items/{plan_id}/toggle",
    response_model=APIResponse,
)
async def toggle_plan_item(
    student_id: str,
    plan_id: str,
    body: dict[str, Any] = Body(...),
    db: Database = Depends(use_db),
) -> APIResponse:
    """切换复习计划条目的完成状态。

    Body: {"item_index": 0, "completed": true}
    """
    completed = body.get("completed", False)
    item_index = body.get("item_index", 0)
    await db.update_kp_sequence_item(plan_id, item_index, {"completed": bool(completed)})
    return APIResponse(
        data={"plan_id": plan_id, "item_index": item_index, "completed": bool(completed)},
        message="ok",
    )
