"""诊断性评估模型 — 评估报告和知识点评估结果数据结构。

【功能说明】
定义 AssessmentEngine 的输出结构：
1. KPAssessmentResult — 单个知识点在一次诊断中的评估结果
2. AssessmentReport — 完整的诊断评估报告（聚合所有 KP 结果）

核心概念：
- initial_mastery: 基于答题准确率的初始掌握度
- adjusted_mastery: 经 3 条前置规则校准后的最终掌握度
- confidence: 掌握度评估的置信度（Rule 1 会折扣此值）
- status: 掌握状态标签（mastered/learning/need_review/need_relearn）

【耦合关系】
- 被 AssessmentEngine 创建和修改（apply_prerequisite_rules 直接修改字段）
- 被 app.py 用于渲染评估报告 UI
- 被 PlanEngine 的输入（通过 mastery_map 传递 adjusted_mastery）
- 不依赖其他模型模块
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


# ============================================================================
# KPAssessmentResult — 单个知识点的评估结果
# ============================================================================


class KPAssessmentResult(BaseModel):
    """单个知识点在一次诊断性评估中的结果。

    包含题目作答统计、掌握度初始计算值和经前置规则调整后的最终掌握度。

    状态标签说明（由 3 条前置规则 + 最终赋值决定）：
    - ``mastered`` — 掌握度 >= 0.8，无需复习
    - ``learning`` — 0.5 <= 掌握度 < 0.8，正常学习进度
    - ``need_review`` — 后继正确但此前驱有误（Rule 2），需复习
    - ``need_relearn`` — 掌握度 <= 0.5，或 >=3 个后继均错（Rule 3），需重新学习
    """

    kp_id: str = Field(
        ...,
        description="知识点 ID",
    )
    title: str = Field(
        default="",
        description="知识点标题（用于 UI 展示）",
    )
    prerequisite_ids: list[str] = Field(
        default_factory=list,
        description="前置知识点 ID 列表（用于 Rule 1/2 遍历）",
    )
    successor_ids: list[str] = Field(
        default_factory=list,
        description="后继知识点 ID 列表（用于 Rule 3 遍历）",
    )
    question_ids: list[str] = Field(
        default_factory=list,
        description="本次评估中该 KP 对应的题目 ID 列表",
    )
    correct_count: int = Field(
        default=0,
        ge=0,
        description="正确作答数",
    )
    total_count: int = Field(
        default=0,
        ge=0,
        description="该 KP 的总题目数",
    )
    accuracy: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="本 KP 的原始正确率 = correct_count / total_count",
    )
    initial_mastery: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="初始掌握度（= accuracy），未经前置规则调整",
    )
    adjusted_mastery: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="经 3 条前置规则调整后的最终掌握度",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="掌握度评估的置信度（Rule 1 会折扣至 0.7×）",
    )
    status: str = Field(
        default="learning",
        description="掌握状态标签：mastered / learning / need_review / need_relearn",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="前置规则触发的警告消息列表（用于 UI 展示）",
    )
    note: str = Field(
        default="",
        description="诊断备注（预留字段）",
    )


# ============================================================================
# AssessmentReport — 一次完整的诊断性评估报告
# ============================================================================


class AssessmentReport(BaseModel):
    """一次完整的诊断性评估报告。

    聚合所有 KP 的评估结果，提供整体统计和按掌握度排序的薄弱点/强项列表。

    注意：
    - weak_kps 和 strong_kps 由 AssessmentEngine.grade() 填充
    - mastery_distribution 是计算属性（@property），不存入数据库
    """

    assessment_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="评估报告唯一标识（UUID v4）",
    )
    student_id: str = Field(
        default="default",
        description="学生 ID（目前固定为 'default'）",
    )
    kp_ids: list[str] = Field(
        default_factory=list,
        description="本次评估涉及的知识点 ID 列表（拓扑排序序）",
    )
    total_questions: int = Field(
        default=0,
        ge=0,
        description="评估总题目数",
    )
    correct_count: int = Field(
        default=0,
        ge=0,
        description="总正确作答数",
    )
    accuracy: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="整体正确率 = correct_count / total_questions",
    )
    kp_results: list[KPAssessmentResult] = Field(
        default_factory=list,
        description="每个知识点的详细评估结果列表",
    )
    rules_applied: list[str] = Field(
        default_factory=list,
        description="本次评估中触发的 3 条前置规则描述列表（用于 UI 展开显示）",
    )
    weak_kps: list[KPAssessmentResult] = Field(
        default_factory=list,
        description="薄弱知识点列表（adjusted_mastery <= 0.5），按掌握度升序排列",
    )
    strong_kps: list[KPAssessmentResult] = Field(
        default_factory=list,
        description="强项知识点列表（adjusted_mastery >= 0.8），按掌握度降序排列",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="评估过程中的全局警告信息（如错题本写入失败等）",
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="评估生成时间（ISO 8601 格式）",
    )

    # -- 计算属性 ------------------------------------------------------------

    @property
    def mastery_distribution(self) -> dict[str, int]:
        """掌握度分布统计。

        统计各状态下（mastered/learning/need_review/need_relearn）
        的知识点数量，用于在评估报告 UI 中展示分布概览。

        Returns:
            dict: 如 {"mastered": 3, "learning": 5, "need_review": 2, "need_relearn": 1}
        """
        dist: dict[str, int] = {
            "mastered": 0,
            "learning": 0,
            "need_review": 0,
            "need_relearn": 0,
        }
        for r in self.kp_results:
            dist[r.status] = dist.get(r.status, 0) + 1
        return dist
