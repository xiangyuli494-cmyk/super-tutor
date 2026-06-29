"""Super Tutor — 数据模型层。

【功能说明】
提供全项目共用的枚举定义和 Pydantic 数据模型：

枚举（enums.py）：
- DifficultyLevel — 5 级难度（beginner/easy/medium/hard/expert）
- QuestionType   — 6 种题型（选择/判断/填空/简答/论述/编程）

Pydantic 模型（7 个）：
- KnowledgePoint      — 知识点（对应 knowledge_points 表，含双向 DAG 关系）
- Question            — 单道题目（对应 questions 表，支持 6 种题型）
- QuizAttempt         — 单题作答记录（对应 quiz_attempts 表）
- KPAssessmentResult  — 单知识点诊断评估结果（纯内存，不入库）
- AssessmentReport    — 完整诊断评估报告（纯内存，不入库）
- ReviewItem          — 排期条目（存入 study_plans.kp_sequence JSON 字段）
- StudyPlan           — 个性化学习计划（对应 study_plans 表）
- SocraticTurn        — 单轮苏格拉底追问（纯 session_state，不入库）

【模型与数据库表的映射关系】
knowledge_points  ←→  KnowledgePoint
questions         ←→  Question
quiz_attempts     ←→  QuizAttempt
study_plans       ←→  StudyPlan (schdeule 字段 ←→ list[ReviewItem])
wrong_questions   ←→  无专用 Pydantic 模型（通过 dict 操作）
materials         ←→  无专用 Pydantic 模型（通过 dict 操作）

【耦合关系】
- enums.py 被所有 Engine 和 Model 模块依赖（全项目共用）
- 所有 Pydantic 模型被 engine/ 层的对应引擎创建和修改
- 所有模型被 app.py 用于 UI 渲染和数据展示
- 本层不依赖 core/ 和 engine/（纯数据结构层）
- 仅依赖 pydantic（外部库）和自身的 enums.py
"""

from super_tutor.models.enums import (
    DifficultyLevel,
    QuestionType,
)

from super_tutor.models.knowledge import (
    KnowledgePoint,
)

from super_tutor.models.quiz import (
    Question,
    QuizAttempt,
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
    "DifficultyLevel",
    "QuestionType",
    # Knowledge
    "KnowledgePoint",
    # Quiz
    "Question",
    "QuizAttempt",
    # Assessment
    "AssessmentReport",
    "KPAssessmentResult",
    # Mastery
    "ReviewItem",
    "StudyPlan",
    # Socratic
    "SocraticTurn",
]
