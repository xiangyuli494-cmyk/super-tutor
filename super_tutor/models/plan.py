"""Super Tutor — 学习计划模型。

定义基于知识点拓扑排序的个性化学习计划，
包含排期条目和进度追踪。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from super_tutor.models.mastery import ReviewItem


# ============================================================================
# StudyPlan — 学习计划
# ============================================================================


class StudyPlan(BaseModel):
    """基于诊断评估生成的学习计划。

    包含拓扑排序后的知识点序列和按日排期的学习/复习条目。
    学生完成条目后更新对应掌握度，系统据此动态调整后续计划。
    """

    plan_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="计划唯一标识",
    )
    student_id: str = Field(
        ...,
        description="学生 ID",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="计划标题，如'高二物理力学复习计划'",
    )
    status: str = Field(
        default="active",
        description="计划状态：draft / active / completed / paused / archived",
    )
    kp_sequence: list[str] = Field(
        default_factory=list,
        description="拓扑排序后的知识点 ID 序列（前驱 → 后继）",
    )
    schedule: list[ReviewItem] = Field(
        default_factory=list,
        description="排期条目列表（按日期升序）",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="最后更新时间（ISO 8601）",
    )

    # -- 查询方法 -----------------------------------------------------------

    def get_items_for_date(self, date_str: str) -> list[ReviewItem]:
        """返回指定日期的所有排期条目。"""
        return [it for it in self.schedule if it.scheduled_date == date_str]

    def get_pending_items(self) -> list[ReviewItem]:
        """返回所有未完成的条目（含逾期），按日期升序。"""
        return sorted(
            [it for it in self.schedule if not it.completed],
            key=lambda it: it.scheduled_date,
        )

    def get_overdue_items(self) -> list[ReviewItem]:
        """返回所有逾期未完成的条目。"""
        today = datetime.now(timezone.utc).date().isoformat()
        return [
            it
            for it in self.schedule
            if not it.completed and it.scheduled_date < today
        ]

    def get_upcoming_items(self, days: int = 7) -> list[ReviewItem]:
        """返回未来 N 天内的排期条目。"""
        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=days)
        return [
            it
            for it in self.schedule
            if today.isoformat() <= it.scheduled_date <= cutoff.isoformat()
        ]

    # -- 统计 ---------------------------------------------------------------

    @property
    def item_count(self) -> int:
        """排期条目总数。"""
        return len(self.schedule)

    @property
    def completed_count(self) -> int:
        """已完成条目数。"""
        return sum(1 for it in self.schedule if it.completed)

    @property
    def progress(self) -> float:
        """完成进度（0-1），空计划返回 0.0。"""
        if not self.schedule:
            return 0.0
        return round(self.completed_count / len(self.schedule), 4)
