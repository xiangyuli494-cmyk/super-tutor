"""Super Tutor — HTTP 请求/响应 Pydantic Schemas。

与领域模型（super_tutor/models/）分离：领域模型负责业务逻辑，
本模块的 DTO 仅定义 API 边界的数据形状。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

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
    """上传学习材料的请求体。"""

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
    course_type: str = Field(
        default="",
        description="课程类型，如'physics'、'mathematics'",
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
    kp_count: int = Field(default=0, description="已解析的知识点数量")
    course_type: str = Field(default="", description="课程类型")
    created_at: str = Field(default="", description="创建时间 (ISO 8601)")


# ============================================================================
# Quiz（测验）
# ============================================================================


class CreateQuizRequest(BaseModel):
    """创建测验（生成题目）的请求体。"""

    kp_ids: list[str] = Field(
        ...,
        min_length=1,
        description="要考查的知识点 ID 列表",
    )
    count: int = Field(
        default=5,
        ge=1,
        le=50,
        description="期望生成的题目数量",
    )
    difficulty: str = Field(
        default="medium",
        description="整体难度：beginner / easy / medium / hard / expert",
    )
    types: Optional[list[str]] = Field(
        default=None,
        description="题型过滤，不传则覆盖全部题型",
    )
    student_id: str = Field(
        default="default",
        description="学生标识",
    )


class AnswerItem(BaseModel):
    """单题作答条目。"""

    question_id: str = Field(..., description="题目 ID")
    student_answer: Any = Field(..., description="学生提交的答案")
    time_spent_seconds: int = Field(default=0, ge=0, description="本题耗时（秒）")


class SubmitAnswersRequest(BaseModel):
    """提交作答的请求体。"""

    answers: list[AnswerItem] = Field(
        ...,
        min_length=1,
        description="作答列表",
    )
    student_id: str = Field(
        default="default",
        description="学生标识",
    )


class QuestionResponse(BaseModel):
    """返回给前端的题目（不含正确答案）。"""

    question_id: str = Field(..., description="题目 ID")
    stem: str = Field(..., description="题干（Markdown）")
    type: str = Field(..., description="题目类型")
    difficulty: str = Field(..., description="难度等级")
    topic: str = Field(default="", description="主题标签")
    kp_id: str = Field(default="", description="关联知识点 ID")
    options: list[dict[str, Any]] = Field(
        default_factory=list, description="选项列表"
    )
    hints: list[str] = Field(
        default_factory=list, description="渐进式提示"
    )
    points: float = Field(default=1.0, description="分值")
    estimated_seconds: int = Field(default=120, description="预计耗时（秒）")


class AttemptResponse(BaseModel):
    """单题批改结果。"""

    attempt_id: str = Field(..., description="作答记录 ID")
    question_id: str = Field(..., description="题目 ID")
    kp_id: str = Field(default="", description="知识点 ID")
    student_answer: Any = Field(default=None, description="学生答案")
    is_correct: Optional[bool] = Field(default=None, description="是否正确")
    time_spent_seconds: int = Field(default=0, description="耗时（秒）")


class QuizResultResponse(BaseModel):
    """测验批改结果响应。"""

    quiz_id: str = Field(default="", description="测验标识")
    attempts: list[dict[str, Any]] = Field(
        default_factory=list, description="逐题批改结果"
    )
    correct_count: int = Field(default=0, description="正确数")
    total_count: int = Field(default=0, description="总题数")
    accuracy: float = Field(default=0.0, description="正确率 (0-1)")


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

    kp_id: str = Field(..., description="知识点 ID")
    title: str = Field(default="", description="知识点标题")
    mastery_level: float = Field(default=0.0, description="掌握度 (0-1)")
    total_attempts: int = Field(default=0, description="作答次数")
    correct_attempts: int = Field(default=0, description="正确次数")
    accuracy: float = Field(default=0.0, description="正确率 (0-1)")


class WrongQuestionItem(BaseModel):
    """错题本条目。"""

    wrong_id: str = Field(..., description="错题记录 ID")
    question_id: str = Field(..., description="题目 ID")
    kp_id: str = Field(default="", description="知识点 ID")
    wrong_answer: Optional[str] = Field(default=None, description="学生的错误答案")
    correct_answer: str = Field(default="", description="正确答案")
    attempt_count: int = Field(default=1, description="累计答错次数")
    resolution_status: str = Field(default="unresolved", description="解决状态")
    last_wrong_at: Optional[str] = Field(default=None, description="最近答错时间")


class PlanTodayResponse(BaseModel):
    """今日复习清单响应。"""

    date: str = Field(
        default_factory=lambda: date.today().isoformat(),
        description="日期 (ISO 8601)",
    )
    items: list[dict[str, Any]] = Field(
        default_factory=list, description="今日排期条目"
    )
