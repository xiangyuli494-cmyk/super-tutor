"""Super Tutor — 数据模型层。

提供全项目共用的枚举、Pydantic 模型和类型定义。
"""

from super_tutor.models.enums import (
    CourseType,
    DifficultyLevel,
    PlanStatus,
    QuestionType,
)

from super_tutor.models.knowledge import (
    KnowledgeChunk,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    KnowledgePoint,
    Material,
)

from super_tutor.models.quiz import (
    Question,
    QuizAttempt,
    WrongQuestion,
)

from super_tutor.models.assessment import (
    AssessmentReport,
    KPAssessmentResult,
)

from super_tutor.models.mastery import ReviewItem

from super_tutor.models.plan import StudyPlan

from super_tutor.models.socratic import SocraticTurn

__all__ = [
    # Enums
    "CourseType",
    "DifficultyLevel",
    "PlanStatus",
    "QuestionType",
    # Knowledge
    "KnowledgeChunk",
    "KnowledgeEdge",
    "KnowledgeGraph",
    "KnowledgeNode",
    "KnowledgePoint",
    "Material",
    # Quiz
    "Question",
    "QuizAttempt",
    "WrongQuestion",
    # Assessment
    "AssessmentReport",
    "KPAssessmentResult",
    # Mastery
    "ReviewItem",
    "StudyPlan",
    # Socratic
    "SocraticTurn",
]
