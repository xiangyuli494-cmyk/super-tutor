"""Super Tutor — 全项目共用枚举定义。

所有枚举统一在此模块定义，其他模块通过 ``from super_tutor.models.enums import ...`` 引用。
"""

from enum import Enum


# ============================================================================
# CourseType — 课程/学科类型
# ============================================================================


class CourseType(str, Enum):
    """课程类型，对应不同的学科领域。"""

    PHYSICS = "physics"
    MATHEMATICS = "mathematics"
    CHEMISTRY = "chemistry"
    BIOLOGY = "biology"
    COMPUTER_SCIENCE = "computer_science"
    HISTORY = "history"
    LITERATURE = "literature"
    ENGLISH = "english"
    GENERAL = "general"


# ============================================================================
# DifficultyLevel — 难度等级
# ============================================================================


class DifficultyLevel(str, Enum):
    """题目 / 学习材料的难度等级。"""

    BEGINNER = "beginner"        # 入门 — 概念了解、基础记忆
    EASY = "easy"                # 简单 — 单一知识点、直接套用
    MEDIUM = "medium"            # 中等 — 多知识点组合、需要分析
    HARD = "hard"                # 困难 — 综合应用、深层推理
    EXPERT = "expert"            # 专家 — 竞赛级 / 研究级


# ============================================================================
# QuestionType — 题目类型
# ============================================================================


class QuestionType(str, Enum):
    """题目类型，覆盖常见教学测评形式。"""

    MULTIPLE_CHOICE = "multiple_choice"  # 选择题
    TRUE_FALSE = "true_false"            # 判断题
    FILL_IN_BLANK = "fill_in_blank"      # 填空题
    SHORT_ANSWER = "short_answer"        # 简答题
    ESSAY = "essay"                      # 论述题 / 作文
    CODING = "coding"                    # 编程题


# ============================================================================
# PlanStatus — 学习计划状态
# ============================================================================


class PlanStatus(str, Enum):
    """学习计划的生命周期状态。"""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"

