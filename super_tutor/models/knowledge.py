"""知识点模型 — 从教材中提取的独立知识点数据结构。

【功能说明】
定义 KnowledgePoint Pydantic 模型，对应数据库 knowledge_points 表。
每个知识点包含：原文内容、标题、难度评估、关键词列表、
前置/后继依赖关系（形成双向 DAG）、掌握程度追踪。

【字段说明】
- kp_id: 知识点唯一标识（UUID）
- material_id: 所属学习材料 ID（外键 → materials 表）
- title: 知识点标题（如"牛顿第二定律"）
- summary: 一句话摘要（≤256 字符）
- content: 知识点原文内容（200–3000 字）
- keywords: 关键词列表（3–8 个）
- difficulty: 难度等级（beginner/easy/medium/hard/expert）
- prerequisite_ids: 前置知识点 ID 列表（必须先掌握这些才能学此 KP）
- successor_ids: 后继知识点 ID 列表（依赖此 KP 的知识点）
- mastery_level: 掌握程度（0.0–1.0）
- assessment_count: 已评估次数

【耦合关系】
- 被 KnowledgeEngine 用于解析结果和查询返回
- 被 app.py 用于 UI 展示（知识点表格）
- 被 quiz_engine 和 assessment_engine 用于出题上下文
- 依赖 models/enums.py 的 DifficultyLevel 枚举
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from super_tutor.models.enums import DifficultyLevel


# ============================================================================
# KnowledgePoint — 知识点
# ============================================================================


class KnowledgePoint(BaseModel):
    """从教材中提取的独立知识点。

    对应 ``knowledge_points`` 表。每个知识点是一个可在 5–30 分钟内
    学会的完整概念或技能，通过 prerequisite_ids 和 successor_ids
    形成双向有向无环图（DAG）。

    注意：
    - prerequisite_ids 和 successor_ids 在数据库中存为 JSON 字符串，
      通过 _parse_json_list() 工具函数解析
    - mastery_level 由 AssessmentEngine 诊断后更新
    """

    kp_id: str = Field(
        ...,
        description="知识点唯一标识（UUID v4）",
    )
    material_id: str = Field(
        ...,
        description="所属学习材料 ID（外键 → materials.material_id）",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="知识点标题，如'牛顿第二定律'、'矩阵乘法'",
    )
    summary: str = Field(
        default="",
        max_length=256,
        description="一句话摘要（≤256 字符），用于列表展示和出题上下文",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="知识点正文内容，保持教材原文格式（含公式、代码等）",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="关键词列表（3–8 个），用于检索和分类",
    )
    difficulty: DifficultyLevel = Field(
        default=DifficultyLevel.MEDIUM,
        description="难度等级：beginner | easy | medium | hard | expert",
    )
    course_type: str = Field(
        default="",
        description="课程类型标签，如'physics'、'mathematics'",
    )
    chapter_index: int = Field(
        default=0,
        ge=0,
        description="章节序号（0-based），用于排序和展示",
    )
    prerequisite_ids: list[str] = Field(
        default_factory=list,
        description="前置知识点 ID 列表 — 必须先掌握这些 KP 才能学习本 KP",
    )
    successor_ids: list[str] = Field(
        default_factory=list,
        description="后继知识点 ID 列表 — 依赖本 KP 的知识点（双向关系）",
    )
    mastery_level: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="掌握程度（0.0=完全未掌握，1.0=完全掌握）",
    )
    assessment_count: int = Field(
        default=0,
        ge=0,
        description="已参与诊断评估的次数",
    )
    created_at: str = Field(
        ...,
        description="创建时间（ISO 8601 格式）",
    )
    updated_at: str = Field(
        ...,
        description="最后更新时间（ISO 8601 格式）",
    )
