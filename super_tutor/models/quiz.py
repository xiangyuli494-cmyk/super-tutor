"""测验模型 — 题目、作答记录和错题本数据结构。

【功能说明】
定义从出题到作答到错题追踪的完整数据链路：
1. Question — 单道题目（支持 6 种题型）
2. QuizAttempt — 单题作答记录（学生答案 + 批改结果）

【耦合关系】
- 依赖 models/enums.py 的 DifficultyLevel 和 QuestionType 枚举
- 被 QuizEngine 用于生成题目和批改
- 被 AssessmentEngine 用于诊断性评估（委托 QuizEngine）
- 被 app.py 用于 UI 渲染题目和展示批改结果
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from super_tutor.models.enums import DifficultyLevel, QuestionType


# ============================================================================
# Question — 单道题目
# ============================================================================


class Question(BaseModel):
    """题库中的一道题目，支持 6 种题型。

    ``correct_answer`` 的类型因题型而异：
    - 选择题 → 选项 key 字符串（如 ``"A"``）
    - 判断题 → ``true`` / ``false``
    - 填空题 → 字符串或字符串列表（多空）
    - 简答/论述 → 参考答案文本
    - 编程题 → ``{"language":"python", "test_cases":[...], "reference_solution":"..."}``

    注意：
    - options 仅在 multiple_choice 时有值（4 个选项 A/B/C/D）
    - hints 为渐进式提示列表，从笼统到具体排列
    """

    question_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="题目唯一标识（UUID v4）",
    )
    type: QuestionType = Field(
        ...,
        description="题目类型：multiple_choice/true_false/fill_in_blank/short_answer/essay/coding",
    )
    difficulty: DifficultyLevel = Field(
        default=DifficultyLevel.MEDIUM,
        description="难度等级",
    )
    subject: str = Field(
        default="",
        description="所属学科（如'物理'、'数学'）",
    )
    topic: str = Field(
        default="",
        description="主题标签，通常使用对应 KP 的 title",
    )
    stem: str = Field(
        ...,
        min_length=1,
        description="题干内容（支持 Markdown 格式，公式用 $LaTeX$ 语法）",
    )
    options: list[dict[str, Any]] = Field(
        default_factory=list,
        description="选择题选项列表。格式：[{'key':'A','text':'...'}, ...]。非选择题为空数组。",
    )
    correct_answer: Any = Field(
        ...,
        description="正确答案，格式依题型而定（详见类文档注释）",
    )
    explanation: str = Field(
        default="",
        description="答案解析 / 解题思路（支持 Markdown），说明为什么对 + 为什么错",
    )
    hints: list[str] = Field(
        default_factory=list,
        description="渐进式提示列表，从笼统方向到具体线索（2–3 条）",
    )
    kp_id: str = Field(
        default="",
        description="直接关联的知识点 ID（外键 → knowledge_points.kp_id）",
    )
    kp_context: str = Field(
        default="",
        description="出题时注入的上下文 JSON（如诊断标签等）",
    )
    estimated_seconds: int = Field(
        default=120,
        ge=0,
        description="预计作答耗时（秒）",
    )
    points: float = Field(
        default=1.0,
        ge=0.0,
        description="题目分值",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="分类标签列表，便于检索与组卷",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据（出题来源、生成时间等）",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601 格式）",
    )


# ============================================================================
# QuizAttempt — 单题作答记录
# ============================================================================


class QuizAttempt(BaseModel):
    """学生单题作答记录 — 精简为批改核心字段。

    记录学生答案、批改结果（is_correct）和作答耗时。
    每条记录对应一道题的一次作答，直接关联到知识点。

    注意：
    - is_correct 为 None 表示尚未批改
    - student_answer 格式应与 Question.correct_answer 对齐
    """

    attempt_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="作答记录唯一标识（UUID v4）",
    )
    student_id: str = Field(
        default="",
        description="学生标识（目前固定为 'default'）",
    )
    question_id: str = Field(
        ...,
        description="所答题目 ID（外键 → questions.question_id）",
    )
    kp_id: str = Field(
        default="",
        description="关联的知识点 ID（外键 → knowledge_points.kp_id）",
    )
    student_answer: Any = Field(
        default=None,
        description="学生提交的答案（格式与 Question.correct_answer 对齐）",
    )
    is_correct: Optional[bool] = Field(
        default=None,
        description="是否批改为正确。None=尚未批改，True=正确，False=错误",
    )
    time_spent_seconds: int = Field(
        default=0,
        ge=0,
        description="本题作答耗时（秒）",
    )
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="开始作答时间（ISO 8601 格式）",
    )
    submitted_at: Optional[str] = Field(
        default=None,
        description="提交批改时间（ISO 8601 格式）",
    )
