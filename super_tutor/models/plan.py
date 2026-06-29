"""学习计划模型 — 个性化学习计划数据结构。

【功能说明】
定义 StudyPlan Pydantic 模型，代表基于诊断评估生成的完整学习计划。
包含拓扑排序后的知识点序列和按日排期的学习/复习条目。

核心计算属性：
- item_count: 排期条目总数
- completed_count: 已完成条目数
- progress: 完成进度（0.0–1.0）

【耦合关系】
- 依赖 models/mastery.py 的 ReviewItem 类
- 被 PlanEngine 创建并持久化到数据库
- 被 app.py 的 _render_plan_tab() 渲染学习路径 UI
- 从 AssessmentReport 获取 mastery_map 作为输入
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from super_tutor.models.mastery import ReviewItem


# ============================================================================
# StudyPlan — 学习计划
# ============================================================================


class StudyPlan(BaseModel):
    """基于诊断评估生成的个性化学习计划。

    包含：
    1. kp_sequence: 拓扑排序后的知识点 ID 序列（从基础到高级）
    2. schedule: 每个知识点的日活动安排（ReviewItem 列表）

    工作流：
    1. AssessmentEngine 生成 AssessmentReport
    2. PlanEngine 从 Report 提取 mastery_map
    3. PlanEngine 拓扑排序 + 优先级计算 → StudyPlan
    4. StudyPlan 存储到 st.session_state 和数据库 study_plans 表
    """

    plan_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="计划唯一标识（UUID v4）",
    )
    student_id: str = Field(
        ...,
        description="学生 ID（目前固定为 'default'）",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="计划标题，如'个性化学习计划'",
    )
    status: str = Field(
        default="active",
        description="计划状态：draft(草稿)/active(进行中)/completed(已完成)/paused(暂停)/archived(归档)",
    )
    kp_sequence: list[str] = Field(
        default_factory=list,
        description="拓扑排序后的知识点 ID 序列（前驱→后继，按依赖关系排列）",
    )
    schedule: list[ReviewItem] = Field(
        default_factory=list,
        description="排期条目列表（按日期升序），每天一个知识点",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601 格式）",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="最后更新时间（ISO 8601 格式）",
    )

    # -- 计算属性（不存入数据库）-----------------------------------------------

    @property
    def item_count(self) -> int:
        """排期条目总数 = schedule 列表长度。"""
        return len(self.schedule)

    @property
    def completed_count(self) -> int:
        """已完成条目数 = schedule 中 completed=True 的条目数。"""
        return sum(1 for it in self.schedule if it.completed)

    @property
    def progress(self) -> float:
        """完成进度（0.0–1.0）。

        空计划（无排期条目）返回 0.0。
        """
        if not self.schedule:
            return 0.0
        return round(self.completed_count / len(self.schedule), 4)
