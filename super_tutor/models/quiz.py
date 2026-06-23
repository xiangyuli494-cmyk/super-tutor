"""Super Tutor Agent — 测验模型。

定义题目、测验会话、作答记录和错误概念标签，覆盖出题→作答→诊断完整链路。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from super_tutor.models.enums import DifficultyLevel, QuestionType, QuizStatus


# ============================================================================
# Question — 单道题目
# ============================================================================


class Question(BaseModel):
    """题库中的一道题目，支持多种题型。

    ``correct_answer`` 的类型因题型而异：
    - 选择题 → 选项 key 字符串（如 ``"A"``）
    - 判断题 → ``true`` / ``false``
    - 填空题 → 字符串或字符串列表（多空）
    - 简答/论述 → 参考答案文本
    - 编程题 → ``{"language": "python", "test_cases": [...], "reference_solution": "..."}``
    - 匹配题 → ``{"left": [...], "right": [...]}`` 或匹配对列表
    """

    question_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="题目唯一标识",
    )
    type: QuestionType = Field(
        ...,
        description="题目类型",
    )
    difficulty: DifficultyLevel = Field(
        default=DifficultyLevel.MEDIUM,
        description="难度等级",
    )
    subject: str = Field(
        default="",
        description="所属学科",
    )
    topic: str = Field(
        default="",
        description="主题标签，如'牛顿定律'、'矩阵运算'",
    )
    stem: str = Field(
        ...,
        min_length=1,
        description="题干（支持 Markdown）",
    )
    options: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "选项列表。选择题：[{'key': 'A', 'text': '...'}, ...]；"
            "匹配题：[{'left': '...', 'right': '...'}, ...]"
        ),
    )
    correct_answer: Any = Field(
        ...,
        description="正确答案，格式依题型而定（详见类文档）",
    )
    explanation: str = Field(
        default="",
        description="答案解析 / 解题思路（支持 Markdown）",
    )
    hints: list[str] = Field(
        default_factory=list,
        description="渐进式提示，从笼统到具体排列",
    )
    knowledge_node_ids: list[str] = Field(
        default_factory=list,
        description="考查的知识图谱节点 ID 列表",
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="出题依据的原始 KnowledgeChunk ID 列表",
    )
    estimated_seconds: int = Field(
        default=120,
        ge=0,
        description="预计作答耗时（秒）",
    )
    points: float = Field(
        default=1.0,
        ge=0.0,
        description="分值",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="分类标签，便于检索与组卷",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据（出题人、审核状态、使用次数等）",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )

    @property
    def hint_count(self) -> int:
        """提示数量。"""
        return len(self.hints)


# ============================================================================
# QuizSession — 测验会话
# ============================================================================


class QuizSession(BaseModel):
    """一次完整的测验会话，将多道题目按序组织后发布给学生作答。

    生命周期通过 ``status`` 字段追踪：
    ``draft → ready → published → in_progress → submitted → graded → reviewed → archived``
    """

    session_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="会话唯一标识",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="测验标题",
    )
    description: str = Field(
        default="",
        description="测验说明 / 考试须知",
    )
    subject: str = Field(
        default="",
        description="所属学科",
    )
    question_ids: list[str] = Field(
        default_factory=list,
        description="题目 ID 列表（按序出题）",
    )
    difficulty: DifficultyLevel = Field(
        default=DifficultyLevel.MEDIUM,
        description="整体难度",
    )
    time_limit_minutes: Optional[int] = Field(
        default=None,
        ge=0,
        description="时间限制（分钟），None 表示不限时",
    )
    total_points: float = Field(
        default=0.0,
        ge=0.0,
        description="满分值",
    )
    passing_score: float = Field(
        default=60.0,
        ge=0.0,
        description="及格线",
    )
    shuffle_questions: bool = Field(
        default=False,
        description="是否随机打乱题目顺序",
    )
    show_hints: bool = Field(
        default=True,
        description="是否允许学生查看提示",
    )
    status: QuizStatus = Field(
        default=QuizStatus.DRAFT,
        description="测验状态",
    )
    student_id: Optional[str] = Field(
        default=None,
        description="作答学生 ID（匿名模式下为 None）",
    )
    started_at: Optional[str] = Field(
        default=None,
        description="学生开始作答时间（ISO 8601）",
    )
    submitted_at: Optional[str] = Field(
        default=None,
        description="学生提交时间（ISO 8601）",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据（班级、课程、标签等）",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )

    @property
    def question_count(self) -> int:
        """题目数量。"""
        return len(self.question_ids)

    @property
    def is_timed(self) -> bool:
        """是否限时。"""
        return self.time_limit_minutes is not None


# ============================================================================
# QuizAttempt — 单题作答记录
# ============================================================================


class QuizAttempt(BaseModel):
    """学生在一次测验会话中对单道题的作答记录。

    支持同一题目多次尝试（通过 ``attempt_number`` 区分），
    记录提示使用情况和自评置信度，并可关联诊断出的错误概念。
    """

    attempt_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="作答记录唯一标识",
    )
    session_id: str = Field(
        ...,
        description="所属 QuizSession ID",
    )
    question_id: str = Field(
        ...,
        description="所答 Question ID",
    )
    student_answer: Any = Field(
        default=None,
        description="学生提交的答案（格式与 Question.correct_answer 对齐）",
    )
    is_correct: Optional[bool] = Field(
        default=None,
        description="是否批改为正确（None 表示尚未批改）",
    )
    score: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="实际得分（None 表示尚未批改）",
    )
    time_spent_seconds: int = Field(
        default=0,
        ge=0,
        description="本题作答耗时（秒）",
    )
    hints_used: int = Field(
        default=0,
        ge=0,
        description="查看提示次数",
    )
    attempt_number: int = Field(
        default=1,
        ge=1,
        description="本题第几次尝试（从 1 开始）",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="学生自评置信度（0-1），None 表示未自评",
    )
    misconception_ids: list[str] = Field(
        default_factory=list,
        description="诊断出的 MisconceptionTag ID 列表",
    )
    note: str = Field(
        default="",
        description="学生笔记 / 草稿（可选）",
    )
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="开始作答时间（ISO 8601）",
    )
    submitted_at: Optional[str] = Field(
        default=None,
        description="提交时间（ISO 8601）",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )

    @property
    def is_graded(self) -> bool:
        """是否已批改。"""
        return self.is_correct is not None

    @property
    def is_confident(self) -> bool:
        """学生是否自信（置信度 >= 0.7）。"""
        return self.confidence is not None and self.confidence >= 0.7


# ============================================================================
# MisconceptionTag — 错误概念标签
# ============================================================================


class MisconceptionTag(BaseModel):
    """学生答题中暴露出的错误概念 / 常见误区。

    标签由诊断引擎自动生成或教师手动标注，可关联到知识点和补救建议，
    用于生成个性化复习计划和针对性练习。
    """

    tag_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="标签唯一标识",
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="标签名，如'符号错误'、'动量与动能混淆'",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="错误概念的详细描述（支持 Markdown）",
    )
    category: str = Field(
        default="conceptual",
        description=(
            "错误类别：conceptual(概念混淆) / calculation(计算错误) / "
            "careless(粗心) / application(应用不当) / logic(逻辑错误) / "
            "notation(符号/书写) / incomplete(不完整)"
        ),
    )
    severity: str = Field(
        default="moderate",
        description="严重程度：minor(轻微) / moderate(中等) / critical(严重)",
    )
    knowledge_node_ids: list[str] = Field(
        default_factory=list,
        description="关联的知识图谱节点 ID，用于定位薄弱环节",
    )
    remediation_hint: str = Field(
        default="",
        description="补救建议 / 矫正策略（支持 Markdown），如'建议重新学习牛顿第三定律的受力分析'",
    )
    occurrence_count: int = Field(
        default=0,
        ge=0,
        description="该错误概念在所有学生中出现的累计次数（用于统计分析）",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )


# ============================================================================
# SocraticHint — 苏格拉底式渐进引导提示
# ============================================================================


class SocraticHint(BaseModel):
    """苏格拉底式追问的一条渐进引导提示。

    每条提示绑定到一个 Question，按 ``level`` 分层：
    - **1** — 笼统引导：指出思考方向，不给任何具体线索
    - **2** — 方向提示：缩小思考范围，引入相关概念
    - **3** — 接近答案：给出具体线索或公式，逼近但不等于答案

    提示的触发由 ``trigger_after_failures`` 控制：
    学生连续答错 N 次后才展示对应层级的提示。

    与 Question.hints（``list[str]``）的关系：
    ``Question.hints`` 是简版的纯文本提示列表；本模型是结构化版本，
    支持触发条件、难度适配和效果追踪，用于进阶的苏格拉底多轮对话场景。
    """

    hint_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="提示唯一标识",
    )
    question_id: str = Field(
        ...,
        description="关联的 Question ID",
    )
    level: int = Field(
        ...,
        ge=1,
        le=3,
        description=(
            "提示层级：1=笼统引导（'这道题考察什么概念？'），"
            "2=方向提示（'注意力和加速度的关系'），"
            "3=接近答案（'代入 F=ma，已知 m 和 a'）"
        ),
    )
    content: str = Field(
        ...,
        min_length=1,
        description="提示正文（支持 Markdown）",
    )
    trigger_after_failures: int = Field(
        default=0,
        ge=0,
        description="学生累计答错 N 次后才展示此提示（0=首次作答即可见）",
    )
    difficulty_adapt: bool = Field(
        default=False,
        description=(
            "是否根据学生掌握度动态调整。True 时，"
            "若 MasteryRecord.mastery_level >= 0.7，自动跳过该提示"
        ),
    )
    times_shown: int = Field(
        default=0,
        ge=0,
        description="该提示已展示次数（用于统计与 A/B 测试）",
    )
    was_helpful: Optional[bool] = Field(
        default=None,
        description=(
            "该提示是否帮助学生答对（None=未评估，True=有助，False=无效果）"
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )
