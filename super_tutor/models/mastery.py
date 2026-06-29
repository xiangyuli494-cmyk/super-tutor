"""学习计划排期模型 — 排期条目数据结构。

【功能说明】
定义 ReviewItem Pydantic 模型，代表学习计划中的一个排期条目。
每个条目对应一个知识点在特定日期的学习/复习活动。

【耦合关系】
- 被 PlanEngine 用于生成排期（plan_engine.py）
- 被 StudyPlan 模型引用（plan.py 的 schedule 字段）
- 不依赖项目内其他模块
"""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ============================================================================
# ReviewItem — 排期中的单个学习/复习条目
# ============================================================================


class ReviewItem(BaseModel):
    """学习计划中的单个复习/学习条目。

    由 PlanEngine.generate() 根据知识点的掌握度和优先级自动生成。
    每个条目对应一个知识点在某一天的特定学习活动。

    Attributes:
        item_id: 条目唯一标识（UUID）
        knowledge_node_id: 对应的知识点 ID（关联 knowledge_points.kp_id）
        scheduled_date: 计划日期（ISO 8601 date 格式，如 "2026-06-25"）
        activity_type: 活动类型 — learn_new(新学)/review(复习)/practice(练习)/quiz(测验)
        estimated_minutes: 预计学习耗时（分钟），由难度和掌握度差距计算
        completed: 是否已完成
        completed_at: 完成时间（ISO 8601 格式）
        notes: 备注信息
    """

    item_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="条目唯一标识（UUID v4）",
    )
    knowledge_node_id: str = Field(
        ...,
        description="对应的知识点 ID（关联 knowledge_points.kp_id）",
    )
    scheduled_date: str = Field(
        ...,
        description="计划学习日期（ISO 8601 date 格式，如'2026-06-25'）",
    )
    activity_type: str = Field(
        default="review",
        description="活动类型：learn_new(新学)/review(复习)/practice(练习)/quiz(测验)",
    )
    estimated_minutes: int = Field(
        default=15,
        ge=0,
        description="预计耗时（分钟），范围 10–120",
    )
    completed: bool = Field(
        default=False,
        description="是否已完成",
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="完成时间（ISO 8601 格式），未完成时为 None",
    )
    notes: str = Field(
        default="",
        description="备注信息（记录掌握度和优先级等元信息）",
    )
