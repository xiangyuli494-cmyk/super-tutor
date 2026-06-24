"""Super Tutor — HTTP 请求/响应 Pydantic Schemas。

与领域模型（super_tutor/models/）分离：领域模型负责业务逻辑，
本模块的 DTO 仅定义 API 边界的数据形状。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ============================================================================
# 通用响应封装
# ============================================================================


class APIResponse(BaseModel):
    """标准 API 成功响应。

    所有成功端点统一使用此格式包裹返回数据：
    ``{"code": 0, "message": "success", "data": {...}}``
    """

    code: int = Field(default=0, description="业务状态码，0 表示成功")
    message: str = Field(default="success", description="可读的状态描述")
    data: Any = Field(default=None, description="响应载荷")


class ErrorDetail(BaseModel):
    """API 错误响应。"""

    code: int = Field(..., description="业务错误码")
    message: str = Field(..., description="错误描述")
    detail: str = Field(default="", description="详细错误信息（调试用）")


# ============================================================================
# Materials（材料管理）
# ============================================================================


class MaterialUploadRequest(BaseModel):
    """上传学习材料的请求体。

    MVP 阶段接收原始文本而非 PDF 文件流，
    待 PyMuPDF 集成后增加 file upload 支持。
    """

    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="材料标题，如'大学物理·力学篇'",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="材料正文（PDF 提取后的文本或 Markdown）",
    )
    subject: str = Field(
        default="",
        description="所属学科，如'物理'、'数学'",
    )
    description: str = Field(
        default="",
        max_length=512,
        description="材料简介",
    )


class MaterialStatusResponse(BaseModel):
    """材料解析状态查询响应。"""

    material_id: str = Field(..., description="材料唯一标识")
    title: str = Field(..., description="材料标题")
    status: str = Field(..., description="处理状态：draft / processing / ready")
    chunk_count: int = Field(default=0, description="已解析的知识片段数量")
    subject: str = Field(default="", description="学科")
    created_at: str = Field(default="", description="创建时间 (ISO 8601)")


# ============================================================================
# Quiz Sessions（测验会话）
# ============================================================================


class CreateSessionRequest(BaseModel):
    """创建测验会话的请求体。"""

    material_id: str = Field(
        ...,
        min_length=1,
        description="关联的学习材料 ID",
    )
    title: str = Field(
        default="新测验",
        max_length=256,
        description="测验标题",
    )
    question_count: int = Field(
        default=10,
        ge=1,
        le=50,
        description="期望生成的题目数量",
    )
    difficulty: str = Field(
        default="medium",
        description="整体难度：beginner / easy / medium / hard / expert",
    )
    student_id: Optional[str] = Field(
        default=None,
        description="作答学生 ID（匿名模式下为空）",
    )


class SessionResponse(BaseModel):
    """测验会话状态响应。"""

    session_id: str = Field(..., description="会话唯一标识")
    material_id: str = Field(..., description="关联的材料 ID")
    title: str = Field(..., description="测验标题")
    state: str = Field(..., description="Orchestrator 工作流状态")
    question_count: int = Field(default=0, description="已生成题目数量")


class AnswerItem(BaseModel):
    """单题作答条目。"""

    question_id: str = Field(..., description="题目 ID")
    student_answer: Any = Field(..., description="学生提交的答案")
    time_spent_seconds: int = Field(default=0, ge=0, description="本题耗时（秒）")
    hints_used: int = Field(default=0, ge=0, description="使用提示次数")
    attempt_number: int = Field(default=1, ge=1, description="第几次尝试")
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="自评置信度"
    )


class SubmitAnswersRequest(BaseModel):
    """提交作答的请求体。"""

    answers: list[AnswerItem] = Field(
        ...,
        min_length=1,
        description="作答列表",
    )


class QuestionResponse(BaseModel):
    """返回给前端的题目（不含正确答案）。"""

    question_id: str = Field(..., description="题目 ID")
    stem: str = Field(..., description="题干（Markdown）")
    type: str = Field(..., description="题目类型")
    difficulty: str = Field(..., description="难度等级")
    topic: str = Field(default="", description="主题标签")
    options: list[dict[str, Any]] = Field(
        default_factory=list, description="选项列表"
    )
    hints: list[str] = Field(
        default_factory=list, description="渐进式提示"
    )
    points: float = Field(default=1.0, description="分值")
    estimated_seconds: int = Field(default=120, description="预计耗时（秒）")


class ResultResponse(BaseModel):
    """批改结果响应。"""

    session_id: str = Field(..., description="会话 ID")
    state: str = Field(..., description="当前工作流状态")
    attempts: list[dict[str, Any]] = Field(
        default_factory=list, description="逐题批改结果"
    )
    misconceptions: list[dict[str, Any]] = Field(
        default_factory=list, description="迷思概念诊断"
    )
    summary: dict[str, Any] = Field(
        default_factory=dict, description="评估汇总"
    )


class PlanResponse(BaseModel):
    """学习计划响应。"""

    session_id: str = Field(..., description="会话 ID")
    state: str = Field(..., description="当前工作流状态")
    plan_items: list[dict[str, Any]] = Field(
        default_factory=list, description="排期条目列表"
    )
    summary: str = Field(default="", description="计划概述")


class SubmitAnswersResponse(BaseModel):
    """提交作答的确认响应。"""

    session_id: str = Field(..., description="会话 ID")
    accepted_count: int = Field(..., description="成功接收的作答条数")
    state: str = Field(..., description="提交后的工作流状态")


# ============================================================================
# Dashboard（学生仪表盘）
# ============================================================================


class DashboardResponse(BaseModel):
    """学生仪表盘响应。"""

    student_id: str = Field(..., description="学生 ID")
    total_questions_attempted: int = Field(default=0, description="累计作答数")
    correct_count: int = Field(default=0, description="正确数")
    overall_accuracy: float = Field(default=0.0, description="总体正确率 (0-1)")
    weak_topics: list[str] = Field(
        default_factory=list, description="薄弱知识点（需加强）"
    )
    strong_topics: list[str] = Field(
        default_factory=list, description="优势知识点"
    )
    recent_attempts: list[dict[str, Any]] = Field(
        default_factory=list, description="最近 10 条作答记录"
    )


class MasteryItem(BaseModel):
    """单个知识点的掌握度概览。"""

    knowledge_node_id: str = Field(..., description="知识点 ID")
    total_attempts: int = Field(default=0, description="作答次数")
    correct_attempts: int = Field(default=0, description="正确次数")
    accuracy: float = Field(default=0.0, description="正确率 (0-1)")
    last_attempt_at: Optional[str] = Field(
        default=None, description="最近作答时间"
    )


class WrongQuestionItem(BaseModel):
    """错题本条目。"""

    attempt_id: str = Field(..., description="作答记录 ID")
    question_id: str = Field(..., description="题目 ID")
    student_answer: Any = Field(default=None, description="学生的错误答案")
    is_correct: bool = Field(default=False, description="是否正确")
    score: Optional[float] = Field(default=None, description="得分")
    submitted_at: Optional[str] = Field(default=None, description="提交时间")
    note: str = Field(default="", description="批注")


class PlanTodayResponse(BaseModel):
    """今日复习清单响应。"""

    date: str = Field(
        default_factory=lambda: date.today().isoformat(),
        description="日期 (ISO 8601)",
    )
    items: list[dict[str, Any]] = Field(
        default_factory=list, description="今日排期条目"
    )


# ============================================================================
# Tokens（用量统计）
# ============================================================================


class TokenStatsResponse(BaseModel):
    """Token 用量统计响应。"""

    total_prompt_tokens: int = Field(default=0, description="累计 Prompt Token")
    total_completion_tokens: int = Field(default=0, description="累计 Completion Token")
    total_tokens: int = Field(default=0, description="累计 Token")
    call_count: int = Field(default=0, description="API 调用次数")
    by_role: dict[str, Any] = Field(
        default_factory=dict, description="按角色分组的 Token 用量（含 prompt/completion/total）"
    )
    budget: int = Field(default=0, description="Token 预算上限")
    used: int = Field(default=0, description="已消耗 Token 数")
    remaining: int = Field(default=0, description="剩余可用 Token 数")
    by_tier: dict[str, Any] = Field(
        default_factory=dict, description="按算力档位分组的 Token 用量"
    )
